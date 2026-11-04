"""The livre des recettes, in the app: read, reverse, attach, export."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.ledger_policy import BASIS_LABELS, FEE_POINTER, FX_LABELS, UNCONFIRMED, counted_eur
from ...core.money import fmt_money
from ...i18n import fmt_date, tr
from ..models import Col, fmt_value
from ..widgets.table_view import DataTable
from .common import (
    Banner, StatRow, bubble, button_box, fill_years, form_row, from_qdate, guarded, heading,
    make_date_edit, year_combo,
)


def _columns() -> list[Col]:
    return [
        Col("seq", tr("N°"), "int", 44, tip=tr("Entry number, in the order recorded. It never changes.")),
        Col("received_on", tr("Received"), "date", 84, tip=tr("The day the money arrived. Turnover counts on this date.")),
        Col("client_name", tr("Client (origin)"), width=125, tip=tr("Who paid, as recorded at the time.")),
        Col("description", tr("Description"), width=150, tip=tr("What the payment was for.")),
        Col("amount_gross", tr("Gross"), "money", 76, currency_key="currency",
            tip=tr("What the client paid, in the client's currency, before any fee.")),
        Col("fx_rate", tr("Rate"), "rate", 56, tip=tr("Units of the currency for 1 EUR, on this entry.")),
        Col("eur_gross", tr("EUR gross"), "eur", 76, tip=tr("Gross divided by the rate.")),
        Col("fee_amount", tr("Fee"), "money", 58, currency_key="fee_currency",
            tip=tr("What the provider kept, in the currency recorded.")),
        Col("net_credited", tr("Net credited"), "money", 88, currency_key="net_currency",
            tip=tr("What reached your account.")),
        Col("counted", tr("Counted"), "eur", 76,
            tip=tr("What this entry adds to turnover under the current setting.")),
        Col("set_aside", tr("Set aside"), "eur", 112,
            tip=tr("Contributions on this payment, at the rate in force on its date.")),
        Col("method_shown", tr("Method"), width=62, tip=tr("How the money arrived.")),
        Col("provider_ref", tr("Reference"), width=80, tip=tr("The provider's own reference.")),
        Col("linked_invoice", tr("Invoice"), width=92,
            tip=tr("The invoice this payment is on, and any credit note that cancelled it.")),
        Col("receipts", tr("Receipts"), "int", 62, tip=tr("How many files are attached to this entry.")),
        Col("note", tr("Note"), width=180, tip=tr("Shows when an entry was reversed, or what a reversal cancels.")),
    ]


class ReverseDialog(QDialog):
    def __init__(self, entry: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Reverse entry {seq}", seq=entry["seq"]))
        form = QFormLayout(self)
        form.addRow(heading(
            f"{fmt_date(entry['received_on'])}  ·  {entry['client_name']}",
            tr("The entry this cancels."), "h2",
        ))
        amount = QLineEdit(
            f"{fmt_value(entry['amount_gross'], 'money', entry['currency'])} "
            f"({fmt_money(entry['eur_gross'])})"
        )
        amount.setReadOnly(True)
        form_row(form, tr("Amount"), amount, tr("The amount that will be cancelled by a negative entry."))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("Why this entry is being cancelled"))
        form_row(form, tr("Reason"), self.reason, tr("Required. It stays with the reversal in the ledger and its exports."))
        self.on = make_date_edit(entry["received_on"])
        form_row(form, tr("Reversal date"), self.on, tr(
            "Keep the original date to fix a mistake: it cancels in the same period. Use the real "
            "date for a refund."
        ))
        form.addRow(button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self.accept, self.reject))


class LedgerPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(heading(tr("Payments ledger"), tr(
            "The livre des recettes: one entry per payment received. Entries can't be edited."
        )))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        self.policy_banner = Banner("warn", tip=tr(
            "How turnover is counted. The choice is in Settings, and each entry keeps every value, "
            "so changing it recomputes without touching an entry."
        ))
        top.addWidget(self.policy_banner, 1)
        layout.addLayout(top)

        self.totals = StatRow([
            ("q1", tr("Q1 total"), tr("Turnover received from January to March.")),
            ("q2", tr("Q2 total"), tr("Turnover received from April to June.")),
            ("q3", tr("Q3 total"), tr("Turnover received from July to September.")),
            ("q4", tr("Q4 total"), tr("Turnover received from October to December.")),
            ("year", tr("Year total"), tr("Turnover for the year, under the current setting.")),
            ("gross", tr("EUR gross"), tr("Everything received, before fees, at each entry's rate.")),
            ("fees", tr("Provider fees"), tr("What the providers kept, in euros.")),
            ("set_aside", tr("Set aside"), tr("Contributions on the year's turnover.")),
        ])
        layout.addWidget(self.totals)

        self.table = DataTable(_columns(), key="seq")
        self.reverse_button = self.table.add_button(
            tr("Reverse entry…"), self.reverse_selected, danger=True,
            tip=tr("Entries can't be edited. This adds a reversing entry with a reason."),
        )
        self.attach_button = self.table.add_button(
            tr("Attach receipt…"), self.attach_receipt,
            tip=tr("Keeps a copy of a file with the selected entry and queues it for Google Drive."),
        )
        self.table.add_button(tr("Export CSV"), self.export_csv, tip=tr(
            "Saves this year's ledger as a spreadsheet file, in French, and queues it for Drive."
        ))
        self.table.add_button(tr("Export PDF"), self.export_pdf, tip=tr(
            "Saves this year's livre des recettes as a PDF, in French, with totals every 3 months, "
            "and queues it for Drive."
        ))
        self.table.row_selected.connect(self._on_selected)
        layout.addWidget(self.table, 1)
        self._on_selected(None)

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        reversible = bool(row and row["kind"] == "payment" and not row["is_reversed"])
        self.reverse_button.setEnabled(reversible)
        self.attach_button.setEnabled(row is not None)

    def _selected_year(self) -> int:
        return self.year.currentData() or clock.today().year

    def reload(self) -> None:
        current = self._selected_year()
        fill_years(self.year, set(self.book.ledger.years()) | {clock.today().year}, current)
        profile = self.book.profile()
        policy = profile.policy

        self.policy_banner.show_text(tr(
            "Turnover counted: {basis} · {rate}. USD rate and fees: {label}. {pointer}",
            basis=tr(BASIS_LABELS[policy.basis]), rate=tr(FX_LABELS[policy.fx]),
            label=tr(UNCONFIRMED), pointer=tr(FEE_POINTER),
        ))

        rows = []
        for entry in self.book.ledger.entries(current):
            row = dict(entry)
            row["counted"] = counted_eur(entry, policy)
            row["method_shown"] = tr(entry["payment_method"])
            try:
                row["set_aside"] = self.book.limits.set_aside_for(entry, profile)
            except MissingFigure:
                row["set_aside"] = None
            if entry["kind"] == "reversal":
                row["note"] = tr("Reverses entry {seq}: {reason}", seq=entry["reverses_seq"], reason=entry["reason"])
                row["_dim"] = True
            elif entry["is_reversed"]:
                row["note"] = tr("Reversed")
                row["_dim"] = True
            else:
                row["note"] = ""
            rows.append(row)
        self.table.set_rows(rows[::-1])  # newest first: new entries are what you came to see

        quarters = self.book.ledger.quarter_totals(current, policy)
        for q in quarters:
            self.totals.set(f"q{q['quarter']}", fmt_money(q["counted"]))
        self.totals.set("year", fmt_money(sum((q["counted"] for q in quarters), Decimal(0))))
        self.totals.set("gross", fmt_money(sum((q["eur_gross"] for q in quarters), Decimal(0))))
        self.totals.set("fees", fmt_money(sum((q["fee_eur"] for q in quarters), Decimal(0))))
        aside = sum((r["set_aside"] for r in rows if r["set_aside"] is not None), Decimal(0))
        self.totals.set("set_aside", fmt_money(aside))

    # -- actions ------------------------------------------------------------
    def reverse_selected(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        dialog = ReverseDialog(row, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.reverse(int(row["seq"]), dialog.reason.text(), from_qdate(dialog.on.date()))

    def reverse(self, seq: int, reason: str, on: date | None = None) -> int | None:
        new_seq = guarded(self, tr("Not reversed"), lambda: self.book.ledger.reverse(seq, reason, on))
        if new_seq is not None:
            self.status.emit(tr("Entry {seq} reversed by entry {new}.", seq=seq, new=new_seq))
            self.changed.emit()
        return new_seq

    def attach_receipt(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        path, _filter = QFileDialog.getOpenFileName(self, tr("Attach a receipt to entry {seq}", seq=row["seq"]))
        if path and guarded(self, tr("Receipt not attached"),
                            lambda: self.book.attach_receipt(int(row["seq"]), path)) is not None:
            self.status.emit(tr("Receipt attached to entry {seq} and queued for Drive.", seq=row["seq"]))
            self.changed.emit()

    def export_csv(self, ask: bool = True) -> int | None:
        return self._export("CSV", lambda: self.book.exports.ledger_csv(self._selected_year()), ask)

    def export_pdf(self, ask: bool = True) -> int | None:
        return self._export("PDF", lambda: self.book.exports.ledger_pdf(self._selected_year()), ask)

    def _export(self, label: str, action: Any, ask: bool) -> int | None:
        doc_id = guarded(self, tr("Export failed"), action)
        if doc_id is None:
            return None
        doc = self.book.documents.get(doc_id)
        path = self.book.documents.path_of(doc)
        self.status.emit(tr("{kind} export saved and queued for Drive: {path}", kind=label, path=doc["rel_path"]))
        self.changed.emit()
        if ask:
            box = QMessageBox(self)
            box.setWindowTitle(tr("Export saved"))
            box.setText(tr("Saved to:\n{path}\n\nAlso queued for Google Drive.", path=path))
            open_button = box.addButton(tr("Open folder"), QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is open_button:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        return doc_id


__all__ = ["LedgerPanel", "ReverseDialog", "bubble"]
