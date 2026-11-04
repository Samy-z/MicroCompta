"""The real window, offscreen, on fake data. Drives the panels the way a click would."""

from __future__ import annotations

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

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDateEdit, QDialog, QMessageBox  # noqa: E402

import demo_data  # noqa: E402
from conftest import FakeDrive  # noqa: E402
from microcompta import config  # noqa: E402
from microcompta.ui.main_window import MainWindow  # noqa: E402
from microcompta.ui.panels import common  # noqa: E402
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
                tmp: Path | None = None) -> MainWindow:
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
    assert win.tabs.currentWidget() is win.settings_panel
    assert win.settings_panel.setup_banner.isVisibleTo(win)
    assert not win.form.record_button.isEnabled()
    for index in range(win.tabs.count()):
        win.tabs.setCurrentIndex(index)
        qapp.processEvents()
    win._finish_quit(None)


def test_identity_is_never_prefilled(book, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    assert win.settings_panel.legal_name.text() == ""
    assert win.settings_panel.siren.text() == ""
    assert win.settings_panel.address.toPlainText() == ""
    assert book.clients.list() == []
    win._finish_quit(None)


def test_settings_save_round_trip(book, qapp, tmp_path):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.settings_panel
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
    assert not panel.setup_banner.isVisibleTo(win)
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
    assert len(drive.files) == 5   # two invoices, the snapshot and two CSVs
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
    panel = win.settings_panel

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
    assert win.form.client.count() == 1
    assert win.form.record_button.isEnabled()

    panel.clients_table.select_first()

    def edit(dialog: Any) -> None:
        assert dialog.name.text() == "Client Test"
        dialog.taxed_in_france.setChecked(False)

    answer_dialogs.append(edit)
    panel.edit_client()
    assert book.clients.list()[0]["taxed_in_france"] is False
    assert "probably; SIE to confirm" in panel.clients_table.model.rows[0]["vat_flag"]
    win._finish_quit(None)


def test_figure_dialog_adds_a_later_value_and_the_old_one_stays(
        book, demo, qapp, tmp_path, answer_dialogs):
    win = make_window(book, qapp, state="no_client", tmp=tmp_path)
    panel = win.settings_panel
    panel.figures_table.select_key("micro_ceiling|2026-01-01")

    def fill(dialog: Any) -> None:
        dialog.effective.setDate(common.to_qdate(date(2029, 1, 1)))
        dialog.value.setText("90000")
        dialog.source.setText("Test")

    answer_dialogs.append(fill)
    panel.edit_figure()
    assert book.figures.value("micro_ceiling", date(2028, 12, 31)) == D(83600)
    assert book.figures.value("micro_ceiling", date(2029, 1, 1)) == D(90000)
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


# -- look --------------------------------------------------------------------
def test_theme_uses_the_same_tokens_as_polyclusters():
    for token in ("#14161c", "#1a1d25", "#20242e", "#2c313d", "#4f9cf9", "#2d5c96"):
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
