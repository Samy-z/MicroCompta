"""The real window, offscreen, on fake data. Drives the panels the way a click would."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import QLocale, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QAbstractSpinBox, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QGroupBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QTableView, QTableWidget, QTabWidget, QToolTip, QWidget,
)

import demo_data  # noqa: E402
from conftest import FakeDrive  # noqa: E402
from microcompta import config, i18n  # noqa: E402
from microcompta.ui.main_window import MainWindow  # noqa: E402
from microcompta.ui.models import wrap_tip  # noqa: E402
from microcompta.ui.panels import common  # noqa: E402
from microcompta.ui.panels.clients_panel import ClientDialog  # noqa: E402
from microcompta.ui.panels.common import Chip, StatCard, bubble, from_qdate  # noqa: E402
from microcompta.ui.panels.invoices_panel import CreditDialog, EditDraftDialog, IssueDialog  # noqa: E402
from microcompta.ui.panels.ledger_panel import ReverseDialog  # noqa: E402
from microcompta.ui.panels.purchases_panel import PurchaseDialog, ReversePurchaseDialog  # noqa: E402
from microcompta.ui.panels.settings_panel import FigureDialog  # noqa: E402
from microcompta.ui.panels.stripe_dialog import StripeImportDialog  # noqa: E402
from microcompta.imports.stripe import StripeKeyError, StripePayment, StripeReading, save_key  # noqa: E402
from microcompta.ui.widgets.table_view import DataTable  # noqa: E402
from microcompta.ui.widgets.threshold_bar import ThresholdBar  # noqa: E402
from microcompta.ui import theme  # noqa: E402
from microcompta.ui.theme import STYLESHEET  # noqa: E402


class FakeTokens:
    def __init__(self, state: str = "connected", tmp: Path | None = None):
        self._state = state
        self.client_file = (tmp or Path(".")) / "client.json"
        self.token_file = (tmp or Path(".")) / "token.json"

    def state(self) -> str:
        return self._state

    def sign_out(self) -> None:
        self._state = "signed_out"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def warnings(monkeypatch) -> list[str]:
    """Refusals show a message box; collect them instead of blocking on one."""
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda _parent, _title, text: seen.append(text)))
    monkeypatch.setattr(common.QMessageBox, "warning",
                        staticmethod(lambda _parent, _title, text: seen.append(text)))
    return seen


def make_window(book: Any, qapp: Any, drive: Any = None, state: str = "connected",
                tmp: Path | None = None, language: str = "en") -> MainWindow:
    """English by default, so a test reads the source text. See the French tests below."""
    profile = book.profile()
    profile.language = language
    book.save_profile(profile)
    win = MainWindow(book, client_factory=(lambda: drive), tokens=FakeTokens(state, tmp))
    # The timers fire on the event loop; tests call the same methods directly.
    win.queue_timer.stop()
    win.reminder_timer.stop()
    win.snapshot_timer.stop()
    win.integrity_timer.stop()
    win.resize(1536, 824)
    win.show()
    qapp.processEvents()
    return win


def wait_for_upload(win: MainWindow, qapp: Any) -> None:
    for _ in range(300):
        qapp.processEvents()
        if not win._upload_running():
            qapp.processEvents()
            return
        QTest.qWait(10)
    raise AssertionError("The upload worker did not finish.")


@pytest.fixture
def demo(book, pinned_today):
    pinned_today(demo_data.FAKE_TODAY)
    return demo_data.populate(book)


# -- first launch ------------------------------------------------------------
def test_first_launch_on_an_empty_book_opens_settings(book, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.settings_dialog.isVisible()
    assert win.settings_panel.setup_banner.isVisibleTo(win.settings_dialog)
    assert not win.form.record_button.isEnabled()
    for index in range(win.tabs.count()):
        win.tabs.setCurrentIndex(index)
        qapp.processEvents()
    win._finish_quit(None)


def test_identity_is_never_prefilled(book, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.settings_panel.reload()
    assert win.settings_panel.legal_name.text() == ""
    assert win.settings_panel.siren.text() == ""
    assert win.settings_panel.address.toPlainText() == ""
    assert book.clients.list() == []
    win._finish_quit(None)


def test_settings_save_round_trip(book, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.settings_panel
    panel.reload()
    panel.legal_name.setText("Camille Exemple")
    panel.address.setPlainText("12 rue de l'Exemple")
    panel.siren.setText("123 456 782")
    panel.has_start.setChecked(True)
    panel.start_date.setDate(common.to_qdate(date(2026, 11, 2)))
    panel.acre.setChecked(True)
    panel.frequency.setCurrentIndex(panel.frequency.findData("quarterly"))
    panel.save_profile()
    profile = book.profile()
    assert profile.legal_name == "Camille Exemple"
    assert profile.siren == "123456782"
    assert profile.start_date == date(2026, 11, 2)
    assert profile.acre_enabled is True
    assert profile.declaration_frequency == "quarterly"
    assert not panel.setup_banner.isVisibleTo(win.settings_dialog)
    win._finish_quit(None)


# -- the panels on real records ----------------------------------------------
def test_every_panel_shows_the_records(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.ledger_panel.table.proxy.rowCount() == 19
    assert win.invoices_panel.table.proxy.rowCount() == 3
    assert win.deadlines_panel.table.proxy.rowCount() > 5
    assert win.dashboard_panel.cards["ceiling"].chip.text() == "OK"
    assert win.annual_panel.stats.cards["turnover"].value.text() == "€15,303.49"
    assert win.backup_panel.stats.cards["pending"].value.text() == "2"
    win._finish_quit(None)


def test_unconfirmed_labels_are_on_screen(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    label = "unconfirmed, URSSAF to answer"
    assert label in win.dashboard_panel.basis_chip.text()
    assert label in win.ledger_panel.policy_banner.label.text()
    assert label in win.form.unconfirmed.text()
    assert label in win.annual_panel.form_note.text()
    assert "probably; SIE to confirm" in win.dashboard_panel.cards["vat"].details.text()
    win._finish_quit(None)


def test_tables_open_in_a_useful_order(book, demo, qapp, tmp_path):
    """Found on screen: Qt sorts descending by default, which put the next deadline last."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    table = win.deadlines_panel.table
    due = [table.proxy.index(r, 0).data() for r in range(table.proxy.rowCount())]
    assert due[0] == "2026-11-30"
    newest = win.ledger_panel.table.model.rows[0]
    assert newest["received_on"] == date(2026, 10, 30)
    periods = win.dashboard_panel.periods
    assert periods.proxy.index(0, 0).data() == "Jul 2026"
    assert win.invoices_panel.table.model.rows[0]["status"] == "draft"
    win._finish_quit(None)


def test_no_false_overdue_on_a_clean_book(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert "overdue" not in win.tabs.tabText(win.tabs.indexOf(win.deadlines_panel))
    assert win.deadlines_panel.stats.cards["overdue"].value.text() == "0"
    win._finish_quit(None)


def test_new_year_with_no_records_still_renders(book, demo, qapp, tmp_path, pinned_today):
    pinned_today(date(2027, 1, 1))
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.dashboard_panel.year.currentData() == 2027
    assert win.dashboard_panel.stats.cards["ytd"].value.text() == "€0.00"
    win._finish_quit(None)


# -- recording ---------------------------------------------------------------
def fill_form(win: MainWindow, gross: str = "1000", rate: str = "1.25") -> None:
    form = win.form
    form.description.setText("Annotation work")
    form.gross.setText(gross)
    form.rate.setText(rate)
    form.fee.setText("30")
    form.net.setText("775")
    form.reference.setText("po_ui_1")


def test_recording_a_payment_updates_everything(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _summary: True)
    fill_form(win)
    assert win.form.eur_gross.text() == "€800.00"
    assert win.form.set_aside.text().startswith("€153.60")   # 19.2% with ACRE
    seq = win.form.record()
    assert seq is not None
    assert book.ledger.get(seq)["eur_gross"] == D("800.00")
    assert win.ledger_panel.table.proxy.rowCount() == 20
    assert win.form.gross.text() == ""
    assert "153.60" in win.status_label.text()
    win._finish_quit(None)


def test_declining_the_confirmation_records_nothing(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _summary: False)
    before = len(book.ledger.entries())
    fill_form(win)
    assert win.form.record() is None
    assert len(book.ledger.entries()) == before
    win._finish_quit(None)


def test_a_bad_payment_is_refused_with_a_message(book, demo, qapp, tmp_path, monkeypatch, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _summary: True)
    before = len(book.ledger.entries())
    fill_form(win, gross="abc")
    assert win.form.record() is None
    assert len(book.ledger.entries()) == before
    assert warnings and "not a number" in warnings[0]
    win._finish_quit(None)


def test_reversal_from_the_ledger_panel(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    first = int(demo["first_seq"])
    new = win.ledger_panel.reverse(first, "Wrong amount")
    assert new is not None
    assert win.ledger_panel.reverse(first, "Again") is None
    assert warnings and "already been reversed" in warnings[0]
    win._finish_quit(None)


def test_only_a_live_payment_can_be_reversed_from_the_screen(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.ledger_panel
    win.tabs.setCurrentWidget(panel)
    panel.table.select_first()    # the newest entry is a live payment
    assert panel.reverse_button.isEnabled()
    panel.table.select_key(19)    # the reversal in the demo data
    assert not panel.reverse_button.isEnabled()
    panel.table.select_key(18)    # the entry it reversed
    assert not panel.reverse_button.isEnabled()
    win._finish_quit(None)


def test_exports_from_the_ledger_panel_are_queued(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    before = book.queue.counts()["pending"]
    assert win.ledger_panel.export_csv(ask=False) is not None
    assert win.ledger_panel.export_pdf(ask=False) is not None
    assert book.queue.counts()["pending"] == before + 2
    assert "2026/exports" in win.status_label.text()
    win._finish_quit(None)


# -- invoices ----------------------------------------------------------------
def test_issuing_needs_a_siren_on_screen_too(book, qapp, tmp_path, pinned_today, warnings):
    pinned_today(demo_data.FAKE_TODAY)
    demo = demo_data.populate(book, with_siren=False)
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    assert panel.issue(demo["invoices"][9], demo_data.FAKE_TODAY, "1.08", demo_data.FAKE_TODAY) is None
    assert warnings and "SIREN" in warnings[0]
    assert book.invoices.register() == []
    win._finish_quit(None)


def test_issue_and_credit_note_from_the_panel(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    number = panel.issue(demo["invoices"][9], demo_data.FAKE_TODAY, "1.08", demo_data.FAKE_TODAY)
    assert number == "FA-2026-0003"
    assert number in win.status_label.text()
    panel.table.select_key(demo["invoices"][9])
    assert panel.credit_button.isEnabled()
    assert not panel.issue_button.isEnabled()
    assert not panel.edit_button.isEnabled()
    assert "Turnover uses the ledger" in panel.value_note.text()
    win._finish_quit(None)


def test_creating_a_draft_from_the_month_picker(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    period = panel.month.currentData()
    assert period == (2026, 10)
    invoice_id = panel.create_draft()
    assert invoice_id is not None
    assert panel.table.current_row()["id"] == invoice_id
    assert panel.month.currentData() is None
    assert not panel.draft_button.isEnabled()
    win._finish_quit(None)


def test_a_reversed_payment_on_an_invoice_raises_the_alert(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.invoices_panel.alert.isHidden()
    win.ledger_panel.reverse(int(demo["first_seq"]), "Refund")
    assert not win.invoices_panel.alert.isHidden()
    assert "FA-2026-0001" in win.invoices_panel.alert.label.text()
    # Visible from anywhere: the alert is on a tab that may not be open.
    assert "1 to correct" in win.tabs.tabText(win.tabs.indexOf(win.invoices_panel))
    win._finish_quit(None)


# -- backup through the real worker thread -----------------------------------
def test_uploads_run_on_a_worker_and_status_reaches_the_screen(book, demo, qapp, tmp_path):
    drive = FakeDrive()
    win = make_window(book, qapp, drive=drive, tmp=tmp_path)
    assert book.queue.counts()["pending"] == 2
    win.tick_queue()
    wait_for_upload(win, qapp)
    assert book.queue.counts() == {"pending": 0, "uploaded": 2, "failed": 0}
    assert "2 document(s) uploaded" in win.status_label.text()
    assert win.backup_label.text() == "Drive: all uploaded"
    win.tabs.setCurrentWidget(win.backup_panel)
    qapp.processEvents()
    assert win.backup_panel.stats.cards["uploaded"].value.text() == "2"
    assert win.backup_panel.table.model.rows[0]["status"] == "uploaded"
    win._finish_quit(None)


def test_offline_shows_as_waiting_and_recovers(book, demo, qapp, tmp_path, monkeypatch):
    from conftest import TransientDriveError
    from microcompta.core import clock

    drive = FakeDrive()
    drive.fail_next = [TransientDriveError("No connection to Google Drive.")]
    win = make_window(book, qapp, drive=drive, tmp=tmp_path)
    win.tick_queue()
    wait_for_upload(win, qapp)
    assert book.queue.counts()["pending"] == 2
    assert "No connection" in win.status_label.text()
    book.queue.retry()
    win.tick_queue()
    wait_for_upload(win, qapp)
    assert book.queue.counts()["uploaded"] == 2
    win._finish_quit(None)
    assert clock  # imported for symmetry with the core tests


def test_not_connected_means_no_upload_attempt_and_says_so(book, demo, qapp, tmp_path):
    drive = FakeDrive()
    win = make_window(book, qapp, drive=drive, state="signed_out", tmp=tmp_path)
    win.tick_queue()
    assert not win._upload_running()
    assert drive.calls == []
    assert "not connected" in win.backup_label.text()
    win.tabs.setCurrentWidget(win.backup_panel)
    win.backup_panel.reload()
    assert win.backup_panel.message.isVisibleTo(win)
    win._finish_quit(None)


def test_the_app_is_fully_usable_with_no_network_at_all(book, demo, qapp, tmp_path, monkeypatch):
    """Any socket would fail the test, not just a Drive call."""
    import socket

    def no_network(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("The app tried to use the network.")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    fill_form(win)
    assert win.form.record() is not None
    win.invoices_panel.issue(demo["invoices"][9], demo_data.FAKE_TODAY, "1.08", demo_data.FAKE_TODAY)
    win.ledger_panel.export_pdf(ask=False)
    assert win.run_snapshot() != []
    win.tick_queue()
    win.tick_reminders()
    assert win.check_integrity() == []
    win._finish_quit(None)


# -- timers and alerts -------------------------------------------------------
def test_timers_are_configured(book, qapp, tmp_path):
    win = MainWindow(book, client_factory=lambda: None, tokens=FakeTokens("no_client", tmp_path))
    assert win.queue_timer.isActive() and win.queue_timer.interval() == 60_000
    assert win.reminder_timer.isActive()
    assert win.snapshot_timer.isActive()
    assert win.integrity_timer.isActive()
    win._finish_quit(None)
    assert not win.queue_timer.isActive()


def test_reminders_fire_once_through_the_window(book, demo, qapp, tmp_path, pinned_today):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    pinned_today(date(2026, 11, 20))   # 10 days before the first declaration
    win.tick_reminders()
    first = win.status_label.text()
    assert "Turnover declaration" in first
    win.set_status("cleared")
    win.tick_reminders()
    assert win.status_label.text() == "cleared"
    win._finish_quit(None)


def test_a_changed_record_raises_the_integrity_banner(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.check_integrity() == []
    assert not win.integrity_banner.isVisibleTo(win)
    book.db.con.execute("UPDATE ledger SET eur_gross = 1.00 WHERE seq = 1")
    assert win.check_integrity() != []
    assert win.integrity_banner.isVisibleTo(win)
    win._finish_quit(None)


def test_recording_schedules_a_snapshot_rather_than_blocking(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    assert not win.snapshot_debounce.isActive()
    fill_form(win)
    win.form.record()
    assert win.snapshot_debounce.isActive()
    win.snapshot_debounce.stop()
    assert win.run_snapshot() != []
    win._finish_quit(None)


# -- leaving -----------------------------------------------------------------
def test_quit_takes_a_final_snapshot_and_tries_to_upload(book, demo, qapp, tmp_path):
    drive = FakeDrive()
    win = make_window(book, qapp, drive=drive, tmp=tmp_path)
    win.quit_app()
    for _ in range(300):
        qapp.processEvents()
        if not win.isVisible() or not win._upload_running() and drive.files:
            break
        QTest.qWait(10)
    wait_for_upload(win, qapp)
    QTest.qWait(30)
    qapp.processEvents()
    assert len(drive.files) == 6   # two invoices, the snapshot and three CSVs
    assert {f["name"].rsplit(".", 1)[-1] for f in drive.files.values()} == {"pdf", "zip", "csv"}


def test_quit_while_offline_does_not_hang(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.quit_app()
    qapp.processEvents()
    assert not win.isVisible()


def test_sign_out_only_forgets_the_local_token(book, demo, qapp, tmp_path):
    drive = FakeDrive()
    win = make_window(book, qapp, drive=drive, tmp=tmp_path)
    win.sign_out()
    assert win.tokens.state() == "signed_out"
    assert drive.calls == []
    win._finish_quit(None)


# -- every dialog, through its real code path ---------------------------------
@pytest.fixture
def answer_dialogs(monkeypatch):
    """Replace exec() with: fill in the dialog as a person would, then press OK."""
    answers: list[Any] = []

    def fake_exec(dialog: QDialog) -> int:
        answer = answers.pop(0)
        if answer is None:
            return QDialog.Rejected
        answer(dialog)
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    return answers


def test_issue_dialog_takes_the_rate_and_issues(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    panel.table.select_key(demo["invoices"][9])

    def fill(dialog: Any) -> None:
        dialog.rate.setText("1,0823")
        assert dialog.euro_value.text() == "€3,714.31"   # 4020 / 1.0823
        dialog.issue_date.setDate(common.to_qdate(demo_data.FAKE_TODAY))
        dialog.rate_date.setDate(common.to_qdate(demo_data.FAKE_TODAY))

    answer_dialogs.append(fill)
    panel.issue_selected()
    assert book.invoices.get(demo["invoices"][9])["number"] == "FA-2026-0003"
    win._finish_quit(None)


def test_cancelling_the_issue_dialog_takes_no_number(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.invoices_panel.table.select_key(demo["invoices"][9])
    answer_dialogs.append(None)
    win.invoices_panel.issue_selected()
    assert book.invoices.get(demo["invoices"][9])["status"] == "draft"
    assert len(book.invoices.register()) == 2
    win._finish_quit(None)


def test_edit_draft_dialog_saves_hours_and_a_rate(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    invoice_id = demo["invoices"][9]
    panel.table.select_key(invoice_id)

    def fill(dialog: Any) -> None:
        assert dialog.table.item(0, 1).text() == "1"
        dialog.table.item(0, 1).setText("16")
        dialog.table.item(0, 2).setText("60")
        dialog.notes.setText("Merci")
        dialog._save()

    answer_dialogs.append(fill)
    panel.edit_selected()
    first = book.invoices.lines(invoice_id)[0]
    assert first["total"] == D("960.00")
    assert book.invoices.get(invoice_id)["notes"] == "Merci"
    assert panel.table.current_row()["id"] == invoice_id
    win._finish_quit(None)


def test_credit_dialog_issues_a_credit_note(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    panel.table.select_key(demo["invoices"][8])

    def fill(dialog: Any) -> None:
        dialog.reason.setText("Wrong client")
        dialog.issue_date.setDate(common.to_qdate(demo_data.FAKE_TODAY))

    answer_dialogs.append(fill)
    panel.credit_selected()
    assert book.invoices.register()[-1]["number"] == "AV-2026-0003"
    win._finish_quit(None)


def test_preview_and_open_hand_a_pdf_to_the_system(book, demo, qapp, tmp_path, monkeypatch):
    from microcompta.ui.panels import invoices_panel as module

    opened: list[str] = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile())))
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    panel.table.select_key(demo["invoices"][9])
    panel.preview_selected()
    panel.table.select_key(demo["invoices"][7])
    panel.open_selected()
    assert len(opened) == 2
    assert all(Path(p).read_bytes().startswith(b"%PDF") for p in opened)
    assert opened[1].endswith("FA-2026-0001.pdf")
    win._finish_quit(None)


def test_delete_draft_from_the_panel(book, demo, qapp, tmp_path, monkeypatch):
    from microcompta.ui.panels import invoices_panel as module

    monkeypatch.setattr(module.QMessageBox, "question",
                        staticmethod(lambda *_a, **_k: QMessageBox.Yes))
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.invoices_panel
    panel.table.select_key(demo["invoices"][9])
    panel.delete_selected()
    assert book.invoices.get(demo["invoices"][9]) is None
    win._finish_quit(None)


def test_reverse_dialog_needs_and_records_a_reason(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.ledger_panel
    panel.table.select_key(int(demo["first_seq"]))

    def fill(dialog: Any) -> None:
        dialog.reason.setText("Wrong amount")

    answer_dialogs.append(fill)
    panel.reverse_selected()
    newest = max(book.ledger.entries(), key=lambda e: e["seq"])
    assert newest["kind"] == "reversal"
    assert newest["reason"] == "Wrong amount"
    win._finish_quit(None)


def test_client_dialog_adds_and_edits(book, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.clients_panel

    def add(dialog: Any) -> None:
        dialog.name.setText("Client Test")
        dialog.address.setPlainText("1 rue Test")
        dialog.currency.setCurrentText("EUR")
        dialog.taxed_in_france.setChecked(True)

    answer_dialogs.append(add)
    panel.add_client()
    client = book.clients.list()[0]
    assert client["name"] == "Client Test"
    assert client["taxed_in_france"] is True
    assert "Client Test" in win.status_label.text()
    assert win.form.client.count() == 1
    assert win.form.record_button.isEnabled()

    assert panel.table.model.rows[0]["name"] == "Client Test"
    panel.table.select_first()

    def edit(dialog: Any) -> None:
        assert dialog.name.text() == "Client Test"
        dialog.taxed_in_france.setChecked(False)

    answer_dialogs.append(edit)
    panel.edit_client()
    assert book.clients.list()[0]["taxed_in_france"] is False
    assert "probably; SIE to confirm" in panel.table.model.rows[0]["vat_flag"]
    win._finish_quit(None)


def test_figure_dialog_adds_a_later_value_and_the_old_one_stays(
        book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.settings_panel
    panel.reload()
    panel.figures_table.select_key("micro_ceiling|2026-01-01")

    def fill(dialog: Any) -> None:
        dialog.effective.setDate(common.to_qdate(date(2029, 1, 1)))
        dialog.value.setText("90000")
        dialog.source.setText("Test")

    answer_dialogs.append(fill)
    panel.edit_figure()
    assert book.figures.value("micro_ceiling", date(2028, 12, 31)) == D(83600)
    assert book.figures.value("micro_ceiling", date(2029, 1, 1)) == D(90000)
    assert any(r["row_key"] == "micro_ceiling|2029-01-01" for r in panel.figures_table.model.rows)
    win._finish_quit(None)


def test_set_date_dialog_for_form_2042(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.deadlines_panel
    panel.table.select_key("2042:2026")
    assert panel.date_button.isEnabled()

    def fill(dialog: Any) -> None:
        dialog.findChild(QDateEdit).setDate(common.to_qdate(date(2027, 5, 20)))

    answer_dialogs.append(fill)
    panel.set_date_selected()
    item = next(i for i in book.deadlines.items() if i["key"] == "2042:2026")
    assert item["due"] == date(2027, 5, 20)
    win._finish_quit(None)


def test_mark_done_from_the_panel(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.deadlines_panel
    panel.table.select_first()
    key = panel.table.current_row()["key"]
    panel.toggle_done()
    assert next(i for i in book.deadlines.items() if i["key"] == key)["done"] is True
    assert key not in [r["key"] for r in panel.table.model.rows]
    panel.show_done.setChecked(True)
    panel.table.select_key(key)
    assert panel.done_button.text() == "Mark not done"
    win._finish_quit(None)


def test_annual_checklist_is_remembered_per_year(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.annual_panel
    panel.checks["vl"].setChecked(True)
    panel.reload()
    assert panel.checks["vl"].isChecked()
    assert not panel.checks["regime"].isChecked()
    assert book.db.scalar("SELECT count(*) FROM annual_review WHERE year = 2026 AND done") == 1
    win._finish_quit(None)


def test_help_opens(book, qapp, tmp_path, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda _p, _t, text: shown.append(text)))
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win._show_help()
    assert "doesn't give tax advice" in shown[0]
    assert "unconfirmed, URSSAF to answer" in shown[0]
    win._finish_quit(None)


def test_recording_with_a_receipt_keeps_it_and_queues_it(
        book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    receipt = tmp_path / "payout.pdf"
    receipt.write_bytes(b"%PDF receipt")
    fill_form(win)
    win.form.set_receipt(str(receipt))
    seq = win.form.record()
    assert [d["kind"] for d in book.documents.for_ledger(seq)] == ["receipt"]
    assert win.form.receipt_label.text() == ""
    win._finish_quit(None)


def test_a_missing_figure_after_recording_does_not_look_like_a_failure(
        book, demo, qapp, tmp_path, monkeypatch):
    """The payment is committed by then. A crash here would invite a duplicate entry."""
    from microcompta.core.errors import MissingFigure

    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    fill_form(win)

    def missing(*_a: Any) -> Any:
        raise MissingFigure("rate_bnc", date(2020, 1, 1))

    monkeypatch.setattr(book.limits, "set_aside_for", missing)
    seq = win.form.record()
    assert seq is not None
    assert win.form.gross.text() == ""   # cleared, so it can't be recorded twice by accident
    win._finish_quit(None)


def test_sign_in_flow_through_the_real_worker(book, demo, qapp, tmp_path, monkeypatch):
    from microcompta.backup import oauth

    client_file = tmp_path / "client.json"
    client_file.write_text(
        '{"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "x"}}',
        encoding="utf-8",
    )

    def fake_sign_in(client: Any, token_file: Path, **_k: Any) -> None:
        assert client.client_id.startswith("abc")
        token_file.write_text("{}", encoding="utf-8")
        tokens._state = "connected"

    monkeypatch.setattr(oauth, "run_sign_in", fake_sign_in)
    drive = FakeDrive()
    win = make_window(book, qapp, drive=drive, state="signed_out", tmp=tmp_path)
    tokens = win.tokens
    win.backup_panel.reload()
    assert win.backup_panel.sign_in_button.isEnabled()
    win.start_sign_in()
    for _ in range(300):
        qapp.processEvents()
        if not win._sign_in_worker.isRunning() and tokens.state() == "connected":
            break
        QTest.qWait(10)
    qapp.processEvents()
    wait_for_upload(win, qapp)
    assert book.queue.counts()["uploaded"] == 2
    win._finish_quit(None)


def test_a_failed_sign_in_says_why(book, demo, qapp, tmp_path, monkeypatch, warnings):
    win = make_window(book, qapp, state="signed_out", tmp=tmp_path)
    win.start_sign_in()   # no client file at this path, so it fails straight away
    for _ in range(300):
        qapp.processEvents()
        if not win._sign_in_worker.isRunning():
            break
        QTest.qWait(10)
    qapp.processEvents()
    assert warnings
    assert win.backup_panel.sign_in_button.text() == "Sign in with Google"
    win._finish_quit(None)


def test_installing_the_client_file_from_the_backup_tab(book, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    bad = tmp_path / "web.json"
    bad.write_text('{"web": {"client_id": "x"}}', encoding="utf-8")
    assert win.backup_panel.install_client_file(str(bad)) is False
    assert warnings and "Desktop app" in warnings[0]
    good = tmp_path / "client_secret_fake.json"
    good.write_text('{"installed": {"client_id": "abc", "client_secret": "x"}}', encoding="utf-8")
    assert win.backup_panel.install_client_file(str(good)) is True
    assert config.oauth_client_path().exists()
    assert config.ROOT_DIR not in config.oauth_client_path().resolve().parents
    win._finish_quit(None)


# -- expenses: the purchases register ------------------------------------------
def fill_purchase(dialog: PurchaseDialog) -> None:
    dialog.supplier.setText("Logiciel Exemple")
    dialog.description.setText("Abonnement mensuel, novembre")
    dialog.category.setCurrentIndex(dialog.category.findData("Software and subscriptions"))
    dialog.amount.setText("21,60")
    dialog.method.setCurrentIndex(dialog.method.findData("Bank card"))
    dialog.reference.setText("EX-2026-11")


def test_expenses_is_a_tab_next_to_the_payments(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    assert win.tabs.tabText(win.tabs.indexOf(win.purchases_panel)) == "Dépenses"
    assert win.tabs.indexOf(win.purchases_panel) == win.tabs.indexOf(win.ledger_panel) + 1
    win._finish_quit(None)


def test_the_tab_opens_with_the_rule_a_beginner_needs(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.tabs.setCurrentWidget(win.purchases_panel)
    qapp.processEvents()
    text = win.purchases_panel.rule_banner.label.text()
    assert win.purchases_panel.rule_banner.isVisible()
    assert "ne se déduisent pas" in text
    assert "ne se déclare" in text
    win._finish_quit(None)


def test_a_purchase_is_recorded_from_the_dialog_and_reaches_the_table(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.purchases_panel
    before = len(book.purchases.entries())
    dialog = PurchaseDialog(book, panel)
    fill_purchase(dialog)
    dialog.share.setValue(50)
    dialog.accept()
    assert dialog.result() == QDialog.Accepted
    panel.recorded(dialog.seq)
    qapp.processEvents()
    row = book.purchases.get(dialog.seq)
    assert row["amount_eur"] == D("21.60")
    assert row["pro_share"] == D("0.5")
    assert row["payment_method"] == "Bank card"
    assert len(panel.table.model.rows) == before + 1
    assert panel.table.model.rows[0]["seq"] == dialog.seq      # newest first
    assert "recorded" in win.status_label.text()
    win._finish_quit(None)


def test_a_refused_purchase_keeps_the_dialog_open_with_what_was_typed(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    before = len(book.purchases.entries())
    dialog = PurchaseDialog(book, win.purchases_panel)
    fill_purchase(dialog)
    dialog.amount.setText("0")
    dialog.show()
    dialog.accept()
    assert dialog.isVisible()
    assert dialog.seq is None
    assert dialog.supplier.text() == "Logiciel Exemple"
    assert any("positive" in w for w in warnings)
    assert len(book.purchases.entries()) == before
    dialog.done(0)
    win._finish_quit(None)


def test_a_copy_is_for_this_months_bill(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    source = next(e for e in book.purchases.entries() if e["category"] == "Transport and travel")
    dialog = PurchaseDialog(book, win.purchases_panel, template=dict(source))
    assert dialog.supplier.text() == source["supplier"]
    assert dialog.amount.text() == "90.00"
    assert dialog.share.value() == 50
    assert dialog.method.currentData() == "Direct debit"
    assert from_qdate(dialog.paid_on.date()) == demo_data.FAKE_TODAY
    win._finish_quit(None)


def test_a_copy_doesnt_keep_the_old_document_number(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    source = next(e for e in book.purchases.entries() if e["piece_ref"])
    dialog = PurchaseDialog(book, win.purchases_panel, template=dict(source))
    assert dialog.reference.text() == ""                        # a new bill has a new number
    win._finish_quit(None)


def test_a_copy_shows_its_amount_the_french_way_and_can_be_saved(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    source = next(e for e in book.purchases.entries() if e["category"] == "Fixed asset")
    dialog = PurchaseDialog(book, win.purchases_panel, template=dict(source))
    assert dialog.amount.text().replace("\u00a0", " ").replace("\u202f", " ") == "1 200,00"
    dialog.accept()
    assert not warnings
    assert book.purchases.get(dialog.seq)["amount_eur"] == D("1200.00")
    win._finish_quit(None)


def test_recording_a_purchase_in_french_stores_the_keys(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    dialog = PurchaseDialog(book, win.purchases_panel)
    fill_purchase(dialog)
    assert dialog.method.currentText() == "Carte bancaire"
    assert dialog.category.currentText() == "Logiciels et abonnements"
    dialog.accept()
    row = book.purchases.get(dialog.seq)
    assert row["payment_method"] == "Bank card"
    assert row["category"] == "Software and subscriptions"
    win._finish_quit(None)


def test_buttons_follow_what_is_selected(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.purchases_panel
    win.tabs.setCurrentWidget(panel)
    panel.table.select_first()
    qapp.processEvents()
    assert panel.reverse_button.isEnabled()
    assert panel.copy_button.isEnabled()
    seq = int(panel.table.current_row()["seq"])
    new = panel.reverse(seq, "Erreur")
    qapp.processEvents()
    panel.table.select_key(new)
    qapp.processEvents()
    assert not panel.reverse_button.isEnabled()                 # a reversal can't be reversed
    assert not panel.copy_button.isEnabled()
    assert panel.attach_button.isEnabled()
    panel.table.select_key(seq)
    qapp.processEvents()
    assert not panel.reverse_button.isEnabled()                 # already reversed
    assert panel.copy_button.isEnabled()
    win._finish_quit(None)


def test_the_numbers_on_the_tab_add_up(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    cards = win.purchases_panel.stats.cards
    assert cards["paid"].value.text() == "€1,333.20"            # 21.60 x 2 + 90 + 1,200
    assert cards["pro"].value.text() == "€1,288.20"             # the pass counts for half
    assert cards["assets"].value.text() == "€1,200.00"
    comparison = book.regime_comparison(2026)
    assert comparison["purchases"]["charges"] == D("88.20")
    assert comparison["real_charges"] == D("88.20") + comparison["social"]
    assert "34%" in cards["allowance"].toolTip()
    assert "€500" in cards["assets"].toolTip()
    win._finish_quit(None)


def test_a_share_of_half_is_stored_as_a_half(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = PurchaseDialog(book, win.purchases_panel)
    fill_purchase(dialog)
    dialog.share.setValue(50)
    dialog.accept()
    assert not warnings
    assert book.purchases.get(dialog.seq)["pro_share"] == D("0.5")
    win._finish_quit(None)


def test_the_comparison_note_says_what_it_leaves_out(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    note = win.purchases_panel.note.text()
    assert "impôt sur le revenu" in note
    assert "expert-comptable" in note
    assert "versement libératoire" not in note
    profile = book.profile()
    profile.vl_enabled = True
    book.save_profile(profile)
    win.purchases_panel.reload()
    assert "versement libératoire" in win.purchases_panel.note.text()
    win._finish_quit(None)


def test_recording_a_purchase_changes_no_other_tab(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    ytd = win.dashboard_panel.stats.cards["ytd"].value.text()
    aside = win.dashboard_panel.stats.cards["set_aside"].value.text()
    dialog = PurchaseDialog(book, win.purchases_panel)
    fill_purchase(dialog)
    dialog.amount.setText("5000")
    dialog.accept()
    win.purchases_panel.recorded(dialog.seq)
    qapp.processEvents()
    assert win.dashboard_panel.stats.cards["ytd"].value.text() == ytd
    assert win.dashboard_panel.stats.cards["set_aside"].value.text() == aside
    win._finish_quit(None)


def test_attaching_a_document_shows_in_the_table_and_the_backup(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    source = tmp_path / "facture.pdf"
    source.write_bytes(b"facture")
    seq = book.purchases.entries()[0]["seq"]
    assert win.purchases_panel.attach(int(seq), str(source)) is not None
    qapp.processEvents()
    row = next(r for r in win.purchases_panel.table.model.rows if r["seq"] == seq)
    assert row["receipts"] == 1
    assert "Justificatif joint" in win.status_label.text()
    win._finish_quit(None)


def test_the_register_exports_from_the_tab(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    for export in (win.purchases_panel.export_csv, win.purchases_panel.export_pdf):
        doc = book.documents.get(export(ask=False))
        assert "registre_achats_2026" in doc["rel_path"]
        assert book.documents.path_of(doc).stat().st_size > 0
    win._finish_quit(None)


# -- clients: a tab of their own, and a button beside the form's list -----------
def _new_client(name: str = "Nouveau Client", currency: str = "USD", active: bool = True) -> Any:
    def fill(dialog: Any) -> None:
        dialog.name.setText(name)
        dialog.currency.setCurrentText(currency)
        dialog.active.setChecked(active)
    return fill


def _client_named(book: Any, name: str) -> dict[str, Any]:
    return next(c for c in book.clients.list() if c["name"] == name)


@pytest.mark.parametrize("language, before, after", [("fr", "Dépenses", "Factures"), ("en", "Expenses", "Invoices")])
def test_clients_is_a_tab_between_expenses_and_invoices(book, demo, qapp, tmp_path, language, before, after):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language=language)
    index = win.tabs.indexOf(win.clients_panel)
    assert win.tabs.tabText(index - 1) == before
    assert win.tabs.tabText(index) == "Clients"
    assert win.tabs.tabText(index + 1) == after
    assert win.tabs.tabToolTip(index)
    assert [row["name"] for row in win.clients_panel.table.model.rows] == [c["name"] for c in book.clients.list()]
    win._finish_quit(None)


def test_settings_no_longer_holds_the_clients(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    tabs = win.settings_panel.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Identity and activity", "Figures"]
    win.open_settings(1)
    qapp.processEvents()
    assert win.settings_panel.figures_table.isVisible()
    assert "clients" not in win.settings_button.toolTip().lower()
    win._finish_quit(None)


def test_a_set_up_profile_with_no_client_lands_on_the_clients_tab(book, qapp, tmp_path):
    profile = book.profile()
    profile.legal_name, profile.address, profile.start_date = "Camille Exemple", "12 rue de l'Exemple", date(2026, 11, 2)
    book.save_profile(profile)
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.tabs.currentWidget() is win.clients_panel
    assert not win.settings_dialog.isVisible()
    win._finish_quit(None)


def test_the_plus_button_sits_right_beside_the_client_list(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    combo, button = win.form.client, win.form.add_client_button
    assert button.text() == "+"
    assert button.accessibleName() == "Add client…"
    assert button.toolTip() and button.toolTip() != combo.toolTip()
    assert combo.accessibleName() == "Client"     # the list keeps its own name and bubble
    assert "+" in combo.toolTip()
    assert 0 < button.geometry().left() - combo.geometry().right() <= 8
    assert button.geometry().top() == combo.geometry().top()
    assert button.height() == combo.height()
    win._finish_quit(None)


def test_the_plus_button_adds_to_the_same_clients_and_selects_the_new_one(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    count = len(book.clients.list())
    win.form.description.setText("Annotation")
    win.form.gross.setText("100")
    seen: list[Any] = []

    def fill(dialog: Any) -> None:
        seen.append(type(dialog))
        _new_client()(dialog)

    answer_dialogs.append(fill)
    win.form.add_client_button.click()

    assert seen == [ClientDialog]                # the same window as the tab's
    assert len(book.clients.list()) == count + 1
    new = _client_named(book, "Nouveau Client")
    assert win.form.client.currentData() == new["id"]
    assert win.form.description.text() == "Annotation"   # the payment under way is still there
    assert win.form.gross.text() == "100"
    assert new["id"] in [row["id"] for row in win.clients_panel.table.model.rows]
    assert "Nouveau Client" in win.status_label.text()
    assert win.snapshot_debounce.isActive()      # a change like any other, so it gets backed up
    win._finish_quit(None)


def test_a_payment_can_be_recorded_for_the_client_just_added(book, demo, qapp, tmp_path, answer_dialogs, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    answer_dialogs.append(_new_client())
    win.form.add_client()
    fill_form(win)
    seq = win.form.record()
    assert book.ledger.get(seq)["client_id"] == _client_named(book, "Nouveau Client")["id"]
    assert book.verify() == []
    win._finish_quit(None)


def test_the_first_client_unlocks_recording_from_the_form(book, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert not win.form.record_button.isEnabled()
    assert "+" in win.form.record_button.toolTip()
    answer_dialogs.append(_new_client(currency="EUR"))
    win.form.add_client()
    assert win.form.client.currentText() == "Nouveau Client"
    assert win.form.record_button.isEnabled()
    assert win.form.rate.text() == "1"           # a euro client needs no rate
    win._finish_quit(None)


def test_a_client_added_on_the_tab_doesnt_change_the_selection(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    selected = win.form.client.currentData()
    answer_dialogs.append(_new_client("AAA Premier"))
    win.clients_panel.add_client()
    assert win.form.client.findText("AAA Premier") >= 0
    assert win.form.client.currentData() == selected
    win._finish_quit(None)


def test_cancelling_the_plus_button_changes_nothing(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    count, selected = len(book.clients.list()), win.form.client.currentData()
    answer_dialogs.append(None)
    win.form.add_client()
    assert len(book.clients.list()) == count
    assert win.form.client.currentData() == selected
    assert not win.snapshot_debounce.isActive()
    win._finish_quit(None)


def test_a_client_refused_from_the_form_says_why_and_changes_nothing(book, demo, qapp, tmp_path, answer_dialogs, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    count, selected = len(book.clients.list()), win.form.client.currentData()
    answer_dialogs.append(_new_client(name="   "))
    win.form.add_client()
    assert warnings == ["A client needs a name."]
    assert len(book.clients.list()) == count
    assert win.form.client.currentData() == selected
    win._finish_quit(None)


def test_an_inactive_new_client_is_saved_but_not_offered(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    answer_dialogs.append(_new_client("ZZZ Dernier"))    # not the first row, which a reload falls back to
    win.form.add_client()
    selected = win.form.client.currentData()
    answer_dialogs.append(_new_client(active=False))
    win.form.add_client()
    new = _client_named(book, "Nouveau Client")
    assert win.form.client.findData(new["id"]) == -1
    assert win.form.client.currentData() == selected
    assert new["id"] in [row["id"] for row in win.clients_panel.table.model.rows]
    win._finish_quit(None)


def test_a_long_client_name_doesnt_stretch_the_form(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    QTest.qWait(30)
    width = win.payment_dock.width()
    long_name = "Société Internationale de Formation Professionnelle et de Conseil SARL"
    answer_dialogs.append(_new_client(long_name))
    win.form.add_client()
    QTest.qWait(30)
    assert win.payment_dock.width() == width
    # Found on screen: the width only grew once the form was built again, as at the next launch.
    win.rebuild_for_language()
    QTest.qWait(200)
    qapp.processEvents()
    assert win.payment_dock.width() == width
    assert not win.form.horizontalScrollBar().isVisible()
    combo = win.form.client
    assert combo.sizeHint().width() < combo.fontMetrics().horizontalAdvance(long_name)
    view = win.form.client.view()
    assert view.minimumWidth() >= view.sizeHintForColumn(0)    # the name can still be read in the list
    win._finish_quit(None)


def test_the_plus_button_still_works_after_a_language_switch(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.open_settings(0)
    panel = win.settings_panel
    panel.language.setCurrentIndex(panel.language.findData("en"))
    panel.save_profile()
    QTest.qWait(30)
    qapp.processEvents()
    win.settings_dialog.done(0)
    answer_dialogs.append(_new_client())
    win.form.add_client_button.click()
    new = _client_named(book, "Nouveau Client")
    assert new["id"] in [row["id"] for row in win.clients_panel.table.model.rows]
    win._finish_quit(None)


# -- importing from Stripe ------------------------------------------------------
FAKE_STRIPE_KEY = "rk_test_FAKEKEY0123456789abcdef"
STRIPE_PAYMENT = StripePayment(
    id="ch_fake_1", paid_on=date(2026, 10, 31), amount=D("1020"), currency="USD", fee=D("27.61"),
    fee_currency="EUR", net=D("914.83"), net_currency="EUR", provider_rate=D("1.082284"),
    description="Annotation work, week 44", customer_name="Acme Annotation LLC", customer_email="",
)


class FakeStripe:
    def __init__(self, reading: StripeReading | None = None, error: Exception | None = None):
        self.reading = reading or StripeReading([STRIPE_PAYMENT])
        self.error = error
        self.reads = 0

    def read(self, _since: date) -> StripeReading:
        self.reads += 1
        if self.error:
            raise self.error
        return self.reading


def _stripe_dialog(win: Any, book: Any, tmp_path: Path, *, key: bool = True, **fake: Any) -> StripeImportDialog:
    path = tmp_path / "stripe_key.txt"
    if key:
        save_key(path, FAKE_STRIPE_KEY)
    source = FakeStripe(**fake)
    return StripeImportDialog(book, path, win.fill_from_stripe, win, source_factory=lambda _key: source,
                              threaded=False)


def test_payments_has_an_import_from_stripe_button(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    assert win.ledger_panel.stripe_button.text() == "Importer depuis Stripe…"
    assert win.ledger_panel.stripe_button.toolTip()
    win._finish_quit(None)


def test_without_a_key_the_window_asks_for_one(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path, key=False)
    assert not dialog.key_row.isHidden() and dialog.saved_row.isHidden()
    assert not dialog.refresh_button.isEnabled()
    assert dialog.table.model.rows == []
    win._finish_quit(None)


def test_a_secret_key_is_refused_and_not_saved(book, demo, qapp, tmp_path, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path, key=False)
    dialog.key_field.setText("sk_" + "live_FAKEKEY0123456789abcdef")    # in two parts for secret scanners
    assert dialog.save_key() is False
    assert "secret key" in warnings[0]
    assert not (tmp_path / "stripe_key.txt").exists()
    assert dialog.key_field.text() == ""          # not left on screen either
    win._finish_quit(None)


def test_a_restricted_key_is_saved_and_the_payments_read(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path, key=False)
    dialog.key_field.setText(FAKE_STRIPE_KEY)
    assert dialog.save_key() is True
    assert dialog.key_row.isHidden() and not dialog.saved_row.isHidden()
    assert FAKE_STRIPE_KEY not in dialog.key_label.text() and FAKE_STRIPE_KEY[-4:] in dialog.key_label.text()
    assert [r["id"] for r in dialog.table.model.rows] == ["ch_fake_1"]
    assert dialog.table.model.rows[0]["client"] == "Acme Annotation LLC"
    assert dialog.summary.text() == "1 payment to record."
    win._finish_quit(None)


def test_choosing_a_payment_fills_the_form_and_leaves_the_ecb_rate_to_you(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path)
    dialog.fill_selected()
    form = win.form
    assert from_qdate(form.date.date()) == date(2026, 10, 31)
    assert form.client.currentText() == "Acme Annotation LLC"
    assert form.description.text() == "Annotation work, week 44"
    assert form.method.currentData() == "Stripe"
    assert form.reference.text() == "ch_fake_1"
    assert (form.gross.text(), form.fee.text(), form.net.text()) == ("1,020.00", "27.61", "914.83")
    assert (form.fee_currency.currentText(), form.net_currency.currentText()) == ("EUR", "EUR")
    assert form.rate.text() == "" and form.rate_source.currentData() == "ECB reference"
    assert "ECB rate" in win.status_label.text()
    assert dialog.result() == QDialog.Accepted
    win._finish_quit(None)


def test_under_the_provider_setting_the_stripe_rate_is_used(book, demo, qapp, tmp_path):
    profile = book.profile()
    profile.fx_policy = "provider_effective"
    book.save_profile(profile)
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    _stripe_dialog(win, book, tmp_path).fill_selected()
    assert win.form.rate.text() == "1.082284"
    assert win.form.rate_source.currentData() == "Provider rate"
    assert "Check it" in win.status_label.text()
    win._finish_quit(None)


def test_a_recorded_payment_is_no_longer_offered(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    _stripe_dialog(win, book, tmp_path).fill_selected()
    win.form.rate.setText("1.0823")
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    seq = win.form.record()
    assert book.ledger.get(seq)["provider_ref"] == "ch_fake_1"
    assert book.ledger.get(seq)["fee_currency"] == "EUR"
    again = _stripe_dialog(win, book, tmp_path)
    assert again.table.model.rows == []
    assert again.summary.text() == "0 payments to record."
    win._finish_quit(None)


def test_an_ignored_payment_is_no_longer_offered(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path)
    dialog.dismiss_selected()
    assert dialog.table.model.rows == []
    assert _stripe_dialog(win, book, tmp_path).table.model.rows == []
    assert book.ledger.entries() and all(e["provider_ref"] != "ch_fake_1" for e in book.ledger.entries())
    win._finish_quit(None)


def test_refunds_are_pointed_out(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path, reading=StripeReading([STRIPE_PAYMENT], refunds=2))
    assert "2 refund(s)" in dialog.summary.text()
    win._finish_quit(None)


def test_a_stripe_error_shows_in_the_window(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path, error=StripeKeyError("Stripe refused the key: Invalid API Key"))
    assert not dialog.problem.isHidden()
    assert "Invalid API Key" in dialog.problem.label.text()
    assert dialog.table.model.rows == [] and dialog.refresh_button.isEnabled()
    win._finish_quit(None)


def test_a_folded_payment_form_opens_to_show_the_payment(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.collapse_dock()
    _stripe_dialog(win, book, tmp_path).fill_selected()
    assert win.payment_dock.isVisible()
    win._finish_quit(None)


def test_forgetting_the_key(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    dialog = _stripe_dialog(win, book, tmp_path)
    dialog.forget()
    assert not (tmp_path / "stripe_key.txt").exists()
    assert not dialog.key_row.isHidden() and dialog.table.model.rows == []
    win._finish_quit(None)


# -- the rate follows the client's currency ------------------------------------
def _usd_and_eur_clients(book: Any, form: Any) -> tuple[int, int]:
    """Two clients, whatever the demo holds, and the form's list refreshed."""
    usd = book.clients.add(name="Client Dollar", currency="USD")
    eur = book.clients.add(name="Client Euro", currency="EUR")
    form.reload()
    return usd, eur


def _select(form: Any, client_id: int) -> None:
    form.client.setCurrentIndex(form.client.findData(client_id))


def test_leaving_a_euro_client_doesnt_keep_the_rate_of_1(book, demo, qapp, tmp_path):
    """Found on screen: 100 USD read as 100 EUR, ready to be recorded."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    usd, eur = _usd_and_eur_clients(book, form)
    _select(form, eur)
    assert (form.rate.text(), form.rate.isEnabled()) == ("1", False)
    form.gross.setText("100")
    assert form.eur_gross.text() == "€100.00"

    _select(form, usd)
    assert (form.rate.text(), form.rate.isEnabled()) == ("", True)
    assert form.eur_gross.text() == ""            # no euro figure until there is a rate
    assert form.gross.text() == "100"             # only the rate goes
    win._finish_quit(None)


def test_the_plus_button_doesnt_keep_the_rate_of_1_either(book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    answer_dialogs.append(_new_client("Client Euro", currency="EUR"))
    win.form.add_client()
    assert win.form.rate.text() == "1"
    answer_dialogs.append(_new_client("Client Dollar", currency="USD"))
    win.form.add_client()
    assert (win.form.rate.text(), win.form.rate.isEnabled()) == ("", True)
    win._finish_quit(None)


def test_a_usd_payment_without_a_rate_is_refused(book, demo, qapp, tmp_path, monkeypatch, warnings):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    usd, eur = _usd_and_eur_clients(book, form)
    monkeypatch.setattr(form, "_confirm", lambda _s: True)
    _select(form, eur)
    _select(form, usd)
    entries = len(book.ledger.entries())
    form.description.setText("Annotation")
    form.gross.setText("100")
    form.net.setText("90")
    assert form.record() is None
    assert len(warnings) == 1
    assert len(book.ledger.entries()) == entries
    win._finish_quit(None)


def test_a_typed_rate_survives_anything_that_stays_in_the_same_currency(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    usd, _eur = _usd_and_eur_clients(book, form)
    other = book.clients.add(name="Client Dollar Bis", currency="USD")
    form.reload()
    _select(form, usd)
    form.rate.setText("1.0823")
    _select(form, other)                          # another client in the same currency
    assert form.rate.text() == "1.0823"
    win.reload_all()                              # what follows every change in the app
    assert form.rate.text() == "1.0823"
    assert form.rate.isEnabled()
    win._finish_quit(None)


def test_a_rate_of_1_typed_for_a_usd_client_is_left_alone(book, demo, qapp, tmp_path):
    """Only the 1 the form filled in itself goes away."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    usd, _eur = _usd_and_eur_clients(book, form)
    _select(form, usd)
    form.rate.setText("1")
    win.reload_all()
    assert form.rate.text() == "1"
    win._finish_quit(None)


def test_a_euro_client_keeps_its_rate_of_1_after_a_refresh(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    _usd, eur = _usd_and_eur_clients(book, form)
    _select(form, eur)
    win.reload_all()
    assert (form.rate.text(), form.rate.isEnabled()) == ("1", False)
    win._finish_quit(None)


def test_changing_the_selected_clients_currency_updates_the_rate(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    _usd, eur = _usd_and_eur_clients(book, form)
    _select(form, eur)
    book.clients.update(eur, currency="USD")      # what the Clients tab does
    win.on_records_changed()
    assert (form.rate.text(), form.rate.isEnabled()) == ("", True)
    win._finish_quit(None)


def test_a_euro_payment_records_at_1_after_leaving_a_usd_client(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    form = win.form
    usd, eur = _usd_and_eur_clients(book, form)
    monkeypatch.setattr(form, "_confirm", lambda _s: True)
    _select(form, usd)
    form.rate.setText("1.0823")
    _select(form, eur)
    form.description.setText("Annotation")
    form.gross.setText("100")
    form.net.setText("100")
    entry = book.ledger.get(form.record())
    assert entry["fx_rate"] == D(1)
    assert entry["eur_gross"] == D(100)
    win._finish_quit(None)


# -- the layout: a navigation rail, tiles, a slimmer top bar ---------------------
_PAGES_FR = ["Seuils", "Recettes", "Dépenses", "Clients", "Factures", "Échéances", "Revue annuelle", "Sauvegarde"]


def test_the_rail_lists_every_page_in_order_with_its_icon(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    assert [b.text().replace("\n", " ") for b in win.rail.buttons] == _PAGES_FR
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == _PAGES_FR
    assert all(not b.icon().isNull() for b in win.rail.buttons)
    assert all(b.toolTip() and b.accessibleName() for b in win.rail.buttons)
    win._finish_quit(None)


def test_the_rail_and_the_pages_follow_each_other(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.rail.buttons[3].click()
    assert win.tabs.currentWidget() is win.clients_panel
    win.tabs.setCurrentWidget(win.invoices_panel)          # what the app itself does
    assert win.rail.buttons[win.tabs.indexOf(win.invoices_panel)].isChecked()
    assert sum(b.isChecked() for b in win.rail.buttons) == 1
    win._finish_quit(None)


@pytest.mark.parametrize("number, panel", [(1, "dashboard_panel"), (4, "clients_panel"), (8, "backup_panel")])
def test_ctrl_and_a_number_opens_that_page(book, demo, qapp, tmp_path, number, panel):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.tabs.setCurrentIndex(2)
    action = next(a for a in win.actions() if a.shortcut().toString() == f"Ctrl+{number}")
    action.trigger()
    assert win.tabs.currentWidget() is getattr(win, panel)
    assert f"Ctrl+{number}" in win.tabs.tabToolTip(number - 1)
    win._finish_quit(None)


def test_ctrl_9_with_no_ninth_page_does_nothing(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.tabs.setCurrentIndex(2)
    next(a for a in win.actions() if a.shortcut().toString() == "Ctrl+9").trigger()
    assert win.tabs.currentIndex() == 2
    win._finish_quit(None)


@pytest.mark.parametrize("language", ["fr", "en"])
def test_the_rail_sits_far_left_and_every_label_fits(book, demo, qapp, tmp_path, language):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language=language)
    assert win.nav_bar.geometry().right() < win.payment_dock.geometry().left()
    assert win.rail.width() <= 110
    for button in win.rail.buttons:
        for line in button.text().split("\n"):
            assert button.fontMetrics().horizontalAdvance(line) <= button.width() - 8, line
    win._finish_quit(None)


def test_a_long_label_goes_on_two_lines_but_keeps_its_name(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    annual = win.tabs.indexOf(win.annual_panel)
    assert win.rail.buttons[annual].text() == "Revue\nannuelle"
    assert win.tabs.tabText(annual) == "Revue annuelle"
    assert win.rail.buttons[annual].accessibleName() == "Revue annuelle"
    win._finish_quit(None)


def test_counts_show_as_badges_on_the_rail(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    index = win.tabs.indexOf(win.deadlines_panel)
    button = win.rail.buttons[index]
    for counts, badge, level, text in (((2, 0), "2", "bad", "Deadlines  (2 overdue)"),
                                       ((0, 3), "3", "warn", "Deadlines  (3 soon)"),
                                       ((0, 0), "", None, "Deadlines")):
        monkeypatch.setattr(win.deadlines_panel, "counts", lambda c=counts: c)
        win._refresh_labels()
        assert button.badge == badge
        assert win.tabs.tabText(index) == text
        assert button.accessibleName() == text
        if level:
            assert button._badge_level == level
    win._finish_quit(None)


def test_the_year_at_a_glance_keeps_every_number(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    stats = win.dashboard_panel.stats
    assert set(stats.cards) == {"ytd", "projection", "ceiling_pct", "set_aside", "rate", "base", "next"}
    assert stats.cards["ytd"].value.text() == "€15,303.49"
    assert all(card.toolTip() for card in stats.cards.values())
    sizes = {key: card.value.fontInfo().pixelSize() for key, card in stats.cards.items()}
    assert sizes["ytd"] == max(sizes.values())               # the number that matters most is the biggest
    assert sizes["ytd"] > sizes["set_aside"] > sizes["projection"]
    first = next(i for i in book.deadlines.items() if i["status"] not in ("done", "passed") and i["due"])
    assert stats.next_note.text() == first["title"]
    win._finish_quit(None)


def test_the_top_bar_is_slim(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.brand_bar.height() <= 56
    win._finish_quit(None)


def test_rebuilding_for_a_language_keeps_one_rail(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.tabs.setCurrentWidget(win.invoices_panel)
    win.rebuild_for_language()
    QTest.qWait(30)
    rails = [bar for bar in win.findChildren(type(win.nav_bar)) if bar.objectName() == "navBar" and bar.isVisible()]
    assert len(rails) == 1
    assert win.rail.buttons[win.tabs.indexOf(win.invoices_panel)].isChecked()
    win._finish_quit(None)


# -- settings, behind the gear -------------------------------------------------
def test_settings_is_no_longer_a_tab(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.tabs.indexOf(win.settings_panel) == -1
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert "Settings" not in titles
    assert win.tabs.count() == 8
    win._finish_quit(None)


def test_the_gear_sits_right_next_to_help_and_shows_no_word(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    gear, help_button = win.settings_button, win.help_button
    assert gear.text() == ""
    assert gear.accessibleName() == "Settings"
    assert gear.toolTip()
    assert gear.parent() is help_button.parent() is win.brand_bar
    gap = help_button.geometry().left() - gear.geometry().right()
    assert 0 <= gap <= 12
    assert help_button.geometry().right() > win.brand_bar.width() - 40
    win._finish_quit(None)


def test_pressing_the_gear_opens_settings(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert not win.settings_dialog.isVisible()
    win.settings_button.click()
    qapp.processEvents()
    assert win.settings_dialog.isVisible()
    assert win.settings_panel.legal_name.text() == "Camille Exemple"
    win._finish_quit(None)


def test_settings_changes_reach_the_main_window(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.open_settings()
    win.settings_panel.acre.setChecked(False)
    win.settings_panel.save_profile()
    assert win.dashboard_panel.stats.cards["rate"].value.text() == "25.6%"
    assert win.settings_panel.saved_label.text() == "Saved."
    win._finish_quit(None)


@pytest.mark.parametrize("answer, closes, saved", [
    (QMessageBox.Cancel, False, False),
    (QMessageBox.Discard, True, False),
    (QMessageBox.Save, True, True),
])
def test_closing_with_unsaved_changes_asks_first(book, demo, qapp, tmp_path, monkeypatch, answer, closes, saved):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.open_settings()
    monkeypatch.setattr(win.settings_dialog, "_ask_about_unsaved", lambda: answer)
    win.settings_panel.email.setText("nouveau@example.invalid")
    win.settings_dialog.reject()
    qapp.processEvents()
    assert win.settings_dialog.isVisible() is not closes
    assert (book.profile().email == "nouveau@example.invalid") is saved
    win._finish_quit(None)


def test_closing_without_changes_asks_nothing(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.open_settings()

    def fail() -> Any:
        raise AssertionError("Nothing changed, so nothing to ask.")

    monkeypatch.setattr(win.settings_dialog, "_ask_about_unsaved", fail)
    win.settings_dialog.reject()
    qapp.processEvents()
    assert not win.settings_dialog.isVisible()
    win._finish_quit(None)


# -- language ------------------------------------------------------------------
def test_a_new_install_opens_in_french(book, qapp, tmp_path):
    win = MainWindow(book, client_factory=lambda: None, tokens=FakeTokens("no_client", tmp_path))
    assert i18n.current_language() == "fr"
    assert win.tabs.tabText(0) == "Seuils"
    assert win.help_button.text() == "Aide"
    assert win.settings_panel.language.findData("fr") >= 0
    win.settings_panel.reload()
    assert win.settings_panel.language.currentData() == "fr"
    win._finish_quit(None)


def test_qt_own_words_follow_the_language(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    box = win.settings_dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.Close).text() == "Fermer"
    assert QLocale().name().startswith("fr")
    win._finish_quit(None)


def test_switching_language_rebuilds_everything_and_loses_nothing(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    assert win.tabs.tabText(1) == "Recettes"
    win.tabs.setCurrentWidget(win.invoices_panel)
    entries = len(book.ledger.entries())

    win.open_settings(0)
    panel = win.settings_panel
    panel.language.setCurrentIndex(panel.language.findData("en"))
    panel.save_profile()
    QTest.qWait(30)
    qapp.processEvents()

    assert i18n.current_language() == "en"
    assert book.profile().language == "en"
    assert win.tabs.tabText(1) == "Payments"
    assert win.help_button.text() == "Help"
    assert win.tabs.currentWidget() is win.invoices_panel    # same place
    assert win.settings_dialog.isVisible()                   # settings stays open, now in English
    assert win.settings_panel.save_button.text() == "Save"
    assert win.dashboard_panel.stats.cards["ytd"].value.text() == "€15,303.49"
    assert len(book.ledger.entries()) == entries
    assert book.verify() == []
    win._finish_quit(None)


def test_switching_back_and_forth_keeps_working(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    for code, label in (("en", "Limits"), ("fr", "Seuils"), ("en", "Limits")):
        win.open_settings(0)
        panel = win.settings_panel
        panel.language.setCurrentIndex(panel.language.findData(code))
        panel.save_profile()
        QTest.qWait(30)
        qapp.processEvents()
        assert win.tabs.tabText(0) == label
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    win.settings_dialog.done(0)
    fill_form(win)
    assert win.form.record() is not None   # the rebuilt form still works
    win._finish_quit(None)


def test_saving_without_a_language_change_doesnt_rebuild(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    before = win.tabs
    win.open_settings()
    win.settings_panel.save_profile()
    QTest.qWait(30)
    qapp.processEvents()
    assert win.tabs is before
    win._finish_quit(None)


def test_recording_in_french_stores_the_key_not_the_french_word(book, demo, qapp, tmp_path, monkeypatch):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    monkeypatch.setattr(win.form, "_confirm", lambda _s: True)
    win.form.method.setCurrentIndex(win.form.method.findData("Bank transfer"))
    assert win.form.method.currentText() == "Virement bancaire"
    fill_form(win)
    seq = win.form.record()
    assert book.ledger.get(seq)["payment_method"] == "Bank transfer"
    assert "153,60" in win.status_label.text()
    win._finish_quit(None)


_ENGLISH_WORDS = re.compile(
    r"\b(the|and|with|your|this|that|from|will|have|not|for|are|you|isn't|can't|doesn't)\b", re.IGNORECASE
)


def _all_text(win: MainWindow, extra: list[QWidget]) -> list[str]:
    """Every word the app can show: labels, buttons, bubbles, hints, headers, cells."""
    texts: list[str] = []
    roots: list[QWidget] = [win] + extra
    for root in roots:
        for widget in [root] + root.findChildren(QWidget):
            if isinstance(widget, (QLabel, QAbstractButton)):
                texts.append(widget.text())
            if isinstance(widget, QLineEdit):
                texts.append(widget.placeholderText())
            if isinstance(widget, QGroupBox):
                texts.append(widget.title())
            if isinstance(widget, QComboBox):
                texts += [widget.itemText(i) for i in range(widget.count())]
            if isinstance(widget, QTabWidget):
                texts += [widget.tabText(i) for i in range(widget.count())]
                texts += [widget.tabToolTip(i) for i in range(widget.count())]
            texts.append(widget.toolTip())
            texts.append(widget.accessibleDescription())
            if isinstance(widget, DataTable):
                for row in range(widget.proxy.rowCount()):
                    for col in range(widget.proxy.columnCount()):
                        texts.append(str(widget.proxy.index(row, col).data() or ""))
                for col in widget.model.columns:
                    texts += [col.title, col.tip]
    return [t for t in texts if t]


def _every_dialog(book: Any, win: MainWindow, demo: dict[str, Any]) -> list[QWidget]:
    entry = dict(book.ledger.entries()[0])
    invoice = book.invoices.get(demo["invoices"][9])
    figure = book.figures.rows()[0]
    return [
        ReverseDialog(entry, win),
        PurchaseDialog(book, win),
        PurchaseDialog(book, win, template=dict(book.purchases.entries()[0])),
        ReversePurchaseDialog(dict(book.purchases.entries()[0]), win),
        EditDraftDialog(book, demo["invoices"][9], win),
        IssueDialog(book, invoice, win),
        CreditDialog("FA-2026-0001", win),
        ClientDialog(None, win),
        FigureDialog(figure, win),
        StripeImportDialog(book, config.secrets_dir() / "no_stripe_key.txt", lambda *_a: None, win, threaded=False),
    ]


def test_the_french_ui_shows_no_english(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.settings_panel.reload()
    win.deadlines_panel.show_done.setChecked(True)
    texts = _all_text(win, _every_dialog(book, win, demo))
    assert len(texts) > 500
    hits = sorted({t[:90] for t in texts if _ENGLISH_WORDS.search(t)})
    assert not hits, hits[:10]
    win._finish_quit(None)


def test_no_english_source_string_reaches_the_french_screen(book, demo, qapp, tmp_path):
    """Catches what the word check can't: one untranslated word, such as a status."""
    catalog = json.loads(
        (config.PACKAGE_DATA_DIR / "i18n" / "fr.json").read_text(encoding="utf-8")
    )["messages"]
    english_only = set(catalog) - set(catalog.values())
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.settings_panel.reload()
    win.deadlines_panel.show_done.setChecked(True)
    shown = {t.removeprefix("<qt>").removesuffix("</qt>") for t in _all_text(win, _every_dialog(book, win, demo))}
    assert not sorted(shown & english_only)
    win._finish_quit(None)


def test_statuses_are_translated_but_stay_keys_underneath(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    backup = win.backup_panel
    backup.reload()
    assert backup.table.model.rows[0]["status"] == "pending"
    assert backup.table.proxy.index(0, 0).data() == "en attente"
    invoices = win.invoices_panel.table
    assert invoices.model.rows[0]["status"] == "draft"
    assert invoices.proxy.index(0, 2).data() == "brouillon"
    win._finish_quit(None)


def test_the_dock_keeps_its_width_after_a_language_switch(book, demo, qapp, tmp_path):
    """Found on screen: resizing a dock before it is laid out does nothing."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    QTest.qWait(30)
    before = win.payment_dock.width()
    win.open_settings(0)
    panel = win.settings_panel
    panel.language.setCurrentIndex(panel.language.findData("en"))
    panel.save_profile()
    for _ in range(4):     # at every moment, not just once it has settled
        QTest.qWait(80)
        qapp.processEvents()
        assert win.payment_dock.width() < before * 1.3
    assert win.payment_dock.maximumWidth() > before        # unpinned again afterwards
    win._finish_quit(None)


def test_the_english_ui_is_really_english(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    win.settings_panel.reload()
    assert win.tabs.tabText(0) == "Limits"
    assert win.ledger_panel.table.model.columns[1].title == "Received"
    assert win.form.record_button.text() == "Record payment"
    assert win.dashboard_panel.cards["ceiling"].title.text() == "Micro ceiling"
    win._finish_quit(None)


# -- every box, button and line has its bubble ---------------------------------
_NEEDS_OWN_BUBBLE = (QPushButton, QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QCheckBox,
                     QGroupBox, StatCard, Chip, ThresholdBar, QTableView, QTableWidget)


def _is_qt_internal(widget: QWidget) -> bool:
    """The parts of a date field, a calendar or a scroll area aren't ours to label."""
    if widget.objectName().startswith("qt_"):
        return True
    parent = widget.parent()
    while parent is not None:
        if isinstance(parent, (QCalendarWidget, QAbstractSpinBox, QComboBox)):
            return True
        parent = parent.parent()
    return False


def _effective_bubble(widget: QWidget, stop: QWidget) -> str:
    """A hover falls through to the parent if the widget has no bubble of its own."""
    current: Any = widget
    while current is not None and current is not stop:
        if current.toolTip():
            return current.toolTip()
        current = current.parentWidget()
    return ""


def _bubble_gaps(root: QWidget) -> list[str]:
    gaps = []
    for widget in root.findChildren(QWidget):
        if _is_qt_internal(widget):
            continue
        name = f"{type(widget).__name__} {widget.objectName()!r}"
        if isinstance(widget, _NEEDS_OWN_BUBBLE) and not widget.toolTip():
            label = widget.text() if isinstance(widget, (QAbstractButton, QLabel)) else ""
            gaps.append(f"{name} {label!r}")
        elif isinstance(widget, QLabel) and widget.buddy() is not None and not widget.toolTip():
            # A field's label must say what the field is, not fall through to its group's bubble.
            gaps.append(f"form label {widget.text()!r}")
        elif isinstance(widget, QLabel) and widget.text() and not _effective_bubble(widget, root):
            gaps.append(f"{name} {widget.text()[:50]!r}")
        elif isinstance(widget, QTabWidget):
            gaps += [f"tab {widget.tabText(i)!r}" for i in range(widget.count()) if not widget.tabToolTip(i)]
        elif isinstance(widget, DataTable):
            gaps += [f"column {c.title!r}" for c in widget.model.columns if not c.tip]
    return gaps


@pytest.mark.parametrize("language", ["en", "fr"])
def test_everything_in_the_main_window_has_a_bubble(book, demo, qapp, tmp_path, language):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language=language)
    win.settings_panel.reload()
    gaps = _bubble_gaps(win)
    assert not gaps, gaps
    win._finish_quit(None)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_every_dialog_has_its_bubbles(book, demo, qapp, tmp_path, language):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language=language)
    for dialog in _every_dialog(book, win, demo):
        gaps = _bubble_gaps(dialog)
        assert not gaps, (type(dialog).__name__, gaps)
    win._finish_quit(None)


def test_bubbles_stay_after_each_kind_of_refresh(book, demo, qapp, tmp_path):
    """Several bubbles are written by reload(): they must not be left blank by it."""
    win = make_window(book, qapp, state="connected", tmp=tmp_path)
    win.reload_all()
    win.backup_panel.reload()
    assert not _bubble_gaps(win.backup_panel)
    assert not _bubble_gaps(win.dashboard_panel)
    win._finish_quit(None)


def test_number_cards_say_what_they_are_and_their_value(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    card = win.dashboard_panel.stats.cards["ytd"]
    assert "from 1 January" in card.toolTip()
    assert card.accessibleName() == "Year to date: €15,303.49"
    assert card.accessibleDescription()
    assert card.focusPolicy() == Qt.TabFocus    # reachable without a mouse
    win._finish_quit(None)


def test_bubbles_with_figures_stay_up_to_date(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    stats = win.dashboard_panel.stats.cards
    assert "of 179 days" in stats["projection"].toolTip()
    assert "40,998" in stats["ceiling_pct"].toolTip()
    assert "BNC + ACRE" in stats["rate"].toolTip()
    assert "Turnover declaration" in stats["next"].toolTip()
    win._finish_quit(None)


def _shown_bubble(qapp: Any, widget: QWidget) -> QWidget:
    QToolTip.showText(widget.mapToGlobal(widget.rect().bottomLeft()), widget.toolTip(), widget)
    qapp.processEvents()
    return next(w for w in qapp.topLevelWidgets() if w.objectName() == "qtooltip_label" and w.isVisible())


def test_a_long_bubble_is_a_comfortable_width_and_a_short_one_stays_on_one_line(book, demo, qapp, tmp_path):
    """Found by measuring: left alone, Qt wrapped two sentences into a 135 px column."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    long_tip = _shown_bubble(qapp, win.dashboard_panel.stats.cards["projection"])
    assert long_tip.width() >= 300
    assert long_tip.height() < 120
    QToolTip.hideText()
    qapp.processEvents()
    bubble(win.help_button, "Short text.")
    short_tip = _shown_bubble(qapp, win.help_button)
    assert short_tip.height() < 45
    QToolTip.hideText()
    win._finish_quit(None)


def test_bubbles_are_dark_and_use_the_app_font_size(book, demo, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    tip = _shown_bubble(qapp, win.settings_button)
    assert tip.grab().toImage().pixelColor(6, 6).name() == theme.SURFACE_2
    assert tip.font().pixelSize() == 12
    QToolTip.hideText()
    win._finish_quit(None)


def test_a_bubble_shows_angle_brackets_literally():
    assert "a &lt; b &amp; c" in wrap_tip("a < b & c")


def test_every_bubble_is_rich_text_so_it_can_wrap():
    assert wrap_tip("short").startswith("<qt>")
    assert wrap_tip("long " * 40).startswith("<qt>")


# -- look --------------------------------------------------------------------
def test_the_theme_paints_with_its_tokens():
    """The palette left PolyClusters' for its own in the 2026 redesign; test_theme.py checks its contrast."""
    for token in (theme.SURFACE_0, theme.SURFACE_1, theme.SURFACE_2, theme.LINE, theme.TEXT, theme.ACCENT,
                  theme.ACCENT_FILL):
        assert token in STYLESHEET


def test_the_assets_it_loads_exist():
    for path in (config.LOGO_DISPLAY_DARK, config.LOGO_ICON, config.APP_ICO):
        assert path.exists(), path
    for url in re.findall(r"url\(([^)]+)\)", STYLESHEET):
        assert Path(url).exists(), url


# -- what must not be in the repository --------------------------------------
_FORBIDDEN = ("ali" + "gnerr", "sa" + "my", "zer" + "arka")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}\b")
_NIR = re.compile(r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b")


def _source_files() -> list[Path]:
    found = []
    for folder in ("microcompta", "tests", "scripts"):
        found += [p for p in (ROOT / folder).rglob("*") if p.suffix in (".py", ".json")]
    for name in ("README.md", "run.bat", "run.sh", "pyproject.toml", "requirements.txt"):
        path = ROOT / name
        if path.exists():
            found.append(path)
    return found


def test_no_real_personal_data_in_the_repository():
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for word in _FORBIDDEN:
            assert word not in lowered, f"{word} in {path}"
        assert not _IBAN.search(text), f"IBAN-like value in {path}"
        assert not _NIR.search(text), f"Social security number-like value in {path}"


def test_the_settings_page_fits_its_dialog(book, demo, qapp, tmp_path):
    """Found on screen: two long ticks pushed the right column past the dialog's edge."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language="fr")
    win.open_settings(0)
    qapp.processEvents()
    page = win.settings_panel.tabs.widget(0)
    assert page.viewport().width() >= page.widget().minimumSizeHint().width()
    assert win.settings_dialog.width() <= win.width()
    win.settings_dialog.done(0)
    win._finish_quit(None)


@pytest.mark.parametrize("language", ["fr", "en"])
def test_no_field_overlaps_the_next_in_the_client_window(book, demo, qapp, tmp_path, language):
    """Found on screen: a wrapped line left out of the window's height squeezed the address box
    over the country field."""
    win = make_window(book, qapp, state="no_client", tmp=tmp_path, language=language)
    dialog = ClientDialog(parent=win)
    dialog.show()
    qapp.processEvents()
    fields = [dialog.name, dialog.address, dialog.country, dialog.tax_id, dialog.email, dialog.currency]
    for above, below in zip(fields, fields[1:]):
        assert above.geometry().bottom() < below.geometry().top(), (above, below)
    dialog.done(0)
    win._finish_quit(None)
