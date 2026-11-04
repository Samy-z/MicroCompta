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
from ..models import Col
from ..widgets.table_view import DataTable
from .common import Banner, dim_label, from_qdate, guarded, heading, make_date_edit

LIST_COLUMNS = [
    Col("number", "Number", width=110),
    Col("kind_label", "Type", width=70),
    Col("status", "Status", "status", 64),
    Col("issue_date", "Issued", "date", 84),
    Col("client_name", "Client", width=170),
    Col("service_start", "Service from", "date", 88),
    Col("service_end", "To", "date", 84),
    Col("total", "Total", "money", 92, currency_key="currency"),
    Col("fx_rate", "Rate", "rate", 62),
    Col("total_eur", "EUR value", "eur", 92),
    Col("link", "Credit note", width=120),
]
LINE_COLUMNS = [
    Col("position", "#", "int", 34),
    Col("description", "Description", width=320),
    Col("payment_date", "Paid on", "date", 88),
    Col("quantity", "Quantity", "qty", 70),
    Col("unit_price", "Unit price", "money", 90, currency_key="currency"),
    Col("total", "Total", "money", 90, currency_key="currency"),
    Col("ledger_seq", "Ledger entry", "int", 80),
]


class EditDraftDialog(QDialog):
    """Service dates, notes, and each line's description, quantity and price."""

    def __init__(self, book: Book, invoice_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book
        self.invoice_id = invoice_id
        invoice = book.invoices.get(invoice_id)
        self.lines = book.invoices.lines(invoice_id)
        self.setWindowTitle("Edit draft")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.start = make_date_edit(invoice["service_start"])
        self.end = make_date_edit(invoice["service_end"])
        self.notes = QLineEdit(invoice["notes"] or "")
        form.addRow("Service from", self.start)
        form.addRow("Service to", self.end)
        form.addRow("Note on the invoice", self.notes)
        layout.addLayout(form)
        layout.addWidget(dim_label(
            "Quantity 1 at the paid amount by default. Use hours and an hourly rate if you prefer: "
            "you'll be warned if a line stops matching its payment."
        ))

        self.table = QTableWidget(len(self.lines), 3)
        self.table.setHorizontalHeaderLabels(["Description", "Quantity", "Unit price HT"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, line in enumerate(self.lines):
            self.table.setItem(row, 0, QTableWidgetItem(line["description"]))
            quantity = f"{Decimal(line['quantity']):f}".rstrip("0").rstrip(".")
            self.table.setItem(row, 1, QTableWidgetItem(quantity))
            self.table.setItem(row, 2, QTableWidgetItem(f"{Decimal(line['unit_price']):.2f}"))
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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

        if guarded(self, "Draft not saved", apply):
            self.accept()


class IssueDialog(QDialog):
    """Last step before a number is taken for good."""

    def __init__(self, book: Book, invoice: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Issue final invoice")
        self.resize(480, 0)
        self.currency = invoice["currency"]
        self.total = sum((Decimal(l["total"]) for l in book.invoices.lines(invoice["id"])), Decimal(0))

        layout = QVBoxLayout(self)
        layout.addWidget(heading(f"{invoice['client_name']}  ·  {fmt_money(self.total, self.currency)}", "h2"))
        form = QFormLayout()
        today = clock.today()
        self.issue_date = make_date_edit(today)
        form.addRow("Issue date", self.issue_date)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("1.0823")
        self.rate.setToolTip(f"{self.currency} for 1 EUR on the ECB's reference rate.")
        self.rate.textChanged.connect(self._update_value)
        self.rate_date = make_date_edit(today)
        self.euro_value = QLineEdit(readOnly=True)
        if self.currency != "EUR":
            form.addRow(f"ECB rate ({self.currency} per 1 EUR)", self.rate)
            form.addRow("Rate published on", self.rate_date)
            form.addRow("Euro value printed", self.euro_value)
        layout.addLayout(form)
        if self.currency != "EUR":
            layout.addWidget(dim_label(
                "economie.gouv.fr: the invoice shows the amount, its euro counter-value and the rate "
                "applied, using the ECB's rate of the day. No rate is published at weekends, so "
                "use the last one and its date. The app has no network access to look this up."
            ))
        warnings = book.invoices.issue_warnings(invoice["id"])
        try:
            vat = book.limits.report(today.year).vat
            if vat.level == "over":
                warnings.append(vat.headline)
        except MissingFigure as exc:
            warnings.append(str(exc))
        if warnings:
            layout.addWidget(Banner("warn", "\n".join(warnings)))
        layout.addWidget(dim_label(
            "Once issued this can't change or be deleted, and it takes the next number. "
            "A correction is a credit note."
        ))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        issue = QPushButton("Issue invoice")
        issue.setObjectName("primary")
        buttons.addButton(issue, QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_value(self, *_args: Any) -> None:
        try:
            rate = to_decimal(self.rate.text())
            self.euro_value.setText(fmt_money(round_money(self.total / rate)) if rate > 0 else "")
        except Exception:  # noqa: BLE001 - half-typed input
            self.euro_value.clear()


class CreditDialog(QDialog):
    def __init__(self, number: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Credit note for {number}")
        form = QFormLayout(self)
        form.addRow(dim_label("This cancels the whole invoice, at its original exchange rate. "
                              "Its payments can then be invoiced again."))
        self.reason = QLineEdit()
        form.addRow("Reason", self.reason)
        self.issue_date = make_date_edit(clock.today())
        form.addRow("Issue date", self.issue_date)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class InvoicesPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(heading("Invoices"))
        top.addStretch(1)
        top.addWidget(QLabel("New monthly draft:"))
        self.client = QComboBox()
        self.client.setMinimumWidth(170)
        self.client.currentIndexChanged.connect(self._fill_months)
        top.addWidget(self.client)
        self.month = QComboBox()
        self.month.setMinimumWidth(170)
        top.addWidget(self.month)
        self.draft_button = QPushButton("Create draft")
        self.draft_button.setObjectName("primary")
        self.draft_button.clicked.connect(lambda _c=False: self.create_draft())
        top.addWidget(self.draft_button)
        layout.addLayout(top)

        self.alert = Banner("bad")
        layout.addWidget(self.alert)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = DataTable(LIST_COLUMNS, key="id")
        self.edit_button = self.table.add_button("Edit…", self.edit_selected)
        self.preview_button = self.table.add_button("Preview", self.preview_selected)
        self.delete_button = self.table.add_button("Delete draft", self.delete_selected, danger=True)
        self.issue_button = self.table.add_button("Issue…", self.issue_selected, primary=True)
        self.open_button = self.table.add_button("Open PDF", self.open_selected)
        self.credit_button = self.table.add_button("Credit note…", self.credit_selected, danger=True)
        self.table.row_selected.connect(self._on_selected)
        splitter.addWidget(self.table)

        lower = QWidget()
        lower_lay = QVBoxLayout(lower)
        lower_lay.setContentsMargins(0, 4, 0, 0)
        lower_lay.setSpacing(5)
        lower_lay.addWidget(heading("Lines", "h2"))
        self.lines = DataTable(LINE_COLUMNS, toolbar=False)
        lower_lay.addWidget(self.lines, 1)
        self.value_note = dim_label("")
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
            row["kind_label"] = "Credit note" if row["kind"] == "credit_note" else "Invoice"
            if row["credits_number"]:
                row["link"] = f"Cancels {row['credits_number']}"
            elif row["credited_by"]:
                row["link"] = f"Cancelled by {row['credited_by']}"
                row["_dim"] = True
            else:
                row["link"] = ""
            rows.append(row)
        self.table.set_rows(rows)
        self._on_selected(self.table.current_row())

        stale = self.book.invoices.stale()
        self.alert.show_text(
            "A payment on these invoices was reversed, so each needs a credit note: "
            + ", ".join(s["number"] for s in stale) + "." if stale else ""
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
                    f"{year}-{month:02d}  ({len(payments)}, {fmt_money(total, currency)})", (year, month)
                )
        self.draft_button.setEnabled(self.month.count() > 0)
        if self.month.count() == 0:
            self.month.addItem("Nothing left to invoice", None)

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
        return (
            f"On the invoice: {fmt_money(row['total_eur'])}, at the ECB rate on the issue date. In the "
            f"ledger: {fmt_money(total)}, at each payment's rate. Turnover uses the ledger."
        )

    # -- actions ------------------------------------------------------------
    def create_draft(self) -> int | None:
        client_id = self.client.currentData()
        period = self.month.currentData()
        if client_id is None or period is None:
            return None
        invoice_id = guarded(self, "No draft created", lambda: self.book.invoices.create_monthly_draft(
            client_id, period[0], period[1]
        ))
        if invoice_id is not None:
            self.status.emit("Draft created. Check it, then issue it when you have a SIREN.")
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
        path = guarded(self, "Preview failed", lambda: self.book.invoices.preview(row["id"], target))
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def delete_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        reply = QMessageBox.question(self, "Delete draft?", "Its payments can then be drafted again.")
        if reply == QMessageBox.Yes and guarded(
            self, "Not deleted", lambda: self.book.invoices.delete_draft(row["id"]) or True
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
        number = guarded(self, "Invoice not issued", lambda: self.book.invoices.issue(
            invoice_id, issue_date, fx_rate=fx_rate, fx_rate_date=fx_rate_date,
        ))
        if number is not None:
            self.status.emit(f"{number} issued, saved and queued for Drive.")
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
        number = guarded(self, "No credit note issued", lambda: self.book.invoices.credit_note(
            row["id"], dialog.reason.text(), from_qdate(dialog.issue_date.date())
        ))
        if number is not None:
            self.status.emit(f"{number} issued, cancelling {row['number']}.")
            self.changed.emit()
