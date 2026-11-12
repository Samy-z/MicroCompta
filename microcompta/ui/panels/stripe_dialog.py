"""Import from Stripe: the payments not recorded yet, one click away from the payment form.

The window never records anything. It fills the form, and you check the payment and record
it there as usual, with the same checks and the same confirmation.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QDialogButtonBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ...core import clock
from ...core.book import Book
from ...i18n import tr
from ...imports.stripe import (
    StripeError, StripePayment, StripeReading, StripeSource, forget_key, key_hint, load_key, save_key,
)
from ..models import Col
from ..widgets.table_view import DataTable
from .common import Banner, FittedDialog, bubble, button_box, dim_label, guarded, heading


class StripeReadWorker(QThread):
    """Reads Stripe off the window's thread, so the window never waits on the network."""

    finished_ok = Signal(object)    # StripeReading
    failed = Signal(str)

    def __init__(self, source: Any, since: date, parent: QObject | None = None):
        super().__init__(parent)
        self.source = source
        self.since = since

    def run(self) -> None:
        try:
            self.finished_ok.emit(self.source.read(self.since))
        except StripeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - shown, never fatal
            self.failed.emit(tr("Stripe could not be read ({error}).", error=type(exc).__name__))


def _columns() -> list[Col]:
    return [
        Col("paid_on", tr("Paid on"), "date", 90, tip=tr("The day the client paid. It becomes the date received.")),
        Col("client", tr("Client"), width=150, tip=tr("The client this payment will go to. You can change it in the form.")),
        Col("description", tr("Description"), width=200, tip=tr("Stripe's description of the payment, if any.")),
        Col("amount", tr("Gross"), "money", 90, currency_key="currency", tip=tr("What the client paid, in their currency.")),
        Col("fee", tr("Fee"), "money", 70, currency_key="fee_currency", tip=tr("What Stripe kept.")),
        Col("net", tr("Net credited"), "money", 90, currency_key="net_currency",
            tip=tr("What reached your Stripe balance.")),
        Col("rate", tr("Stripe rate"), "rate", 80,
            tip=tr("Units of the client's currency for 1 EUR, as Stripe converted. For information.")),
        Col("note", tr("Note"), width=240, tip=tr("Anything to check before recording.")),
    ]


class StripeImportDialog(FittedDialog):
    def __init__(self, book: Book, key_path: Path, fill: Callable[[StripePayment, int | None], None],
                 parent: QWidget | None = None, source_factory: Callable[[str], Any] = StripeSource,
                 threaded: bool = True):
        super().__init__(parent)
        self.book = book
        self.key_path = key_path
        self.fill = fill
        self.source_factory = source_factory
        self.threaded = threaded
        self.worker: StripeReadWorker | None = None
        self.setWindowTitle(tr("Import from Stripe"))
        self.resize(1060, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(heading(tr("Payments from Stripe"), tr("Read with a restricted key, read only."), "h2"))
        layout.addWidget(dim_label(
            tr("Choose a payment to fill the payment form. You check it there and record it yourself: "
               "nothing is recorded from this window."),
            tip=tr("Recorded payments drop out of this list, found by their Stripe reference."),
        ))

        # The key: entered once, then only a hint of it is shown.
        self.key_row = QWidget()
        key_box = QVBoxLayout(self.key_row)
        key_box.setContentsMargins(0, 0, 0, 0)
        key_box.addWidget(dim_label(tr("Create it in your Stripe dashboard, under API keys: a restricted key with read access to Balance, Charges and Customers, and nothing else."), tip=tr("A key with only read access can't move money or change anything in Stripe.")))
        key_lay = QHBoxLayout()
        key_box.addLayout(key_lay)
        self.key_field = QLineEdit()
        self.key_field.setEchoMode(QLineEdit.Password)
        self.key_field.setPlaceholderText(tr("rk_live_…"))
        bubble(self.key_field, tr(
            "A restricted key from your Stripe dashboard, with read access to balance, charges and "
            "customers. A secret key (sk_) is refused."
        ), tr("Stripe key"))
        key_lay.addWidget(self.key_field, 1)
        self.save_key_button = QPushButton(tr("Save key"))
        bubble(self.save_key_button, tr("Kept on this computer, beside your Google access. Never logged."))
        self.save_key_button.clicked.connect(lambda _c=False: self.save_key())
        key_lay.addWidget(self.save_key_button)
        layout.addWidget(self.key_row)

        self.saved_row = QWidget()
        saved_lay = QHBoxLayout(self.saved_row)
        saved_lay.setContentsMargins(0, 0, 0, 0)
        self.key_label = dim_label("", wrap=False, tip=tr("The start and end of the saved key."))
        saved_lay.addWidget(self.key_label, 1)
        self.forget_button = QPushButton(tr("Forget key"))
        bubble(self.forget_button, tr("Deletes the key from this computer. Nothing changes in Stripe."))
        self.forget_button.clicked.connect(lambda _c=False: self.forget())
        saved_lay.addWidget(self.forget_button)
        layout.addWidget(self.saved_row)

        self.problem = Banner("bad", tip=tr("Why Stripe could not be read."))
        layout.addWidget(self.problem)

        self.table = DataTable(_columns(), key="id")
        self.refresh_button = self.table.add_button(tr("Refresh"), self.refresh, primary=True, tip=tr(
            "Reads the payments since your start date again."
        ))
        self.fill_button = self.table.add_button(tr("Fill the payment form"), self.fill_selected, tip=tr(
            "Copies the selected payment into the payment form and closes this window."
        ))
        self.dismiss_button = self.table.add_button(tr("Ignore"), self.dismiss_selected, tip=tr(
            "Stops offering the selected payment, for a test payment or one recorded another way."
        ))
        self.table.row_selected.connect(self._on_selected)
        self.table.row_activated.connect(lambda _row: self.fill_selected())
        layout.addWidget(self.table, 1)
        self.summary = dim_label("", tip=tr("What the last reading found."))
        layout.addWidget(self.summary)
        layout.addWidget(button_box(QDialogButtonBox.Close, self.accept, self.reject))

        self._payments: dict[str, StripePayment] = {}
        self._show_key_state()
        self._on_selected(None)
        if load_key(self.key_path):
            self.refresh()

    # -- the key ------------------------------------------------------------------
    def _show_key_state(self) -> None:
        key = load_key(self.key_path)
        self.key_row.setVisible(key is None)
        self.saved_row.setVisible(key is not None)
        self.refresh_button.setEnabled(key is not None)
        if key:
            self.key_label.setText(tr("Key saved: {hint}", hint=key_hint(key)))

    def save_key(self) -> bool:
        ok = guarded(self, tr("Key not saved"), lambda: save_key(self.key_path, self.key_field.text()) or True)
        self.key_field.clear()
        self._show_key_state()
        if ok:
            self.refresh()
        return bool(ok)

    def forget(self) -> None:
        forget_key(self.key_path)
        self.table.set_rows([])
        self._payments = {}
        self.summary.setText("")
        self._show_key_state()

    # -- reading ------------------------------------------------------------------
    def _since(self) -> date:
        start = self.book.profile().start_date
        return start or date(clock.today().year, 1, 1)

    def refresh(self) -> None:
        key = load_key(self.key_path)
        if key is None or (self.worker is not None and self.worker.isRunning()):
            return
        self.problem.show_text("")
        self.summary.setText(tr("Reading Stripe…"))
        self.refresh_button.setEnabled(False)
        source = self.source_factory(key)
        if not self.threaded:
            try:
                self.show_reading(source.read(self._since()))
            except StripeError as exc:
                self.show_problem(str(exc))
            return
        self.worker = StripeReadWorker(source, self._since(), self)
        self.worker.finished_ok.connect(self.show_reading)
        self.worker.failed.connect(self.show_problem)
        self.worker.start()

    def show_problem(self, message: str) -> None:
        self.problem.show_text(message)
        self.summary.setText("")
        self.refresh_button.setEnabled(load_key(self.key_path) is not None)

    def show_reading(self, reading: StripeReading) -> None:
        pending = self.book.stripe.pending(reading)
        self._payments = {p.id: p for p in pending}
        names = {c["id"]: c["name"] for c in self.book.clients.list()}
        rows = []
        for p in pending:
            client_id = self.book.stripe.match_client(p)
            rows.append({
                "id": p.id, "paid_on": p.paid_on, "client": names.get(client_id, "—"),
                "description": p.description, "amount": p.amount, "currency": p.currency,
                "fee": p.fee, "fee_currency": p.fee_currency, "net": p.net, "net_currency": p.net_currency,
                "rate": p.provider_rate,
                "note": tr("Refunded: record it, then reverse it") if p.refunded else "",
            })
        self.table.set_rows(rows)
        self.table.select_first()
        text = (tr("{count} payment to record.", count=len(rows)) if len(rows) == 1
                else tr("{count} payments to record.", count=len(rows)))
        if reading.refunds:
            text += " " + tr("{count} refund(s) seen: reverse the matching entry on the Payments page.",
                             count=reading.refunds)
        self.summary.setText(text)
        self.refresh_button.setEnabled(True)

    # -- acting on a payment ---------------------------------------------------------
    def _selected(self) -> StripePayment | None:
        row = self.table.current_row()
        return self._payments.get(row["id"]) if row else None

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        self.fill_button.setEnabled(row is not None)
        self.dismiss_button.setEnabled(row is not None)

    def fill_selected(self) -> None:
        payment = self._selected()
        if payment is None:
            return
        self.fill(payment, self.book.stripe.match_client(payment))
        self.accept()

    def dismiss_selected(self) -> None:
        payment = self._selected()
        if payment is None:
            return
        self.book.stripe.dismiss(payment.id)
        self._payments.pop(payment.id, None)
        self.table.set_rows([r for r in self.table.model.rows if r["id"] != payment.id])
        self._on_selected(self.table.current_row())

    def done(self, result: int) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(2000)
        super().done(result)


__all__ = ["StripeImportDialog", "StripeReadWorker"]
