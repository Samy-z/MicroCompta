"""The left dock: recording a payment. The one thing done every week."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure, ValidationError
from ...core.ledger import PAYMENT_METHODS, RATE_SOURCES
from ...core.ledger_policy import UNCONFIRMED
from ...core.money import fmt_money, round_money, to_decimal
from .common import dim_label, from_qdate, guarded, make_date_edit, to_qdate


class PaymentForm(QScrollArea):
    recorded = Signal(int)
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._receipt: str = ""

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        payment = QGroupBox("Payment")
        form = QFormLayout(payment)
        form.setSpacing(6)
        self.date = make_date_edit(clock.today())
        self.date.setToolTip("Turnover counts on the date received, not the invoice date.")
        form.addRow("Received on", self.date)
        self.client = QComboBox()
        self.client.currentIndexChanged.connect(self._on_client)
        form.addRow("Client", self.client)
        self.description = QLineEdit()
        self.description.setPlaceholderText("Annotation work, week 12")
        form.addRow("Description", self.description)
        self.method = QComboBox()
        self.method.addItems(PAYMENT_METHODS)
        form.addRow("Method", self.method)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Provider's reference")
        form.addRow("Reference", self.reference)
        layout.addWidget(payment)

        amounts = QGroupBox("Amounts")
        grid = QFormLayout(amounts)
        grid.setSpacing(6)
        self.gross = QLineEdit()
        self.gross.setPlaceholderText("0.00")
        self.gross.textChanged.connect(self._update_preview)
        grid.addRow("Gross", self.gross)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("1.0823")
        self.rate.setToolTip("Units of the currency for 1 EUR, as the ECB publishes it.")
        self.rate.textChanged.connect(self._update_preview)
        grid.addRow("Rate per 1 EUR", self.rate)
        self.rate_source = QComboBox()
        self.rate_source.addItems(RATE_SOURCES)
        grid.addRow("Rate source", self.rate_source)
        self.eur_gross = QLineEdit()
        self.eur_gross.setReadOnly(True)
        grid.addRow("EUR gross", self.eur_gross)

        fee_row = QHBoxLayout()
        self.fee = QLineEdit("0")
        self.fee.setToolTip("The provider's fee, stored separately from gross and net.")
        self.fee.textChanged.connect(self._update_preview)
        self.fee_currency = QComboBox()
        self.fee_currency.addItems(["USD", "EUR"])
        self.fee_currency.setMaximumWidth(70)
        self.fee_currency.currentIndexChanged.connect(self._update_preview)
        fee_row.addWidget(self.fee, 1)
        fee_row.addWidget(self.fee_currency)
        grid.addRow("Provider fee", fee_row)

        net_row = QHBoxLayout()
        self.net = QLineEdit()
        self.net.setPlaceholderText("0.00")
        self.net_currency = QComboBox()
        self.net_currency.addItems(["EUR", "USD"])
        self.net_currency.setMaximumWidth(70)
        net_row.addWidget(self.net, 1)
        net_row.addWidget(self.net_currency)
        grid.addRow("Net credited", net_row)
        self.set_aside = QLineEdit()
        self.set_aside.setReadOnly(True)
        self.set_aside.setToolTip("Contributions on this payment at the rate in force on its date.")
        grid.addRow("To set aside", self.set_aside)
        layout.addWidget(amounts)

        self.unconfirmed = dim_label(
            f"USD rate and fees in turnover: {UNCONFIRMED}. Each value is kept separately, so "
            "the setting can change later without touching an entry."
        )
        layout.addWidget(self.unconfirmed)

        receipt_row = QHBoxLayout()
        self.receipt_button = QPushButton("Attach receipt…")
        self.receipt_button.clicked.connect(self._choose_receipt)
        receipt_row.addWidget(self.receipt_button)
        self.receipt_label = dim_label("", wrap=False)
        receipt_row.addWidget(self.receipt_label, 1)
        layout.addLayout(receipt_row)

        self.record_button = QPushButton("Record payment")
        self.record_button.setObjectName("primary")
        self.record_button.clicked.connect(lambda _checked=False: self.record())
        layout.addWidget(self.record_button)
        layout.addWidget(dim_label("Entries can't be edited once recorded. "
                                   "A correction is a reversing entry with a reason."))
        layout.addStretch(1)
        self.setWidget(inner)
        self.reload()

    # -- state --------------------------------------------------------------
    def reload(self) -> None:
        current = self.client.currentData()
        self.client.blockSignals(True)
        self.client.clear()
        for client in self.book.clients.list(active_only=True):
            self.client.addItem(client["name"], client["id"])
        if current is not None:
            index = self.client.findData(current)
            if index >= 0:
                self.client.setCurrentIndex(index)
        self.client.blockSignals(False)
        has_client = self.client.count() > 0
        self.record_button.setEnabled(has_client)
        self.record_button.setToolTip("" if has_client else "Add a client under Settings > Clients.")
        self.date.setMaximumDate(to_qdate(clock.today()))
        self._on_client()

    def _currency(self) -> str:
        client_id = self.client.currentData()
        client = self.book.clients.get(client_id) if client_id is not None else None
        return client["currency"] if client else "USD"

    def _on_client(self, *_args: Any) -> None:
        currency = self._currency()
        self.gross.setPlaceholderText(f"0.00 {currency}")
        if currency == "EUR":
            self.rate.setText("1")
        self.rate.setEnabled(currency != "EUR")
        self.fee_currency.setItemText(0, currency if currency != "EUR" else "EUR")
        self._update_preview()

    def _update_preview(self, *_args: Any) -> None:
        try:
            gross = to_decimal(self.gross.text())
            rate = to_decimal(self.rate.text() or "0")
            if rate <= 0:
                raise ValidationError("rate")
        except ValidationError:
            self.eur_gross.clear()
            self.set_aside.clear()
            return
        eur = round_money(gross / rate)
        self.eur_gross.setText(fmt_money(eur))
        try:
            fee = to_decimal(self.fee.text() or "0")
            fee_eur = fee if self.fee_currency.currentText() == "EUR" else round_money(fee / rate)
        except ValidationError:
            fee_eur = Decimal(0)
        self.net.setPlaceholderText(f"{eur - fee_eur:.2f}")
        self._update_set_aside(eur, fee_eur)

    def _update_set_aside(self, eur: Decimal, fee_eur: Decimal) -> None:
        from ...core.limits import contribution_rate

        profile = self.book.profile()
        base = eur - fee_eur if profile.turnover_basis == "net_of_fees" else eur
        try:
            info = contribution_rate(from_qdate(self.date.date()), profile, self.book.figures)
        except Exception:  # noqa: BLE001 - a missing figure is reported on the dashboard
            self.set_aside.clear()
            return
        self.set_aside.setText(f"{fmt_money(round_money(base * info.rate))}  ({info.rate * 100:.1f}%)")

    def _choose_receipt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Attach a receipt")
        if path:
            self.set_receipt(path)

    def set_receipt(self, path: str) -> None:
        self._receipt = path
        self.receipt_label.setText(path.replace("\\", "/").rsplit("/", 1)[-1])

    # -- recording ----------------------------------------------------------
    def _confirm(self, summary: str) -> bool:
        reply = QMessageBox.question(
            self, "Record this payment?",
            f"{summary}\n\nThis can't be edited afterwards. A correction is a reversing entry.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def record(self) -> int | None:
        client_id = self.client.currentData()
        if client_id is None:
            QMessageBox.information(self, "No client", "Add a client under Settings > Clients first.")
            return None
        received_on = from_qdate(self.date.date())
        summary = (
            f"{received_on}  ·  {self.client.currentText()}\n{self.description.text().strip()}\n"
            f"Gross {self.gross.text().strip() or '?'} {self._currency()}, "
            f"rate {self.rate.text().strip() or '?'}, EUR gross {self.eur_gross.text() or '?'}\n"
            f"Fee {self.fee.text().strip() or '0'} {self.fee_currency.currentText()}, "
            f"net {self.net.text().strip() or '?'} {self.net_currency.currentText()}"
        )
        if not self._confirm(summary):
            return None
        seq = guarded(self, "Payment not recorded", lambda: self.book.ledger.record_payment(
            received_on=received_on,
            client_id=client_id,
            description=self.description.text(),
            amount_gross=self.gross.text(),
            fx_rate=self.rate.text(),
            fx_source=self.rate_source.currentText(),
            fee_amount=self.fee.text(),
            fee_currency=self.fee_currency.currentText(),
            net_credited=self.net.text(),
            net_currency=self.net_currency.currentText(),
            payment_method=self.method.currentText(),
            provider_ref=self.reference.text(),
        ))
        if seq is None:
            return None
        if self._receipt:
            # The payment is already recorded, so a bad receipt path must not read as a failure.
            guarded(self, "Receipt not attached", lambda: self.book.attach_receipt(seq, self._receipt))
        entry = self.book.ledger.get(seq)
        try:
            amount = self.book.limits.set_aside_for(entry, self.book.profile())
            self.status.emit(f"Entry {seq} recorded. Set aside {fmt_money(amount)} for this payment.")
        except MissingFigure as exc:
            self.status.emit(f"Entry {seq} recorded. {exc}")
        self._clear()
        self.recorded.emit(seq)
        return seq

    def _clear(self) -> None:
        for field in (self.description, self.gross, self.net, self.reference):
            field.clear()
        self.fee.setText("0")
        self._receipt = ""
        self.receipt_label.clear()
