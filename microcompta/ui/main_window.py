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
from ..core.errors import MissingFigure
from ..core.ledger_policy import UNCONFIRMED
from ..core.open_questions import OPEN_QUESTIONS
from ..i18n import current_language, tr
from .language import apply_language
from .models import wrap_tip
from .panels.annual_panel import AnnualPanel
from .panels.backup_panel import BackupPanel
from .panels.common import Banner, bubble
from .panels.dashboard_panel import DashboardPanel
from .panels.deadlines_panel import DeadlinesPanel
from .panels.invoices_panel import InvoicesPanel
from .panels.ledger_panel import LedgerPanel
from .panels.payment_form import PaymentForm
from .panels.purchases_panel import PurchasesPanel
from .panels.settings_panel import SettingsDialog
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
        self.payment_dock: QDockWidget | None = None

        apply_language(book.profile().language)
        self.setWindowTitle("MicroCompta")
        self.setStyleSheet(STYLESHEET)
        self._size_to_primary_screen()
        self._apply_icon()

        self._build_ui()
        self._build_shortcuts()
        self._build_tray()
        self._start_timers()
        self.reload_all()
        self._first_run()

    # -- building -----------------------------------------------------------
    def _build_ui(self) -> None:
        """Everything that shows text. Built again when the language changes."""
        # Left dock. The same dock across rebuilds: only its contents change.
        if self.payment_dock is None:
            self.payment_dock = QDockWidget(self)
            self.payment_dock.setObjectName("paymentDock")
            self.payment_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
            self.addDockWidget(Qt.LeftDockWidgetArea, self.payment_dock)
        for stale in (self.payment_dock.widget(), self.payment_dock.titleBarWidget()):
            if stale is not None:
                stale.deleteLater()
        self.form = PaymentForm(self.book)
        self.payment_dock.setWindowTitle(tr("Record a payment"))
        self.payment_dock.setWidget(self.form)
        title = DockTitleBar(tr("Record a payment"), tr(
            "Enter each payment here as it arrives. It goes straight into the ledger."
        ))
        title.collapse_requested.connect(self.collapse_dock)
        self.payment_dock.setTitleBarWidget(title)

        self.strip_bar = QToolBar("Strip", self)
        self.strip_bar.setObjectName("controlsStripBar")
        self.strip_bar.setMovable(False)
        self.strip_bar.setFloatable(False)
        self.strip_bar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.strip_bar.toggleViewAction().setVisible(False)
        strip = CollapsedStrip(tr("RECORD A PAYMENT"))
        strip.clicked.connect(self.expand_dock)
        self.strip_bar.addWidget(strip)
        self.addToolBar(Qt.LeftToolBarArea, self.strip_bar)
        self.strip_bar.hide()

        # Centre
        self.dashboard_panel = DashboardPanel(self.book)
        self.ledger_panel = LedgerPanel(self.book)
        self.purchases_panel = PurchasesPanel(self.book)
        self.invoices_panel = InvoicesPanel(self.book)
        self.deadlines_panel = DeadlinesPanel(self.book)
        self.annual_panel = AnnualPanel(self.book)
        self.backup_panel = BackupPanel(self.book, self.tokens)

        self.tabs = QTabWidget()
        for panel, label, tip in (
            (self.dashboard_panel, tr("Limits"), tr("Your turnover against each legal limit, and what to set aside.")),
            (self.ledger_panel, tr("Payments"), tr("The livre des recettes: every payment received, with totals every 3 months.")),
            (self.purchases_panel, tr("Expenses"), tr(
                "The purchases register: what you buy for the activity. It changes neither turnover "
                "nor contributions."
            )),
            (self.invoices_panel, tr("Invoices"), tr("Drafts, issued invoices and credit notes.")),
            (self.deadlines_panel, tr("Deadlines"), tr("Declarations and other dates, worked out from your start date.")),
            (self.annual_panel, tr("Annual"), tr("The year's totals, the figure for your tax return, and a review checklist.")),
            (self.backup_panel, tr("Backup"), tr("Whether each document has reached your Google Drive.")),
        ):
            index = self.tabs.addTab(panel, label)
            self.tabs.setTabToolTip(index, wrap_tip(tip))

        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(0, 0, 0, 0)
        central_lay.setSpacing(0)
        self.integrity_banner = Banner("bad", tip=tr(
            "The app checks its records against their hash chain at launch and every 6 hours."
        ))
        central_lay.addWidget(self.integrity_banner)
        central_lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        # Settings, behind the gear
        self.settings_dialog = SettingsDialog(self.book, self)
        self.settings_panel = self.settings_dialog.panel

        # Status bar
        self.setStatusBar(QStatusBar())
        self.status_label = QLabel(tr("Ready"))
        bubble(self.status_label, tr("The result of the last action."))
        self.statusBar().addWidget(self.status_label, 1)
        self.backup_label = QLabel("")
        bubble(self.backup_label, tr("Whether your documents have reached Google Drive. See the Backup tab."))
        self.statusBar().addPermanentWidget(self.backup_label)

        self._build_header()
        self._wire()

    def _teardown_ui(self) -> None:
        self.settings_dialog.done(0)
        self.settings_dialog.deleteLater()
        for bar in (self.strip_bar, self.brand_bar):
            self.removeToolBar(bar)
            bar.deleteLater()
        # The central widget is replaced by _build_ui, not removed here.

    def rebuild_for_language(self) -> None:
        """Widgets keep the text they were built with, so build them again. Nothing else
        changes: the records, the timers and any upload in flight carry on."""
        if self._closed:
            return
        settings_tab = self.settings_panel.tabs.currentIndex() if self.settings_dialog.isVisible() else None
        current_tab = self.tabs.currentIndex()
        collapsed = not self.payment_dock.isVisible()
        # Pinned for the rebuild: while the central widget is replaced, the dock would grow to
        # its maximum width and stay there (measured).
        self.payment_dock.setFixedWidth(self._dock_width)
        apply_language(self.book.profile().language)
        self._teardown_ui()
        self._build_ui()
        self.tabs.setCurrentIndex(current_tab)
        if self.tray is not None:
            self.tray.retranslate()
        self.reload_all()
        # Once the layout settles: the text changed, so the width it needs may have.
        QTimer.singleShot(150, self._fit_dock)
        if collapsed:
            self.collapse_dock()
        if settings_tab is not None:
            self.open_settings(settings_tab)
        self.set_status(tr("Language changed."))

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
        if getattr(self, "_dock_width", None):
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

    def _fit_dock(self) -> None:
        """Width depends on the text, so it depends on the language."""
        if self._closed:
            return
        panel = self.form
        needed = panel.widget().minimumSizeHint().width() if panel.widget() else 0
        width = max(needed + panel.verticalScrollBar().sizeHint().width() + 6, 300)
        self.payment_dock.setMinimumWidth(width)
        self.payment_dock.setMaximumWidth(max(width * 2, 560))
        self._dock_width = width
        self.resizeDocks([self.payment_dock], [width], Qt.Horizontal)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """Size the dock once the real font metrics are known."""
        super().showEvent(event)
        if not getattr(self, "_dock_fitted", False):
            self._dock_fitted = True
            self._fit_dock()
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
        bubble(logo, tr("MicroCompta: personal accounting for a French micro-entrepreneur."), "MicroCompta")
        bar.addWidget(logo)

        spacer = QWidget()
        spacer.setObjectName("brandSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        gear = QPushButton()
        gear.setObjectName("brandGear")
        gear.setFixedSize(34, 29)
        gear.setCursor(Qt.PointingHandCursor)
        bubble(gear, tr("Settings: your identity, your clients, rates and limits, and the app's "
                        "language (Ctrl+,)."), tr("Settings"))
        gear.clicked.connect(lambda _c=False: self.open_settings())
        bar.addWidget(gear)
        self.settings_button = gear

        help_button = QPushButton(tr("Help"))
        help_button.setObjectName("brandHelp")
        bubble(help_button, tr("How this works, and what is still open (F1)."))
        help_button.setCursor(Qt.PointingHandCursor)
        help_button.clicked.connect(self._show_help)
        bar.addWidget(help_button)
        self.help_button = help_button

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

    # -- settings -----------------------------------------------------------
    def open_settings(self, tab: int = 0) -> None:
        if self._closed:
            return
        self.settings_panel.reload()
        self.settings_panel.tabs.setCurrentIndex(tab)
        hint = self.size()
        self.settings_dialog.resize(max(int(hint.width() * 0.86), 900), max(int(hint.height() * 0.88), 600))
        self.settings_dialog.open()

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
        for panel in (self.ledger_panel, self.purchases_panel, self.invoices_panel, self.deadlines_panel,
                      self.settings_panel, self.backup_panel):
            panel.status.connect(self.set_status)
        for panel in (self.ledger_panel, self.purchases_panel, self.invoices_panel, self.deadlines_panel,
                      self.settings_panel):
            panel.changed.connect(self.on_records_changed)
        # Not directly: this deletes the dialog whose button is still being pressed.
        self.settings_panel.language_changed.connect(
            lambda: QTimer.singleShot(0, self.rebuild_for_language)
        )
        self.backup_panel.upload_requested.connect(self.upload_now)
        self.backup_panel.snapshot_requested.connect(lambda: self.run_snapshot(announce=True))
        self.backup_panel.sign_in_requested.connect(self.start_sign_in)
        self.backup_panel.sign_out_requested.connect(self.sign_out)
        self.tabs.currentChanged.connect(lambda _i: self.reload_current())

    def _build_shortcuts(self) -> None:
        for key, slot in (
            ("Ctrl+B", self.toggle_dock),
            ("F1", self._show_help),
            ("Ctrl+U", self.upload_now),
            ("Ctrl+,", self.open_settings),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(lambda _c=False, run=slot: run())
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
            self.set_status(tr("Welcome. Enter your details to begin."))
            QTimer.singleShot(0, lambda: self.open_settings(0))
        elif not self.book.clients.list():
            self.set_status(tr("Add your client to start recording payments."))
            QTimer.singleShot(0, lambda: self.open_settings(1))

    # -- refresh ------------------------------------------------------------
    def reload_all(self) -> None:
        if self._closed:
            return
        self.form.reload()
        for panel in (self.dashboard_panel, self.ledger_panel, self.purchases_panel, self.invoices_panel,
                      self.deadlines_panel, self.annual_panel, self.backup_panel):
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
        label = tr("Deadlines")
        if overdue:
            label += "  " + tr("({count} overdue)", count=overdue)
        elif soon:
            label += "  " + tr("({count} soon)", count=soon)
        self.tabs.setTabText(self.tabs.indexOf(self.deadlines_panel), label)

        stale = len(self.book.invoices.stale())
        invoices = tr("Invoices")
        if stale:
            invoices += "  " + tr("({count} to correct)", count=stale)
        self.tabs.setTabText(self.tabs.indexOf(self.invoices_panel), invoices)

        counts = self.book.queue.counts()
        state = self.tokens.state()
        waiting = counts["pending"] + counts["failed"]
        if state == "connected":
            text = tr("Drive: {count} waiting", count=waiting) if waiting else tr("Drive: all uploaded")
        else:
            text = (tr("Drive: not connected, {count} waiting", count=waiting) if waiting
                    else tr("Drive: not connected"))
        if counts["failed"]:
            text += ", " + tr("{count} failed", count=counts["failed"])
        self.backup_label.setText(text)
        tab = tr("Backup")
        if counts["failed"]:
            tab += "  " + tr("({count} failed)", count=counts["failed"])
        self.tabs.setTabText(self.tabs.indexOf(self.backup_panel), tab)
        if self.tray is not None:
            self.tray.set_status(tr("{overdue} overdue, {soon} soon. {backup}.",
                                    overdue=overdue, soon=soon, backup=text))

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
            lines.append(tr("and {count} more", count=len(pending) - 4))
        self.notify(tr("Deadlines"), "\n".join(lines))
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
            self.set_status(tr("Connect Google Drive first: the steps are on the Backup tab."))
            return
        self.book.queue.retry()
        self.tick_queue()

    def _start_upload(self) -> None:
        worker = UploadWorker(self.book.queue, self.client_factory, self)
        worker.finished_ok.connect(self._on_upload_done)
        worker.failed.connect(self._on_upload_failed)
        worker.finished.connect(self._after_upload)
        self._upload_worker = worker
        self.set_status(tr("Uploading to Google Drive…"))
        worker.start()

    def _on_upload_done(self, report: Any) -> None:
        if report.needs_sign_in:
            self.notify(tr("Backup paused"), report.stopped)
        elif report.failed:
            self.notify(tr("Upload failed"), tr("{count} document(s). See the Backup tab.", count=report.failed))
        elif report.uploaded:
            self.set_status(tr("{count} document(s) uploaded and verified.", count=report.uploaded))
        elif report.stopped:
            self.set_status(tr("Backup waiting: {reason}", reason=report.stopped))

    def _on_upload_failed(self, message: str) -> None:
        self.set_status(tr("Upload pass failed: {reason}", reason=message))

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
        self.set_status(tr("Waiting for you to sign in, in the browser…"))
        worker.start()

    def _on_signed_in(self) -> None:
        self.set_status(tr("Signed in to Google Drive. Uploading what was waiting."))
        self.book.queue.retry()
        self.tick_queue()
        self._refresh_labels()

    def _on_sign_in_failed(self, message: str) -> None:
        if not self._quitting:
            QMessageBox.warning(self, tr("Sign-in did not complete"), message)
        self.set_status(tr("Sign-in did not complete."))

    def sign_out(self) -> None:
        self.tokens.sign_out()
        self.backup_panel.reload()
        self._refresh_labels()
        self.set_status(tr("Signed out. Uploads wait until you sign in again."))

    # -- snapshots and integrity -------------------------------------------
    def run_snapshot(self, announce: bool = False) -> list[int]:
        if self._closed:
            return []
        try:
            added = self.book.snapshots.run()
        except Exception as exc:  # noqa: BLE001 - a failed backup must be seen, not crash the app
            log.exception("Snapshot failed")
            self.set_status(tr("Snapshot failed: {reason}", reason=exc))
            return []
        if added:
            self.set_status(tr("Records backed up: database snapshot and CSV exports queued for Drive."))
            self._refresh_labels()
            self.backup_panel.reload()
            self.tick_queue()
        elif announce:
            self.set_status(tr("Nothing has changed since the last snapshot."))
        return added

    def check_integrity(self) -> list[str]:
        if self._closed:
            return []
        problems = self.book.verify()
        if problems:
            log.error("Integrity problems: %s", problems)
            shown = "\n".join(problems[:5])
            more = "\n" + tr("and {count} more", count=len(problems) - 5) if len(problems) > 5 else ""
            self.integrity_banner.show_text(tr(
                "The records don't match their checks. Don't delete anything; your Drive backup "
                "holds earlier copies.\n{problems}", problems=shown + more,
            ))
        else:
            self.integrity_banner.show_text("")
        return problems

    # -- help ---------------------------------------------------------------
    def _show_help(self) -> None:
        questions = "".join(
            f"<li><b>{tr(q['topic'])}</b> ({tr(q['who'])}): {tr(q['status'])}.</li>" for q in OPEN_QUESTIONS
        )
        QMessageBox.information(
            self, tr("How this works"),
            tr("<b>Payments</b>: one entry per payment received. Turnover counts on the date received. "
               "Entries can't be edited; a correction is a reversing entry with a reason.<br><br>"
               "<b>Expenses</b>: the purchases register, which the VAT franchise requires. Under the "
               "micro regime it changes nothing you pay: expenses aren't deducted, and nothing in it is "
               "declared.<br><br>"
               "<b>Invoices</b>: a monthly summary drafted from that month's payments. Drafts are "
               "fine without a SIREN, but a final invoice needs one. Numbers are unbroken and issued "
               "invoices can't change; a correction is a credit note.<br><br>"
               "<b>Backup</b>: every document is saved locally and queued for your Google Drive, "
               "and counts as uploaded only once Drive reports the same checksum.<br><br>"
               "<b>Reminders</b> reach the tray while the app runs, so keep it in the tray.<br><br>"
               "<b>Bubbles</b>: hold the mouse over any number, button or line to see what it means. "
               "Tab onto a number card for the same thing from the keyboard.<br><br>"
               "<b>Still open:</b><ul>{questions}</ul>"
               "<i>MicroCompta reminds and adds up. It doesn't give tax advice, and it doesn't do "
               "e-reporting or file anything with URSSAF.</i>", questions=questions),
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
                self.tray.notify("MicroCompta", tr(
                    "Still running here so reminders can fire. Quit from this icon's menu."
                ))
            return

        self._quitting = True
        if self._upload_running():
            event.ignore()
            self.set_status(tr("Finishing the upload before closing…"))
            QTimer.singleShot(QUIT_FLUSH_LIMIT_MS, self._force_quit)
            return
        if not self._flush_tried:
            self._flush_tried = True
            self.run_snapshot()
            if self._upload_running():
                event.ignore()
                self.set_status(tr("Uploading to Drive before closing…"))
                QTimer.singleShot(QUIT_FLUSH_LIMIT_MS, self._force_quit)
                return
            if self.tokens.state() == "connected" and self.book.queue.has_due():
                event.ignore()
                self.set_status(tr("Uploading to Drive before closing…"))
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
        self.settings_dialog.done(0)
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


__all__ = ["MainWindow", "UNCONFIRMED", "current_language"]
