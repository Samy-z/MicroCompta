"""Invoices: draft from a month's payments, preview, issue, credit."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.money import fmt_money, round_money, to_decimal
from ...i18n import fmt_number, fmt_rate, tr
from ..models import Col, wrap_tip
from ..widgets.table_view import DataTable
from .common import (
    FittedDialog,
    Banner, bubble, button_box, dim_label, form_row, from_qdate, guarded, heading, make_date_edit,
)


def _list_columns() -> list[Col]:
    return [
        Col("number", tr("Number"), width=110, tip=tr("Unbroken across all documents and years. A draft has none yet.")),
        Col("kind_label", tr("Type"), width=74, tip=tr("An invoice, or a credit note cancelling one.")),
        Col("status", tr("Status"), "status", 70, tip=tr("A draft can change. Once issued, it can't.")),
        Col("issue_date", tr("Issued"), "date", 84, tip=tr("The date printed on the document.")),
        Col("client_name", tr("Client"), width=170, tip=tr("Who it is for. An issued document keeps the details it was issued with.")),
        Col("service_start", tr("Service from"), "date", 96, tip=tr("First day of the service covered.")),
        Col("service_end", tr("To"), "date", 84, tip=tr("Last day of the service covered.")),
        Col("total", tr("Total"), "money", 92, currency_key="currency", tip=tr("The total, in the invoice's currency.")),
        Col("fx_rate", tr("Rate"), "rate", 62, tip=tr("The ECB reference rate printed on the invoice: units of the currency for 1 EUR.")),
        Col("total_eur", tr("EUR value"), "eur", 92, tip=tr("The euro counter-value printed on the invoice.")),
        Col("link", tr("Credit note"), width=120, tip=tr("The credit note that cancels this invoice, or the invoice this one cancels.")),
    ]


def _line_columns() -> list[Col]:
    return [
        Col("position", "#", "int", 34, tip=tr("Line number on the invoice.")),
        Col("description", tr("Description"), width=320, tip=tr("What the line says on the invoice.")),
        Col("payment_date", tr("Paid on"), "date", 88, tip=tr("The date this payment was received.")),
        Col("quantity", tr("Quantity"), "qty", 70, tip=tr("1 by default. Hours work too: use Edit on a draft.")),
        Col("unit_price", tr("Unit price"), "money", 90, currency_key="currency", tip=tr("Price per unit, excluding tax.")),
        Col("total", tr("Total"), "money", 90, currency_key="currency", tip=tr("Quantity times unit price.")),
        Col("ledger_seq", tr("Ledger entry"), "int", 80, tip=tr("The payment this line comes from, on the Payments tab.")),
    ]


class EditDraftDialog(FittedDialog):
    """Service dates, notes, and each line's description, quantity and price."""

    def __init__(self, book: Book, invoice_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book
        self.invoice_id = invoice_id
        invoice = book.invoices.get(invoice_id)
        self.lines = book.invoices.lines(invoice_id)
        self.setWindowTitle(tr("Edit draft"))
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.start = make_date_edit(invoice["service_start"])
        self.end = make_date_edit(invoice["service_end"])
        self.notes = QLineEdit(invoice["notes"] or "")
        form_row(form, tr("Service from"), self.start, tr("First day of the service covered, printed on the invoice."))
        form_row(form, tr("Service to"), self.end, tr("Last day of the service covered, printed on the invoice."))
        form_row(form, tr("Note on the invoice"), self.notes, tr("Optional free text, printed on the invoice."))
        layout.addLayout(form)
        layout.addWidget(dim_label(
            tr("Quantity 1 at the paid amount by default. Use hours and an hourly rate if you "
               "prefer: you'll be warned if a line stops matching its payment."),
            tip=tr("The invoice is a summary of what was paid, so each line should add up to its payment."),
        ))

        self.table = QTableWidget(len(self.lines), 3)
        headers = [
            (tr("Description"), tr("What the line says on the invoice.")),
            (tr("Quantity"), tr("1 by default. Hours work too.")),
            (tr("Unit price HT"), tr("Price per unit, excluding tax.")),
        ]
        for column, (title, tip) in enumerate(headers):
            item = QTableWidgetItem(title)
            item.setToolTip(wrap_tip(tip))
            self.table.setHorizontalHeaderItem(column, item)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, line in enumerate(self.lines):
            self.table.setItem(row, 0, QTableWidgetItem(line["description"]))
            quantity = f"{Decimal(line['quantity']):f}".rstrip("0").rstrip(".")
            self.table.setItem(row, 1, QTableWidgetItem(quantity))
            self.table.setItem(row, 2, QTableWidgetItem(f"{Decimal(line['unit_price']):.2f}"))
        bubble(self.table, tr("Double-click a cell to change it."), tr("Invoice lines"))
        layout.addWidget(self.table, 1)

        layout.addWidget(button_box(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self._save, self.reject))

    def _save(self) -> None:
        new_lines = []
        for row, line in enumerate(self.lines):
            new_lines.append({
                "description": self.table.item(row, 0).text(),
                "quantity": self.table.item(row, 1).text(),
                "unit_price": self.table.item(row, 2).text(),
                "ledger_seq": line["ledger_seq"],
                "payment_date": line["payment_date"],
            })

        def apply() -> bool:
            self.book.invoices.set_lines(self.invoice_id, new_lines)
            self.book.invoices.update_draft(
                self.invoice_id, service_start=from_qdate(self.start.date()),
                service_end=from_qdate(self.end.date()), notes=self.notes.text(),
            )
            return True

        if guarded(self, tr("Draft not saved"), apply):
            self.accept()


class IssueDialog(FittedDialog):
    """Last step before a number is taken for good."""

    def __init__(self, book: Book, invoice: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Issue final invoice"))
        self.resize(480, 0)
        self.currency = invoice["currency"]
        self.total = sum((Decimal(l["total"]) for l in book.invoices.lines(invoice["id"])), Decimal(0))

        layout = QVBoxLayout(self)
        layout.addWidget(heading(
            f"{invoice['client_name']}  ·  {fmt_money(self.total, self.currency)}",
            tr("The client and the total of this invoice."), "h2",
        ))
        form = QFormLayout()
        today = clock.today()
        self.issue_date = make_date_edit(today)
        form_row(form, tr("Issue date"), self.issue_date, tr(
            "The date printed on the invoice. It can't be earlier than the last document issued."
        ))
        self.rate = QLineEdit()
        self.rate.setPlaceholderText(fmt_rate(Decimal("1.0823")))
        self.rate.textChanged.connect(self._update_value)
        self.rate_date = make_date_edit(today)
        self.euro_value = QLineEdit()
        self.euro_value.setReadOnly(True)
        if self.currency != "EUR":
            form_row(form, tr("ECB rate ({currency} per 1 EUR)", currency=self.currency), self.rate, tr(
                "The ECB's reference rate for the issue date, from its website. Printed on the invoice."
            ))
            form_row(form, tr("Rate published on"), self.rate_date, tr(
                "The date of that rate. The ECB publishes nothing at weekends: use the last rate "
                "and its date."
            ))
            form_row(form, tr("Euro value printed"), self.euro_value, tr(
                "The total divided by the rate. Printed on the invoice as its counter-value."
            ))
        layout.addLayout(form)
        if self.currency != "EUR":
            layout.addWidget(dim_label(
                tr("economie.gouv.fr: the invoice shows the amount, its euro counter-value and the "
                   "rate applied, using the ECB's rate of the day. No rate is published at weekends, "
                   "so use the last one and its date. The app has no network access to look this up."),
                tip=tr("Page \"Comment facturer dans une monnaie étrangère ?\" on economie.gouv.fr."),
            ))
        warnings = book.invoices.issue_warnings(invoice["id"])
        try:
            vat = book.limits.report(today.year).vat
            if vat.level == "over":
                warnings.append(vat.headline)
        except MissingFigure as exc:
            warnings.append(str(exc))
        if warnings:
            layout.addWidget(Banner("warn", "\n".join(warnings), tip=tr(
                "Worth a second look. These don't stop the invoice being issued."
            )))
        layout.addWidget(dim_label(
            tr("Once issued this can't change or be deleted, and it takes the next number. A "
               "correction is a credit note."),
            tip=tr("French invoices need an unbroken chronological numbering."),
        ))
        buttons = button_box(QDialogButtonBox.Cancel, self.accept, self.reject)
        issue = QPushButton(tr("Issue invoice"))
        issue.setObjectName("primary")
        bubble(issue, tr("Takes the next number, freezes the invoice, saves the PDF and queues it for Drive."))
        buttons.addButton(issue, QDialogButtonBox.AcceptRole)
        layout.addWidget(buttons)

    def _update_value(self, *_args: Any) -> None:
        try:
            rate = to_decimal(self.rate.text())
            self.euro_value.setText(fmt_money(round_money(self.total / rate)) if rate > 0 else "")
        except Exception:  # noqa: BLE001 - half-typed input
            self.euro_value.clear()


class CreditDialog(FittedDialog):
    def __init__(self, number: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Credit note for {number}", number=number))
        form = QFormLayout(self)
        form.addRow(dim_label(
            tr("This cancels the whole invoice, at its original exchange rate. Its payments can then "
               "be invoiced again."),
            tip=tr("An issued invoice can't change, so a credit note is how it gets corrected."),
        ))
        self.reason = QLineEdit()
        form_row(form, tr("Reason"), self.reason, tr("Required. Printed on the credit note."))
        self.issue_date = make_date_edit(clock.today())
        form_row(form, tr("Issue date"), self.issue_date, tr(
            "The date printed on the credit note. It can't be earlier than the last document issued."
        ))
        form.addRow(button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self.accept, self.reject))


class InvoicesPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(heading(tr("Invoices"), tr(
            "Monthly summary invoices drafted from the payments received. Issued documents can't change."
        )))
        top.addStretch(1)
        new_label = QLabel(tr("New monthly draft:"))
        bubble(new_label, tr("Pick a client and a month, then create a draft from that month's payments."))
        top.addWidget(new_label)
        self.client = QComboBox()
        self.client.setMinimumWidth(170)
        self.client.currentIndexChanged.connect(self._fill_months)
        bubble(self.client, tr("The client to invoice."), tr("Client"))
        top.addWidget(self.client)
        self.month = QComboBox()
        self.month.setMinimumWidth(170)
        bubble(self.month, tr("Months with payments not yet on an invoice, with how many and their total."), tr("Month"))
        top.addWidget(self.month)
        self.draft_button = QPushButton(tr("Create draft"))
        self.draft_button.setObjectName("primary")
        bubble(self.draft_button, tr("Makes a draft with one line per payment. A draft can be changed or deleted."))
        self.draft_button.clicked.connect(lambda _c=False: self.create_draft())
        top.addWidget(self.draft_button)
        layout.addLayout(top)

        self.alert = Banner("bad", tip=tr(
            "A payment on an issued invoice was reversed, so the invoice no longer matches the ledger."
        ))
        layout.addWidget(self.alert)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = DataTable(_list_columns(), key="id")
        self.edit_button = self.table.add_button(tr("Edit…"), self.edit_selected, tip=tr(
            "Change a draft's dates, note and lines."
        ))
        self.preview_button = self.table.add_button(tr("Preview"), self.preview_selected, tip=tr(
            "Opens the draft as a PDF marked BROUILLON. Works without a SIREN."
        ))
        self.delete_button = self.table.add_button(tr("Delete draft"), self.delete_selected, danger=True, tip=tr(
            "Removes the draft. Its payments can be drafted again. Issued documents can't be deleted."
        ))
        self.issue_button = self.table.add_button(tr("Issue…"), self.issue_selected, primary=True, tip=tr(
            "Makes the draft final, with the next number. Needs a valid SIREN and the ECB rate."
        ))
        self.open_button = self.table.add_button(tr("Open PDF"), self.open_selected, tip=tr(
            "Opens the issued document."
        ))
        self.credit_button = self.table.add_button(tr("Credit note…"), self.credit_selected, danger=True, tip=tr(
            "Cancels the whole issued invoice with a new document, and frees its payments."
        ))
        self.table.row_selected.connect(self._on_selected)
        splitter.addWidget(self.table)

        lower = QWidget()
        lower_lay = QVBoxLayout(lower)
        lower_lay.setContentsMargins(0, 4, 0, 0)
        lower_lay.setSpacing(5)
        lower_lay.addWidget(heading(tr("Lines"), tr("The lines of the selected invoice."), "h2"))
        self.lines = DataTable(_line_columns(), toolbar=False)
        lower_lay.addWidget(self.lines, 1)
        self.value_note = dim_label("", tip=tr(
            "An invoice's euro value uses the ECB rate on its issue date. Turnover uses each "
            "payment's own rate on the date received, so the two can differ."
        ))
        lower_lay.addWidget(self.value_note)
        splitter.addWidget(lower)
        splitter.setSizes([360, 260])
        layout.addWidget(splitter, 1)
        self._on_selected(None)

    # -- state --------------------------------------------------------------
    def reload(self) -> None:
        keep = self.client.currentData()
        self.client.blockSignals(True)
        self.client.clear()
        for client in self.book.clients.list():
            self.client.addItem(client["name"], client["id"])
        index = self.client.findData(keep)
        if index >= 0:
            self.client.setCurrentIndex(index)
        self.client.blockSignals(False)
        self._fill_months()

        rows = []
        for row in self.book.invoices.list():
            row = dict(row)
            row["kind_label"] = tr("Credit note") if row["kind"] == "credit_note" else tr("Invoice")
            if row["credits_number"]:
                row["link"] = tr("Cancels {number}", number=row["credits_number"])
            elif row["credited_by"]:
                row["link"] = tr("Cancelled by {number}", number=row["credited_by"])
                row["_dim"] = True
            else:
                row["link"] = ""
            rows.append(row)
        self.table.set_rows(rows)
        self._on_selected(self.table.current_row())

        stale = self.book.invoices.stale()
        self.alert.show_text(
            tr("A payment on these invoices was reversed, so each needs a credit note: {numbers}.",
               numbers=", ".join(s["number"] for s in stale)) if stale else ""
        )

    def _fill_months(self, *_args: Any) -> None:
        client_id = self.client.currentData()
        self.month.clear()
        if client_id is None:
            self.draft_button.setEnabled(False)
            return
        found: dict[tuple[int, int], tuple[int, Decimal]] = {}
        for entry in self.book.ledger.entries():
            if entry["client_id"] != client_id or entry["kind"] != "payment" or entry["is_reversed"]:
                continue
            key = (entry["received_on"].year, entry["received_on"].month)
            found.setdefault(key, (0, Decimal(0)))
        for (year, month) in sorted(found, reverse=True):
            payments = self.book.invoices.uninvoiced_payments(client_id, year, month)
            if payments:
                total = sum((Decimal(p["amount_gross"]) for p in payments), Decimal(0))
                currency = payments[0]["currency"]
                self.month.addItem(
                    f"{year}-{month:02d}  ({fmt_number(len(payments), 0)}, {fmt_money(total, currency)})",
                    (year, month),
                )
        self.draft_button.setEnabled(self.month.count() > 0)
        if self.month.count() == 0:
            self.month.addItem(tr("Nothing left to invoice"), None)

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        is_draft = bool(row and row["status"] == "draft")
        issued = bool(row and row["status"] == "issued")
        self.edit_button.setEnabled(is_draft)
        self.preview_button.setEnabled(is_draft)
        self.delete_button.setEnabled(is_draft)
        self.issue_button.setEnabled(is_draft)
        self.open_button.setEnabled(issued)
        self.credit_button.setEnabled(
            issued and row["kind"] == "invoice" and not row["credited_by"]
        )
        if row is None:
            self.lines.set_rows([])
            self.value_note.setText("")
            return
        lines = [dict(l, currency=row["currency"]) for l in self.book.invoices.lines(row["id"])]
        self.lines.set_rows(lines)
        self.value_note.setText(self._value_note(row, lines))

    def _value_note(self, row: dict[str, Any], lines: list[dict[str, Any]]) -> str:
        """Why the invoice's euro value and the ledger's can differ, with both numbers."""
        if row["status"] != "issued" or row["currency"] == "EUR" or row["kind"] != "invoice":
            return ""
        total = Decimal(0)
        for line in lines:
            if line["ledger_seq"] is not None:
                entry = self.book.ledger.get(int(line["ledger_seq"]))
                if entry:
                    total += Decimal(entry["eur_gross"])
        return tr(
            "On the invoice: {invoice}, at the ECB rate on the issue date. In the ledger: {ledger}, "
            "at each payment's rate. Turnover uses the ledger.",
            invoice=fmt_money(row["total_eur"]), ledger=fmt_money(total),
        )

    # -- actions ------------------------------------------------------------
    def create_draft(self) -> int | None:
        client_id = self.client.currentData()
        period = self.month.currentData()
        if client_id is None or period is None:
            return None
        invoice_id = guarded(self, tr("No draft created"), lambda: self.book.invoices.create_monthly_draft(
            client_id, period[0], period[1]
        ))
        if invoice_id is not None:
            self.status.emit(tr("Draft created. Check it, then issue it when you have a SIREN."))
            self.changed.emit()
            self.table.select_key(invoice_id)
        return invoice_id

    def _selected(self) -> dict[str, Any] | None:
        return self.table.current_row()

    def edit_selected(self) -> None:
        row = self._selected()
        if row and EditDraftDialog(self.book, row["id"], self).exec() == QDialog.Accepted:
            self.changed.emit()
            self.table.select_key(row["id"])

    def preview_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        target = self.book.documents.tmp_dir() / f"apercu_{row['id']}_{clock.now():%H%M%S}.pdf"
        path = guarded(self, tr("Preview failed"), lambda: self.book.invoices.preview(row["id"], target))
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def delete_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        reply = QMessageBox.question(self, tr("Delete draft?"), tr("Its payments can then be drafted again."))
        if reply == QMessageBox.Yes and guarded(
            self, tr("Not deleted"), lambda: self.book.invoices.delete_draft(row["id"]) or True
        ):
            self.changed.emit()

    def issue_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        invoice = self.book.invoices.get(row["id"])
        dialog = IssueDialog(self.book, invoice, self)
        if dialog.exec() != QDialog.Accepted:
            return
        is_euro = invoice["currency"] == "EUR"
        self.issue(
            row["id"], from_qdate(dialog.issue_date.date()),
            None if is_euro else dialog.rate.text(),
            None if is_euro else from_qdate(dialog.rate_date.date()),
        )

    def issue(self, invoice_id: int, issue_date: date, fx_rate: Any = None,
              fx_rate_date: date | None = None) -> str | None:
        number = guarded(self, tr("Invoice not issued"), lambda: self.book.invoices.issue(
            invoice_id, issue_date, fx_rate=fx_rate, fx_rate_date=fx_rate_date,
        ))
        if number is not None:
            self.status.emit(tr("{number} issued, saved and queued for Drive.", number=number))
            self.changed.emit()
            self.table.select_key(invoice_id)
        return number

    def open_selected(self) -> None:
        row = self._selected()
        if row and row["document_id"] is not None:
            doc = self.book.documents.get(int(row["document_id"]))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.book.documents.path_of(doc))))

    def credit_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        dialog = CreditDialog(row["number"], self)
        if dialog.exec() != QDialog.Accepted:
            return
        number = guarded(self, tr("No credit note issued"), lambda: self.book.invoices.credit_note(
            row["id"], dialog.reason.text(), from_qdate(dialog.issue_date.date())
        ))
        if number is not None:
            self.status.emit(tr("{number} issued, cancelling {original}.", number=number, original=row["number"]))
            self.changed.emit()
