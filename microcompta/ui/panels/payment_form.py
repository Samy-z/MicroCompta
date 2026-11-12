"""The left dock: recording a payment. The one thing done every week."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure, ValidationError
from ...core.ledger import PAYMENT_METHODS, RATE_SOURCES
from ...core.ledger_policy import UNCONFIRMED
from ...core.money import fmt_money, round_money, to_decimal
from ...i18n import fmt_number, fmt_percent, fmt_rate, tr
from .clients_panel import ask_for_new_client
from .common import bubble, dim_label, form_row, from_qdate, guarded, make_date_edit, to_qdate


class PaymentForm(QScrollArea):
    recorded = Signal(int)
    client_added = Signal()
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

        payment = QGroupBox(tr("Payment"))
        bubble(payment, tr("What was received, from whom, and how."))
        form = QFormLayout(payment)
        form.setSpacing(6)
        self.date = make_date_edit(clock.today())
        form_row(form, tr("Received on"), self.date, tr(
            "The day the money arrived. Turnover counts on this date, not the invoice date."
        ))
        self.client = QComboBox()
        # A long client name must not decide the width of the whole form. The list itself
        # still opens wide enough to read it: see reload().
        self.client.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.client.setMinimumContentsLength(12)
        self.client.currentIndexChanged.connect(self._on_client)
        self.add_client_button = QPushButton("+")
        self.add_client_button.setObjectName("addClient")
        self.add_client_button.setFixedWidth(30)
        self.add_client_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)   # as tall as the list
        self.add_client_button.clicked.connect(lambda _checked=False: self.add_client())
        client_row = QHBoxLayout()
        client_row.setSpacing(4)
        client_row.addWidget(self.client, 1)
        client_row.addWidget(self.add_client_button)
        form_row(form, tr("Client"), client_row, tr(
            "Who paid. The ledger keeps a copy of the name. To add one, use the + button beside "
            "this list, or the Clients tab."
        ))
        bubble(self.add_client_button, tr(
            "Add a client without leaving this form. It opens the same window as the Clients tab, "
            "and the new client is selected here."
        ), tr("Add client…"))
        self.description = QLineEdit()
        self.description.setPlaceholderText(tr("Annotation work, week 12"))
        form_row(form, tr("Description"), self.description, tr(
            "What the payment is for. The livre des recettes must state the origin of each receipt."
        ))
        self.method = QComboBox()
        for method in PAYMENT_METHODS:
            self.method.addItem(tr(method), method)
        form_row(form, tr("Method"), self.method, tr(
            "How the money arrived. The livre des recettes must state it."
        ))
        self.reference = QLineEdit()
        self.reference.setPlaceholderText(tr("Provider's reference"))
        form_row(form, tr("Reference"), self.reference, tr(
            "The provider's own reference for this payment. The same reference can't be recorded "
            "twice for a client, which catches duplicates."
        ))
        layout.addWidget(payment)

        amounts = QGroupBox(tr("Amounts"))
        bubble(amounts, tr("Each value is stored separately, so nothing is lost if a rule changes."))
        grid = QFormLayout(amounts)
        grid.setSpacing(6)
        self.gross = QLineEdit()
        self.gross.textChanged.connect(self._update_preview)
        form_row(grid, tr("Gross"), self.gross, tr(
            "The full amount the client paid, before any fee, in the client's currency."
        ))
        self.rate = QLineEdit()
        self.rate.setPlaceholderText(fmt_rate(Decimal("1.0823")))
        self.rate.textChanged.connect(self._update_preview)
        form_row(grid, tr("Rate per 1 EUR"), self.rate, tr(
            "Units of the currency for 1 EUR, as the ECB publishes it. Which rate applies to "
            "turnover: {label}.", label=tr(UNCONFIRMED),
        ))
        self.rate_source = QComboBox()
        for source in RATE_SOURCES:
            self.rate_source.addItem(tr(source), source)
        form_row(grid, tr("Rate source"), self.rate_source, tr(
            "Where this rate comes from. Kept with the entry so the choice can be reviewed later."
        ))
        self.eur_gross = QLineEdit()
        self.eur_gross.setReadOnly(True)
        form_row(grid, tr("EUR gross"), self.eur_gross, tr(
            "Gross divided by the rate. Calculated for you and stored with the entry."
        ))

        fee_row = QHBoxLayout()
        self.fee = QLineEdit("0")
        self.fee.textChanged.connect(self._update_preview)
        self.fee_currency = QComboBox()
        self.fee_currency.addItems(["USD", "EUR"])
        self.fee_currency.setMaximumWidth(70)
        self.fee_currency.currentIndexChanged.connect(self._update_preview)
        fee_row.addWidget(self.fee, 1)
        fee_row.addWidget(self.fee_currency)
        form_row(grid, tr("Provider fee"), fee_row, tr(
            "What Stripe or PayPal kept, and in which currency. Stored separately: by default it "
            "isn't deducted from turnover."
        ))

        net_row = QHBoxLayout()
        self.net = QLineEdit()
        self.net_currency = QComboBox()
        self.net_currency.addItems(["EUR", "USD"])
        self.net_currency.setMaximumWidth(70)
        net_row.addWidget(self.net, 1)
        net_row.addWidget(self.net_currency)
        form_row(grid, tr("Net credited"), net_row, tr(
            "What actually reached your account, and in which currency."
        ))
        self.set_aside = QLineEdit()
        self.set_aside.setReadOnly(True)
        form_row(grid, tr("To set aside"), self.set_aside, tr(
            "Contributions on this payment, at the rate in force on its date. Keep this money "
            "aside for your next declaration."
        ))
        layout.addWidget(amounts)

        self.unconfirmed = dim_label(
            tr("USD rate and fees in turnover: {label}. Each value is kept separately, so the "
               "setting can change later without touching an entry.", label=tr(UNCONFIRMED)),
            tip=tr("The official sources read so far don't settle this. The choice is under Settings: "
                   "the gear icon at the top right."),
        )
        layout.addWidget(self.unconfirmed)

        receipt_row = QHBoxLayout()
        self.receipt_button = QPushButton(tr("Attach receipt…"))
        bubble(self.receipt_button, tr(
            "Optional. Keeps a copy of a file with this entry and queues it for Google Drive."
        ))
        self.receipt_button.clicked.connect(self._choose_receipt)
        receipt_row.addWidget(self.receipt_button)
        self.receipt_label = dim_label("", wrap=False, tip=tr("The file that will be attached."))
        receipt_row.addWidget(self.receipt_label, 1)
        layout.addLayout(receipt_row)

        self.record_button = QPushButton(tr("Record payment"))
        self.record_button.setObjectName("primary")
        self.record_button.clicked.connect(lambda _checked=False: self.record())
        layout.addWidget(self.record_button)
        layout.addWidget(dim_label(
            tr("Entries can't be edited once recorded. A correction is a reversing entry with a reason."),
            tip=tr("The livre des recettes is a record. To correct an entry, use Reverse entry on "
                   "the Payments tab, then record the right one."),
        ))
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
        self.client.view().setMinimumWidth(self.client.view().sizeHintForColumn(0) + 12)
        has_client = self.client.count() > 0
        self.record_button.setEnabled(has_client)
        bubble(self.record_button, tr(
            "Adds this payment to the ledger. It can't be edited afterwards, only reversed."
        ) if has_client else tr("Add a client first, with the + button beside the Client list."))
        self.date.setMaximumDate(to_qdate(clock.today()))
        self._on_client()

    def prefill(self, *, received_on: Any, client_id: int | None, description: str, gross: Decimal,
                fee: Decimal, fee_currency: str, net: Decimal, net_currency: str, reference: str,
                method: str = "Stripe", provider_rate: Decimal | None = None) -> None:
        """Fill the form from a payment read elsewhere. Nothing is recorded: that stays your click.

        The rate follows the turnover setting: the provider's own rate under the provider setting,
        otherwise empty, for the ECB rate of the day as with any payment."""
        if client_id is not None and self.client.findData(client_id) >= 0:
            self.client.setCurrentIndex(self.client.findData(client_id))
        self.date.setDate(to_qdate(received_on))
        self.description.setText(description)
        if self.method.findData(method) >= 0:
            self.method.setCurrentIndex(self.method.findData(method))
        self.reference.setText(reference)
        self.gross.setText(fmt_number(gross))
        for combo, currency in ((self.fee_currency, fee_currency), (self.net_currency, net_currency)):
            if combo.findText(currency) >= 0:
                combo.setCurrentIndex(combo.findText(currency))
        self.fee.setText(fmt_number(fee))
        self.net.setText(fmt_number(net))
        if self.rate.isEnabled():     # not a euro client
            use_provider = self.book.profile().fx_policy == "provider_effective" and provider_rate
            self.rate.setText(fmt_rate(provider_rate) if use_provider else "")
            source = "Provider rate" if use_provider else "ECB reference"
            self.rate_source.setCurrentIndex(max(0, self.rate_source.findData(source)))
        self._update_preview()

    def add_client(self) -> None:
        """What is already typed in the form stays, so a payment can carry on from here."""
        client = ask_for_new_client(self.book, self)
        if client is None:
            return
        self.reload()
        index = self.client.findData(client["id"])
        if index >= 0:     # an inactive client isn't offered here
            self.client.setCurrentIndex(index)
        self.status.emit(tr("Client {name} added.", name=client["name"]))
        self.client_added.emit()

    def _currency(self) -> str:
        client_id = self.client.currentData()
        client = self.book.clients.get(client_id) if client_id is not None else None
        return client["currency"] if client else "USD"

    def _on_client(self, *_args: Any) -> None:
        currency = self._currency()
        self.gross.setPlaceholderText(f"{fmt_number(0)} {currency}")
        if currency == "EUR":
            self.rate.setText("1")
        elif not self.rate.isEnabled():
            # Leaving a euro client. That 1 was filled in here, and would pass for a real rate.
            self.rate.clear()
        self.rate.setEnabled(currency != "EUR")
        self.fee_currency.setItemText(0, currency if currency != "EUR" else "EUR")
        self._update_preview()

    def _update_preview(self, *_args: Any) -> None:
        self.net.setPlaceholderText(fmt_number(0))
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
        self.net.setPlaceholderText(fmt_number(eur - fee_eur))
        self._update_set_aside(eur, fee_eur)

    def _update_set_aside(self, eur: Decimal, fee_eur: Decimal) -> None:
        from ...core.limits import contribution_rate

        profile = self.book.profile()
        base = eur - fee_eur if profile.turnover_basis == "net_of_fees" else eur
        try:
            info = contribution_rate(from_qdate(self.date.date()), profile, self.book.figures)
        except MissingFigure:  # reported on the Limits tab
            self.set_aside.clear()
            return
        self.set_aside.setText(f"{fmt_money(round_money(base * info.rate))}  ({fmt_percent(info.rate)})")

    def _choose_receipt(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, tr("Attach a receipt"))
        if path:
            self.set_receipt(path)

    def set_receipt(self, path: str) -> None:
        self._receipt = path
        self.receipt_label.setText(path.replace("\\", "/").rsplit("/", 1)[-1])

    # -- recording ----------------------------------------------------------
    def _confirm(self, summary: str) -> bool:
        reply = QMessageBox.question(
            self, tr("Record this payment?"),
            tr("{summary}\n\nThis can't be edited afterwards. A correction is a reversing entry.",
               summary=summary),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def record(self) -> int | None:
        client_id = self.client.currentData()
        if client_id is None:
            QMessageBox.information(self, tr("No client"),
                                    tr("Add a client first, with the + button beside the Client list."))
            return None
        received_on = from_qdate(self.date.date())
        summary = tr(
            "{date}  ·  {client}\n{description}\nGross {gross} {currency}, rate {rate}, EUR gross "
            "{eur}\nFee {fee} {fee_currency}, net {net} {net_currency}",
            date=self.date.text(), client=self.client.currentText(),
            description=self.description.text().strip(),
            gross=self.gross.text().strip() or "?", currency=self._currency(),
            rate=self.rate.text().strip() or "?", eur=self.eur_gross.text() or "?",
            fee=self.fee.text().strip() or "0", fee_currency=self.fee_currency.currentText(),
            net=self.net.text().strip() or "?", net_currency=self.net_currency.currentText(),
        )
        if not self._confirm(summary):
            return None
        seq = guarded(self, tr("Payment not recorded"), lambda: self.book.ledger.record_payment(
            received_on=received_on,
            client_id=client_id,
            description=self.description.text(),
            amount_gross=self.gross.text(),
            fx_rate=self.rate.text(),
            fx_source=self.rate_source.currentData(),
            fee_amount=self.fee.text(),
            fee_currency=self.fee_currency.currentText(),
            net_credited=self.net.text(),
            net_currency=self.net_currency.currentText(),
            payment_method=self.method.currentData(),
            provider_ref=self.reference.text(),
        ))
        if seq is None:
            return None
        if self._receipt:
            # The payment is already recorded, so a bad receipt path must not read as a failure.
            guarded(self, tr("Receipt not attached"), lambda: self.book.attach_receipt(seq, self._receipt))
        entry = self.book.ledger.get(seq)
        try:
            amount = self.book.limits.set_aside_for(entry, self.book.profile())
            self.status.emit(tr("Entry {seq} recorded. Set aside {amount} for this payment.",
                                seq=seq, amount=fmt_money(amount)))
        except MissingFigure as exc:
            self.status.emit(tr("Entry {seq} recorded. {problem}", seq=seq, problem=exc))
        self._clear()
        self.recorded.emit(seq)
        return seq

    def _clear(self) -> None:
        for field in (self.description, self.gross, self.net, self.reference):
            field.clear()
        self.fee.setText("0")
        self._receipt = ""
        self.receipt_label.clear()
