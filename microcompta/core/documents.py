"""Registry of every recorded file. Adding one here is what queues it for Drive.

There is a single way in, so a document cannot be saved locally and forgotten by the
backup.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Callable

from . import clock
from .db import Database
from .errors import ValidationError

KIND_DIRS = {
    "invoice": "factures",
    "receipt": "recus",
    "export": "exports",
    "snapshot": "sauvegardes",
}


def file_hashes(path: Path) -> tuple[str, str, int]:
    """(sha256, md5, size). Drive reports md5, so the queue needs both."""
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), md5.hexdigest(), size


def safe_name(name: str) -> str:
    """Keep a file name readable, and valid on Windows and in a Drive query."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "document"


class Documents:
    def __init__(self, db: Database, root: Path,
                 on_added: Callable[[int], None] | None = None):
        self.db = db
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.on_added = on_added

    def clear_tmp(self) -> None:
        """Previews and interrupted work. Best effort: a preview may still be open."""
        folder = self.root / ".tmp"
        if not folder.is_dir():
            return
        for leftover in folder.iterdir():
            try:
                leftover.unlink()
            except OSError:
                pass

    def tmp_dir(self) -> Path:
        """Scratch space on the same volume, so finished files can be moved in atomically."""
        d = self.root / ".tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _destination(self, kind: str, year: int, name: str) -> Path:
        folder = self.root / str(year) / KIND_DIRS[kind]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / safe_name(name)
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = folder / f"{stem}_{n}{suffix}"
            n += 1
        return dest

    def add_file(
        self,
        source: Path | str,
        *,
        kind: str,
        year: int,
        name: str | None = None,
        title: str | None = None,
        ledger_seq: int | None = None,
        invoice_id: int | None = None,
        move: bool = False,
        read_only: bool = False,
    ) -> int:
        """Store a file under documents/<year>/<kind>/ and queue its upload."""
        if kind not in KIND_DIRS:
            raise ValidationError(f"Unknown document kind '{kind}'.")
        source = Path(source)
        if not source.is_file():
            raise ValidationError(f"File not found: {source}")
        dest = self._destination(kind, year, name or source.name)
        if move:
            os.replace(source, dest)
        else:
            shutil.copy2(source, dest)
        try:
            sha256, md5, size = file_hashes(dest)
            rel_path = dest.relative_to(self.root).as_posix()
            with self.db.transaction():
                doc_id = self.db.next_id("documents")
                self.db.execute(
                    "INSERT INTO documents (id, kind, title, rel_path, size, sha256, md5, year, "
                    "ledger_seq, invoice_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [doc_id, kind, title or dest.name, rel_path, size, sha256, md5, year,
                     ledger_seq, invoice_id, clock.now()],
                )
                if self.on_added is not None:
                    self.on_added(doc_id)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        if read_only:
            dest.chmod(stat.S_IREAD)
        return doc_id

    # -- reading ------------------------------------------------------------
    def get(self, doc_id: int) -> dict[str, Any] | None:
        return self.db.row("SELECT * FROM documents WHERE id = ?", [doc_id])

    def path_of(self, doc: dict[str, Any]) -> Path:
        return self.root / doc["rel_path"]

    def for_ledger(self, seq: int) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT * FROM documents WHERE ledger_seq = ? ORDER BY id", [seq]
        )

    def verify(self) -> list[str]:
        """Files that are missing or no longer match what was recorded."""
        problems = []
        for doc in self.db.rows("SELECT * FROM documents ORDER BY id"):
            path = self.path_of(doc)
            if not path.is_file():
                problems.append(f"Document missing from disk: {doc['rel_path']}")
            elif file_hashes(path)[0] != doc["sha256"]:
                problems.append(f"Document changed on disk: {doc['rel_path']}")
        return problems
