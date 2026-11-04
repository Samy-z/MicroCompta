"""The persistent upload queue. Qt-free: a QTimer in the UI just calls process_due().

A document stays in the queue until Drive reports its own checksum for the file and it
matches. Being offline or signed out is the normal case and costs nothing, because
those keep a document pending instead of counting it as failed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from ..core import clock
from ..core.db import Database
from ..core.documents import file_hashes
from .drive_client import (
    AuthRequired, DriveClient, PermanentDriveError, RemoteFile, TransientDriveError,
)

log = logging.getLogger(__name__)

ROOT_FOLDER = "MicroCompta"
PENDING = "pending"
UPLOADED = "uploaded"
FAILED = "failed"


def backoff_seconds(attempts: int) -> int:
    """1, 2, 4... minutes, capped at an hour."""
    return min(3600, 60 * 2 ** max(0, attempts - 1))


FAILED_RETRY_SECONDS = 6 * 3600


@dataclass
class QueueReport:
    uploaded: int = 0
    failed: int = 0
    deferred: int = 0
    stopped: str = ""          # why the run ended early
    needs_sign_in: bool = False
    newly_failed: list[str] = field(default_factory=list)


class UploadQueue:
    def __init__(self, db: Database, documents: Any = None):
        self.db = db
        self.documents = documents

    # -- state --------------------------------------------------------------
    def enqueue(self, document_id: int) -> None:
        self.db.execute(
            "INSERT INTO upload_queue (document_id, status, attempts, next_attempt_at) "
            "VALUES (?, ?, 0, ?) ON CONFLICT (document_id) DO NOTHING",
            [document_id, PENDING, clock.now()],
        )

    def counts(self) -> dict[str, int]:
        found = {PENDING: 0, UPLOADED: 0, FAILED: 0}
        for row in self.db.rows("SELECT status, count(*) AS n FROM upload_queue GROUP BY status"):
            found[row["status"]] = int(row["n"])
        return found

    def rows(self) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT q.*, d.kind, d.title, d.rel_path, d.size, d.year, d.created_at, d.md5, d.sha256 "
            "FROM upload_queue q JOIN documents d ON d.id = q.document_id "
            "ORDER BY d.id DESC"
        )

    def has_due(self) -> bool:
        return bool(self.db.scalar(
            "SELECT count(*) FROM upload_queue WHERE status <> ? AND next_attempt_at <= ?",
            [UPLOADED, clock.now()],
        ))

    def unfinished(self) -> int:
        return int(self.db.scalar(
            "SELECT count(*) FROM upload_queue WHERE status <> ?", [UPLOADED]
        ))

    def last_upload(self) -> Any:
        return self.db.scalar("SELECT max(uploaded_at) FROM upload_queue")

    def retry(self, document_id: int | None = None) -> None:
        """Try now rather than at the next scheduled attempt."""
        if document_id is None:
            self.db.execute(
                "UPDATE upload_queue SET next_attempt_at = ? WHERE status <> ?",
                [clock.now(), UPLOADED],
            )
        else:
            self.db.execute(
                "UPDATE upload_queue SET next_attempt_at = ? WHERE document_id = ? AND status <> ?",
                [clock.now(), document_id, UPLOADED],
            )

    def forget_folders(self) -> None:
        self.db.execute("DELETE FROM drive_folders")

    # -- processing ---------------------------------------------------------
    def process_due(self, client: DriveClient, limit: int = 50,
                    cancelled: Callable[[], bool] = lambda: False) -> QueueReport:
        report = QueueReport()
        due = self.db.rows(
            "SELECT q.document_id FROM upload_queue q WHERE q.status <> ? "
            "AND q.next_attempt_at <= ? ORDER BY q.document_id LIMIT ?",
            [UPLOADED, clock.now(), limit],
        )
        for row in due:
            if cancelled():
                report.stopped = "cancelled"
                break
            document_id = int(row["document_id"])
            doc = self.documents.get(document_id)
            try:
                self._upload_one(client, doc)
            except AuthRequired as exc:
                # No attempt counted: nothing is wrong with the document.
                self._note(document_id, str(exc))
                report.needs_sign_in = True
                report.stopped = str(exc)
                break
            except TransientDriveError as exc:
                self._defer(document_id, str(exc))
                report.deferred += 1
                report.stopped = str(exc)
                break  # Probably offline, so the rest of the batch would fail the same way.
            except PermanentDriveError as exc:
                if exc.status == 404:
                    self.forget_folders()  # a folder was removed in Drive; look it up again
                self._fail(document_id, str(exc))
                report.failed += 1
                report.newly_failed.append(doc["title"])
            except OSError as exc:
                self._fail(document_id, f"Could not read the local file: {exc}")
                report.failed += 1
                report.newly_failed.append(doc["title"])
            else:
                report.uploaded += 1
        return report

    def _upload_one(self, client: DriveClient, doc: dict[str, Any]) -> None:
        path = self.documents.path_of(doc)
        if not path.is_file():
            raise PermanentDriveError(f"The local file is missing: {doc['rel_path']}")
        sha256, md5, size = file_hashes(path)
        if sha256 != doc["sha256"]:
            raise PermanentDriveError(
                "The local file no longer matches what was recorded, so it was not uploaded."
            )

        queued = self.db.row(
            "SELECT drive_file_id FROM upload_queue WHERE document_id = ?", [doc["id"]]
        )
        name = path.name

        # A file from an earlier try whose checksum we couldn't read yet.
        if queued and queued["drive_file_id"]:
            remote = client.metadata(queued["drive_file_id"])
            if remote.md5 == md5:
                self._verify_and_finish(client, doc, remote, md5, sha256, size)
                return

        parent = self._folder_for(client, doc)
        # The reply to an earlier upload may have been lost. Never upload twice.
        for existing in client.find_files(name, parent):
            if existing.md5 == md5:
                self._verify_and_finish(client, doc, existing, md5, sha256, size)
                return

        uploaded = client.upload(path, name, parent)
        self.db.execute(
            "UPDATE upload_queue SET drive_file_id = ? WHERE document_id = ?",
            [uploaded.id, doc["id"]],
        )
        self._verify_and_finish(client, doc, uploaded, md5, sha256, size)

    def _verify_and_finish(self, client: DriveClient, doc: dict[str, Any], remote: RemoteFile,
                           md5: str, sha256: str, size: int) -> None:
        """Ask Drive again rather than trusting the reply to the upload."""
        checked = client.metadata(remote.id)
        if checked.md5 is None:
            raise TransientDriveError("Drive hasn't reported a checksum yet.")
        if checked.md5 != md5 or (checked.sha256 and checked.sha256 != sha256) or (
            checked.size is not None and checked.size != size
        ):
            # The bad copy stays in Drive (nothing is ever deleted). Forget its id so the
            # next try uploads again instead of re-checking the same wrong file.
            self.db.execute(
                "UPDATE upload_queue SET drive_file_id = NULL WHERE document_id = ?", [doc["id"]]
            )
            raise PermanentDriveError(
                f"Checksum mismatch: Drive holds {checked.md5}, expected {md5}. "
                "The wrong copy stays in Drive and the upload will be tried again."
            )
        self.db.execute(
            "UPDATE upload_queue SET status = ?, drive_file_id = ?, drive_md5 = ?, uploaded_at = ?, "
            "last_error = NULL WHERE document_id = ?",
            [UPLOADED, checked.id, checked.md5, clock.now(), doc["id"]],
        )
        log.info("Uploaded and verified document %s", doc["id"])

    def _folder_for(self, client: DriveClient, doc: dict[str, Any]) -> str:
        """MicroCompta / <year> / <kind>, created as needed and remembered."""
        parent: str | None = None
        path = ""
        kind_folder = doc["rel_path"].split("/")[1]
        for part in (ROOT_FOLDER, str(doc["year"]), kind_folder):
            path = f"{path}/{part}"
            known = self.db.scalar("SELECT folder_id FROM drive_folders WHERE path = ?", [path])
            if known is None:
                known = client.find_folder(part, parent) or client.create_folder(part, parent)
                self.db.execute(
                    "INSERT INTO drive_folders (path, folder_id) VALUES (?, ?) "
                    "ON CONFLICT (path) DO UPDATE SET folder_id = excluded.folder_id",
                    [path, known],
                )
            parent = known
        return parent

    # -- outcomes -----------------------------------------------------------
    def _note(self, document_id: int, message: str) -> None:
        self.db.execute(
            "UPDATE upload_queue SET last_error = ? WHERE document_id = ?", [message, document_id]
        )

    def _defer(self, document_id: int, message: str) -> None:
        attempts = int(self.db.scalar(
            "SELECT attempts FROM upload_queue WHERE document_id = ?", [document_id]
        )) + 1
        self.db.execute(
            "UPDATE upload_queue SET status = ?, attempts = ?, next_attempt_at = ?, last_error = ? "
            "WHERE document_id = ?",
            [PENDING, attempts, clock.now() + timedelta(seconds=backoff_seconds(attempts)),
             message, document_id],
        )

    def _fail(self, document_id: int, message: str) -> None:
        attempts = int(self.db.scalar(
            "SELECT attempts FROM upload_queue WHERE document_id = ?", [document_id]
        )) + 1
        self.db.execute(
            "UPDATE upload_queue SET status = ?, attempts = ?, next_attempt_at = ?, last_error = ? "
            "WHERE document_id = ?",
            [FAILED, attempts, clock.now() + timedelta(seconds=FAILED_RETRY_SECONDS),
             message, document_id],
        )
        log.warning("Upload of document %s failed: %s", document_id, message)
