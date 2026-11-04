"""Google Drive backup: connection, per-document status, and how to set it up."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...backup import oauth
from ...config import oauth_client_path
from ...core.book import Book
from ..models import Col, local_time
from ..theme import BAD, GOOD, WARN
from ..widgets.table_view import DataTable
from .common import Banner, Chip, StatRow, card_frame, dim_label, guarded, heading

COLUMNS = [
    Col("status", "Status", "status", 72),
    Col("title", "Document", width=300),
    Col("kind", "Kind", width=64),
    Col("year", "Year", width=46),
    Col("size", "Size", "bytes", 70),
    Col("attempts", "Tries", "int", 46),
    Col("uploaded_at", "Uploaded", "datetime", 118),
    Col("next_attempt_at", "Next try", "datetime", 118),
    Col("last_error", "Last message", width=340),
    Col("drive_md5", "Drive checksum", width=230, tip="MD5 reported by Drive, compared with the local file."),
]

STEPS = (
    "<b>Connecting takes about 10 minutes, once. You do this yourself in your own browser, so "
    "the app never sees your Google password.</b>"
    "<ol style='margin-left:-20px'>"
    "<li>Go to <a style='color:#4f9cf9' href='https://console.cloud.google.com/'>"
    "console.cloud.google.com</a> and create a project.</li>"
    "<li>APIs &amp; Services &gt; Library: enable <b>Google Drive API</b>.</li>"
    "<li>Google Auth Platform: set the app name and your email, audience <b>External</b>.</li>"
    "<li><b>Publish the app (status: In production).</b> In Testing, Google cancels the sign-in "
    "every 7 days and the backup stops. This app asks only for <i>drive.file</i>, which isn't a "
    "sensitive scope.</li>"
    "<li>Clients &gt; Create client &gt; type <b>Desktop app</b>, then download the JSON.</li>"
    "<li>Press <b>Choose client file…</b> below and pick that file, then "
    "<b>Sign in with Google</b>. Tick the Drive box on the consent screen.</li>"
    "</ol>"
    "It can only see files it created, under a <b>MicroCompta</b> folder, sorted by year. It "
    "never deletes anything from Drive. The full steps are in the README."
)


class BackupPanel(QWidget):
    changed = Signal()
    status = Signal(str)
    upload_requested = Signal()
    snapshot_requested = Signal()
    sign_in_requested = Signal()
    sign_out_requested = Signal()

    def __init__(self, book: Book, tokens: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book
        self.tokens = tokens
        self._signing_in = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(heading("Google Drive backup"))
        self.state_chip = Chip("", "near")
        top.addWidget(self.state_chip)
        top.addStretch(1)
        self.client_button = QPushButton("Choose client file…")
        self.client_button.clicked.connect(lambda _c=False: self.choose_client_file())
        top.addWidget(self.client_button)
        self.sign_in_button = QPushButton("Sign in with Google")
        self.sign_in_button.setObjectName("primary")
        self.sign_in_button.clicked.connect(lambda _c=False: self.sign_in_requested.emit())
        top.addWidget(self.sign_in_button)
        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_button.setToolTip("Forget the token on this computer. Nothing in Drive changes.")
        self.sign_out_button.clicked.connect(lambda _c=False: self._sign_out())
        top.addWidget(self.sign_out_button)
        layout.addLayout(top)

        self.message = Banner("warn")
        layout.addWidget(self.message)

        self.stats = StatRow([
            ("pending", "Pending", "Waiting to upload, or waiting for a connection or sign-in."),
            ("uploaded", "Uploaded", "Checksum confirmed by Drive."),
            ("failed", "Failed", "Needs a look. Retried every 6 hours, or press Retry."),
            ("last", "Last upload", ""),
            ("snapshot", "Last snapshot", "Database copy and CSV exports."),
        ])
        layout.addWidget(self.stats)

        self.steps_card = card_frame()
        steps_lay = QVBoxLayout(self.steps_card)
        steps_lay.setContentsMargins(12, 8, 12, 8)
        self.steps = QLabel(STEPS)
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.RichText)
        self.steps.setOpenExternalLinks(True)
        steps_lay.addWidget(self.steps)
        layout.addWidget(self.steps_card)

        self.table = DataTable(COLUMNS, key="document_id")
        self.table.add_button("Upload now", self.upload_requested.emit, primary=True)
        self.table.add_button("Retry", self.retry_selected, tip="Try the selected document now.")
        self.table.add_button("Back up records now", self.snapshot_requested.emit,
                              tip="A database snapshot and CSV exports, if anything changed.")
        self.table.add_button("Open documents folder", self.open_folder)
        layout.addWidget(self.table, 1)
        layout.addWidget(dim_label(
            "Every invoice PDF, receipt and export is saved locally first, then queued here. The "
            "app works fully offline and catches up when it can. A document counts as uploaded "
            "only once Drive reports the same checksum as the local file."
        ))

    # -- state --------------------------------------------------------------
    def set_signing_in(self, on: bool) -> None:
        self._signing_in = on
        self.reload()

    def reload(self) -> None:
        state = self.tokens.state()
        connected = state == "connected"
        self.steps_card.setVisible(not connected)
        self.sign_in_button.setEnabled(state != "no_client" and not self._signing_in)
        self.sign_in_button.setText(
            "Waiting for the browser…" if self._signing_in else "Sign in with Google"
        )
        self.sign_out_button.setEnabled(connected)
        if connected:
            self.state_chip.setText("Connected")
            self.state_chip.set_level("ok")
        elif state == "signed_out":
            self.state_chip.setText("Not signed in")
            self.state_chip.set_level("warn")
        else:
            self.state_chip.setText("Not set up")
            self.state_chip.set_level("warn")

        counts = self.book.queue.counts()
        self.stats.set("pending", str(counts["pending"]), WARN if counts["pending"] else None)
        self.stats.set("uploaded", str(counts["uploaded"]), GOOD if counts["uploaded"] else None)
        self.stats.set("failed", str(counts["failed"]), BAD if counts["failed"] else None)
        last = self.book.queue.last_upload()
        self.stats.set("last", local_time(last) if last else "—")
        snapshot = self.book.db.get_meta("last_snapshot_at")
        self.stats.set("snapshot", local_time(datetime.fromisoformat(snapshot)) if snapshot else "—")

        rows = []
        for row in self.book.queue.rows():
            row = dict(row)
            if row["status"] == "uploaded":
                row["next_attempt_at"] = None
            rows.append(row)
        self.table.set_rows(rows)

        if not connected and counts["pending"]:
            self.message.show_text(
                f"{counts['pending']} document(s) saved locally but not yet in Drive. They upload "
                "once you connect.", "warn"
            )
        elif counts["failed"]:
            self.message.show_text(
                f"{counts['failed']} document(s) failed to upload. See Last message, then Retry.",
                "bad",
            )
        else:
            self.message.show_text("")

    # -- actions ------------------------------------------------------------
    def choose_client_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "The OAuth client JSON from Google Cloud Console", "", "JSON (*.json)"
        )
        if path:
            self.install_client_file(path)

    def install_client_file(self, path: str) -> bool:
        try:
            oauth.install_client_file(path, oauth_client_path())
        except (oauth.OAuthError, OSError) as exc:
            QMessageBox.warning(self, "Client file not accepted", str(exc))
            return False
        self.status.emit("Client file saved outside the project folder. Now sign in with Google.")
        self.reload()
        return True

    def _sign_out(self) -> None:
        reply = QMessageBox.question(
            self, "Sign out?",
            "This forgets the token on this computer. Nothing in Drive changes, and uploads wait "
            "until you sign in again.",
        )
        if reply == QMessageBox.Yes:
            self.sign_out_requested.emit()

    def retry_selected(self) -> None:
        row = self.table.current_row()
        guarded(self, "Retry", lambda: self.book.queue.retry(
            int(row["document_id"]) if row else None
        ))
        self.upload_requested.emit()

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.book.documents.root)))
