"""Main window: payment form on the left, records on the right, QTimers for periodic work."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QStatusBar, QSystemTrayIcon, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from ..backup import oauth
from ..backup.drive_client import RestDriveClient
from ..config import APP_ICO, LOGO_DISPLAY_DARK, LOGO_ICON, oauth_client_path, token_path
from ..core import clock
from ..core.book import Book
from ..core.open_questions import OPEN_QUESTIONS
from .panels.annual_panel import AnnualPanel
from .panels.backup_panel import BackupPanel
from .panels.common import Banner
from .panels.dashboard_panel import DashboardPanel
from .panels.deadlines_panel import DeadlinesPanel
from .panels.invoices_panel import InvoicesPanel
from .panels.ledger_panel import LedgerPanel
from .panels.payment_form import PaymentForm
from .panels.settings_panel import SettingsPanel
from .theme import STYLESHEET
from .tray import TrayController
from .widgets.collapse import CollapsedStrip, DockTitleBar
from .workers import SignInWorker, UploadWorker

log = logging.getLogger(__name__)

BRAND_LOGO_HEIGHT = 68

QUEUE_TICK_MS = 60_000
REMINDER_TICK_MS = 60 * 60_000
SNAPSHOT_TICK_MS = 60 * 60_000
SNAPSHOT_AFTER_CHANGE_MS = 5 * 60_000
INTEGRITY_TICK_MS = 6 * 60 * 60_000
QUIT_FLUSH_LIMIT_MS = 30_000


class MainWindow(QMainWindow):
    def __init__(self, book: Book, *, client_factory: Callable[[], Any] | None = None,
                 tokens: Any = None):
        super().__init__()
        self.book = book
        self.tokens = tokens or oauth.TokenManager(oauth_client_path(), token_path())
        self.client_factory = client_factory or (lambda: RestDriveClient(self.tokens))
        self.tray: TrayController | None = None
        self._upload_worker: UploadWorker | None = None
        self._sign_in_worker: SignInWorker | None = None
        self._quitting = False
        self._flush_tried = False
        self._told_about_tray = False
        self._last_day = clock.today()
        self._closed = False

        self.setWindowTitle("MicroCompta")
        self.setStyleSheet(STYLESHEET)
        self._size_to_primary_screen()

        # -- left dock ------------------------------------------------------
        self.form = PaymentForm(book)
        dock = QDockWidget("Record a payment", self)
        dock.setObjectName("paymentDock")
        dock.setWidget(self.form)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        title = DockTitleBar("Record a payment")
        title.collapse_requested.connect(self.collapse_dock)
        dock.setTitleBarWidget(title)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.payment_dock = dock

        self.strip_bar = QToolBar("Strip", self)
        self.strip_bar.setObjectName("controlsStripBar")
        self.strip_bar.setMovable(False)
        self.strip_bar.setFloatable(False)
        self.strip_bar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.strip_bar.toggleViewAction().setVisible(False)
        strip = CollapsedStrip("RECORD A PAYMENT")
        strip.clicked.connect(self.expand_dock)
        self.strip_bar.addWidget(strip)
        self.addToolBar(Qt.LeftToolBarArea, self.strip_bar)
        self.strip_bar.hide()

        # -- centre ---------------------------------------------------------
        self.dashboard_panel = DashboardPanel(book)
        self.ledger_panel = LedgerPanel(book)
        self.invoices_panel = InvoicesPanel(book)
        self.deadlines_panel = DeadlinesPanel(book)
        self.annual_panel = AnnualPanel(book)
        self.backup_panel = BackupPanel(book, self.tokens)
        self.settings_panel = SettingsPanel(book)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard_panel, "Limits")
        self.tabs.addTab(self.ledger_panel, "Payments")
        self.tabs.addTab(self.invoices_panel, "Invoices")
        self.tabs.addTab(self.deadlines_panel, "Deadlines")
        self.tabs.addTab(self.annual_panel, "Annual")
        self.tabs.addTab(self.backup_panel, "Backup")
        self.tabs.addTab(self.settings_panel, "Settings")

        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(0, 0, 0, 0)
        central_lay.setSpacing(0)
        self.integrity_banner = Banner("bad")
        central_lay.addWidget(self.integrity_banner)
        central_lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # -- status bar -----------------------------------------------------
        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, 1)
        self.backup_label = QLabel("")
        self.statusBar().addPermanentWidget(self.backup_label)

        self._wire()
        self._build_shortcuts()
        self._build_header()
        self._apply_icon()
        self._build_tray()
        self._start_timers()
        self.reload_all()
        self._first_run()

    # -- geometry -----------------------------------------------------------
    def _size_to_primary_screen(self) -> None:
        """Fit the restored window to the primary monitor, centred on it."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        area = screen.availableGeometry()
        self.resize(QSize(int(area.width() * 0.92), int(area.height() * 0.92)))
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

    # -- dock ---------------------------------------------------------------
    def collapse_dock(self) -> None:
        self.payment_dock.hide()
        self.strip_bar.show()
        self._remember_dock(True)

    def expand_dock(self) -> None:
        self.strip_bar.hide()
        self.payment_dock.show()
        self._remember_dock(False)
        if getattr(self, "_dock_fitted", False):
            self.resizeDocks([self.payment_dock], [self._dock_width], Qt.Horizontal)

    def toggle_dock(self) -> None:
        if self.payment_dock.isVisible():
            self.collapse_dock()
        else:
            self.expand_dock()

    def _remember_dock(self, collapsed: bool) -> None:
        profile = self.book.profile()
        if profile.dock_collapsed != collapsed:
            profile.dock_collapsed = collapsed
            self.book.save_profile(profile)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """Size the dock once the real font metrics are known."""
        super().showEvent(event)
        if not getattr(self, "_dock_fitted", False):
            self._dock_fitted = True
            panel = self.form
            needed = panel.widget().minimumSizeHint().width() if panel.widget() else 0
            width = max(needed + panel.verticalScrollBar().sizeHint().width() + 6, 300)
            self.payment_dock.setMinimumWidth(width)
            self.payment_dock.setMaximumWidth(max(width * 2, 560))
            self._dock_width = width
            self.resizeDocks([self.payment_dock], [width], Qt.Horizontal)
            if self.book.profile().dock_collapsed:
                self.collapse_dock()

    # -- branding -----------------------------------------------------------
    def _build_header(self) -> None:
        """The logo strip. A top toolbar spans the full width above the dock area, which is
        what puts the mark in the true top-left corner."""
        bar = QToolBar("Branding", self)
        bar.setObjectName("brandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(1, 1))

        logo = QLabel()
        logo.setObjectName("brandLogo")
        pix = QPixmap(str(LOGO_DISPLAY_DARK)) if LOGO_DISPLAY_DARK.exists() else QPixmap()
        if not pix.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            pix.setDevicePixelRatio(ratio)
            logo.setPixmap(pix.scaledToHeight(int(BRAND_LOGO_HEIGHT * ratio), Qt.SmoothTransformation))
        else:
            logo.setText("MicroCompta")
            logo.setObjectName("h1")
        logo.setContentsMargins(10, 4, 12, 4)
        logo.setToolTip("MicroCompta: personal accounting for a French micro-entrepreneur")
        bar.addWidget(logo)

        spacer = QWidget()
        spacer.setObjectName("brandSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        help_button = QPushButton("Help")
        help_button.setObjectName("brandHelp")
        help_button.setToolTip("How this works  (F1)")
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self._show_help)
        bar.addWidget(help_button)

        bar.toggleViewAction().setVisible(False)
        bar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.brand_bar = bar

    def createPopupMenu(self) -> QMenu | None:  # noqa: N802
        return None

    def _apply_icon(self) -> None:
        path = APP_ICO if APP_ICO.exists() else LOGO_ICON
        if path.exists():
            self.setWindowIcon(QIcon(str(path)))

    # -- tray ---------------------------------------------------------------
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = TrayController(self.windowIcon(), self)
        self.tray.show_requested.connect(self.show_from_tray)
        self.tray.upload_requested.connect(self.upload_now)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.show()

    def show_from_tray(self) -> None:
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    # -- wiring -------------------------------------------------------------
    def _wire(self) -> None:
        self.form.recorded.connect(lambda _seq: self.on_records_changed())
        self.form.status.connect(self.set_status)
        for panel in (self.ledger_panel, self.invoices_panel, self.deadlines_panel,
                      self.settings_panel, self.backup_panel):
            panel.status.connect(self.set_status)
        for panel in (self.ledger_panel, self.invoices_panel, self.deadlines_panel,
                      self.settings_panel):
            panel.changed.connect(self.on_records_changed)
        self.backup_panel.upload_requested.connect(self.upload_now)
        self.backup_panel.snapshot_requested.connect(lambda: self.run_snapshot(announce=True))
        self.backup_panel.sign_in_requested.connect(self.start_sign_in)
        self.backup_panel.sign_out_requested.connect(self.sign_out)
        self.tabs.currentChanged.connect(lambda _i: self.reload_current())

    def _build_shortcuts(self) -> None:
        for text, key, slot in (
            ("Show or hide the payment form", "Ctrl+B", self.toggle_dock),
            ("Help", "F1", self._show_help),
            ("Upload now", "Ctrl+U", self.upload_now),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(slot)
            self.addAction(action)

    def _start_timers(self) -> None:
        """All periodic work runs from here, on the UI thread, in small steps."""
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(QUEUE_TICK_MS)
        self.queue_timer.timeout.connect(self.tick_queue)
        self.queue_timer.start()

        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(REMINDER_TICK_MS)
        self.reminder_timer.timeout.connect(self.tick_reminders)
        self.reminder_timer.start()

        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(SNAPSHOT_TICK_MS)
        self.snapshot_timer.timeout.connect(self.run_snapshot)
        self.snapshot_timer.start()

        # A burst of edits ends in one snapshot, a few minutes after the last.
        self.snapshot_debounce = QTimer(self)
        self.snapshot_debounce.setSingleShot(True)
        self.snapshot_debounce.setInterval(SNAPSHOT_AFTER_CHANGE_MS)
        self.snapshot_debounce.timeout.connect(self.run_snapshot)

        self.integrity_timer = QTimer(self)
        self.integrity_timer.setInterval(INTEGRITY_TICK_MS)
        self.integrity_timer.timeout.connect(self.check_integrity)
        self.integrity_timer.start()

        QTimer.singleShot(1500, self.check_integrity)
        QTimer.singleShot(3000, self.tick_reminders)
        QTimer.singleShot(5000, self.tick_queue)

    def _first_run(self) -> None:
        profile = self.book.profile()
        if not profile.is_set_up:
            self.tabs.setCurrentWidget(self.settings_panel)
            self.set_status("Welcome. Enter your details to begin.")
        elif not self.book.clients.list():
            self.tabs.setCurrentWidget(self.settings_panel)
            self.settings_panel.tabs.setCurrentIndex(1)
            self.set_status("Add your client to start recording payments.")

    # -- refresh ------------------------------------------------------------
    def reload_all(self) -> None:
        if self._closed:
            return
        self.form.reload()
        for panel in (self.dashboard_panel, self.ledger_panel, self.invoices_panel,
                      self.deadlines_panel, self.annual_panel, self.backup_panel,
                      self.settings_panel):
            panel.reload()
        self._refresh_labels()

    def reload_current(self) -> None:
        if self._closed:
            return
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "reload"):
            widget.reload()

    def on_records_changed(self) -> None:
        self.reload_all()
        self.snapshot_debounce.start()
        self.tick_queue()

    def _refresh_labels(self) -> None:
        overdue, soon = self.deadlines_panel.counts()
        label = "Deadlines"
        if overdue:
            label += f"  ({overdue} overdue)"
        elif soon:
            label += f"  ({soon} soon)"
        self.tabs.setTabText(self.tabs.indexOf(self.deadlines_panel), label)

        stale = len(self.book.invoices.stale())
        self.tabs.setTabText(
            self.tabs.indexOf(self.invoices_panel),
            f"Invoices  ({stale} to correct)" if stale else "Invoices",
        )

        counts = self.book.queue.counts()
        state = self.tokens.state()
        waiting = counts["pending"] + counts["failed"]
        if state == "connected":
            text = f"Drive: {waiting} waiting" if waiting else "Drive: all uploaded"
        else:
            text = f"Drive: not connected, {waiting} waiting" if waiting else "Drive: not connected"
        if counts["failed"]:
            text += f", {counts['failed']} failed"
        self.backup_label.setText(text)
        tab = "Backup"
        if counts["failed"]:
            tab += f"  ({counts['failed']} failed)"
        self.tabs.setTabText(self.tabs.indexOf(self.backup_panel), tab)
        if self.tray is not None:
            self.tray.set_status(f"{overdue} overdue, {soon} soon. {text}.")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # -- reminders ----------------------------------------------------------
    def tick_reminders(self) -> None:
        """Hourly, and shortly after launch so a late start catches up."""
        if self._closed:
            return
        today = clock.today()
        if today != self._last_day:
            self._last_day = today
            self.reload_all()
        from ..core.errors import MissingFigure

        try:
            pending = self.book.deadlines.pending_reminders(today)
        except MissingFigure as exc:
            self.set_status(str(exc))
            return
        if not pending:
            return
        for item in pending:
            self.book.deadlines.mark_reminded(item)
        lines = [item["_message"] for item in pending[:4]]
        if len(pending) > 4:
            lines.append(f"and {len(pending) - 4} more")
        self.notify("Deadlines", "\n".join(lines))
        self._refresh_labels()

    def notify(self, title: str, message: str) -> None:
        if self.tray is not None:
            self.tray.notify(f"MicroCompta: {title}", message)
        self.set_status(message.splitlines()[0])

    # -- uploads ------------------------------------------------------------
    def _upload_running(self) -> bool:
        return self._upload_worker is not None and self._upload_worker.isRunning()

    def tick_queue(self) -> None:
        if self._closed or self._upload_running() or self.tokens.state() != "connected":
            return
        if self.book.queue.has_due():
            self._start_upload()

    def upload_now(self) -> None:
        if self.tokens.state() != "connected":
            self.tabs.setCurrentWidget(self.backup_panel)
            self.set_status("Connect Google Drive first: the steps are on the Backup tab.")
            return
        self.book.queue.retry()
        self.tick_queue()

    def _start_upload(self) -> None:
        worker = UploadWorker(self.book.queue, self.client_factory, self)
        worker.finished_ok.connect(self._on_upload_done)
        worker.failed.connect(self._on_upload_failed)
        worker.finished.connect(self._after_upload)
        self._upload_worker = worker
        self.set_status("Uploading to Google Drive…")
        worker.start()

    def _on_upload_done(self, report: Any) -> None:
        if report.needs_sign_in:
            self.notify("Backup paused", report.stopped)
        elif report.failed:
            self.notify("Upload failed", f"{report.failed} document(s). See the Backup tab.")
        elif report.uploaded:
            self.set_status(f"{report.uploaded} document(s) uploaded and verified.")
        elif report.stopped:
            self.set_status(f"Backup waiting: {report.stopped}")

    def _on_upload_failed(self, message: str) -> None:
        self.set_status(f"Upload pass failed: {message}")

    def _after_upload(self) -> None:
        if self._closed:
            return
        if self._quitting:
            self.close()
            return
        self._refresh_labels()
        if self.tabs.currentWidget() is self.backup_panel:
            self.backup_panel.reload()

    def start_sign_in(self) -> None:
        if self._sign_in_worker is not None and self._sign_in_worker.isRunning():
            return
        worker = SignInWorker(self.tokens.client_file, self.tokens.token_file, self)
        worker.finished_ok.connect(self._on_signed_in)
        worker.failed.connect(self._on_sign_in_failed)
        worker.finished.connect(lambda: self.backup_panel.set_signing_in(False))
        self._sign_in_worker = worker
        self.backup_panel.set_signing_in(True)
        self.set_status("Waiting for you to sign in, in the browser…")
        worker.start()

    def _on_signed_in(self) -> None:
        self.set_status("Signed in to Google Drive. Uploading what was waiting.")
        self.book.queue.retry()
        self.tick_queue()
        self._refresh_labels()

    def _on_sign_in_failed(self, message: str) -> None:
        if not self._quitting:
            QMessageBox.warning(self, "Sign-in did not complete", message)
        self.set_status("Sign-in did not complete.")

    def sign_out(self) -> None:
        self.tokens.sign_out()
        self.backup_panel.reload()
        self._refresh_labels()
        self.set_status("Signed out. Uploads wait until you sign in again.")

    # -- snapshots and integrity -------------------------------------------
    def run_snapshot(self, announce: bool = False) -> list[int]:
        if self._closed:
            return []
        try:
            added = self.book.snapshots.run()
        except Exception as exc:  # noqa: BLE001 - a failed backup must be seen, not crash the app
            log.exception("Snapshot failed")
            self.set_status(f"Snapshot failed: {exc}")
            return []
        if added:
            self.set_status("Records backed up: database snapshot and CSV exports queued for Drive.")
            self._refresh_labels()
            self.backup_panel.reload()
            self.tick_queue()
        elif announce:
            self.set_status("Nothing has changed since the last snapshot.")
        return added

    def check_integrity(self) -> list[str]:
        if self._closed:
            return []
        problems = self.book.verify()
        if problems:
            log.error("Integrity problems: %s", problems)
            shown = "\n".join(problems[:5])
            more = f"\nand {len(problems) - 5} more" if len(problems) > 5 else ""
            self.integrity_banner.show_text(
                "The records don't match their checks. Don't delete anything; your Drive backup "
                f"holds earlier copies.\n{shown}{more}"
            )
        else:
            self.integrity_banner.show_text("")
        return problems

    # -- help ---------------------------------------------------------------
    def _show_help(self) -> None:
        questions = "".join(
            f"<li><b>{q['topic']}</b> ({q['who']}): {q['status']}.</li>" for q in OPEN_QUESTIONS
        )
        QMessageBox.information(
            self, "How this works",
            "<b>Payments</b>: one entry per payment received. Turnover counts on the date received. "
            "Entries can't be edited; a correction is a reversing entry with a reason.<br><br>"
            "<b>Invoices</b>: a monthly summary drafted from that month's payments. Drafts are "
            "fine without a SIREN, but a final invoice needs one. Numbers are unbroken and issued "
            "invoices can't change; a correction is a credit note.<br><br>"
            "<b>Backup</b>: every document is saved locally and queued for your Google Drive, "
            "and counts as uploaded only once Drive reports the same checksum.<br><br>"
            "<b>Reminders</b> reach the tray while the app runs, so keep it in the tray.<br><br>"
            f"<b>Still open:</b><ul>{questions}</ul>"
            "<i>MicroCompta reminds and adds up. It doesn't give tax advice, and it doesn't do "
            "e-reporting or file anything with URSSAF.</i>",
        )

    # -- closing ------------------------------------------------------------
    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        """Closing the window keeps the app in the tray, so reminders still fire.

        A real quit makes a final snapshot and gives the upload queue a bounded chance to
        finish, since this may be the last time the app runs for a while.
        """
        if not self._quitting and self.tray is not None and self.book.profile().keep_in_tray:
            event.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.notify("MicroCompta", "Still running here so reminders can fire. "
                                                "Quit from this icon's menu.")
            return

        self._quitting = True
        if self._upload_running():
            event.ignore()
            self.set_status("Finishing the upload before closing…")
            QTimer.singleShot(QUIT_FLUSH_LIMIT_MS, self._force_quit)
            return
        if not self._flush_tried:
            self._flush_tried = True
            self.run_snapshot()
            if self._upload_running():
                event.ignore()
                self.set_status("Uploading to Drive before closing…")
                QTimer.singleShot(QUIT_FLUSH_LIMIT_MS, self._force_quit)
                return
            if self.tokens.state() == "connected" and self.book.queue.has_due():
                event.ignore()
                self.set_status("Uploading to Drive before closing…")
                self._start_upload()
                QTimer.singleShot(QUIT_FLUSH_LIMIT_MS, self._force_quit)
                return
        self._finish_quit(event)

    def _force_quit(self) -> None:
        worker = self._upload_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(3000)
            if worker.isRunning():
                # Blocked in a network call. Records are committed and the queue resumes
                # next launch, so nothing is lost by leaving now.
                log.warning("Leaving with an upload still in flight.")
                self._finish_quit(None)
                os._exit(0)
        self._finish_quit(None)

    def _finish_quit(self, event: Any) -> None:
        if self._closed:
            return
        self._closed = True
        for timer_name in ("queue_timer", "reminder_timer", "snapshot_timer", "snapshot_debounce",
                           "integrity_timer"):
            getattr(self, timer_name).stop()
        for worker in (self._upload_worker, self._sign_in_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(2000)
        try:
            self.book.close()
        except Exception:  # noqa: BLE001 - already tearing down
            pass
        if self.tray is not None:
            self.tray.hide()
        if event is not None:
            event.accept()
        QApplication.quit()
