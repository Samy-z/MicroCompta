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
from ...core.ledger_policy import BASIS_LABELS, FEE_POINTER, FX_LABELS, UNCONFIRMED
from ...core.money import fmt_money
from ..models import Col
from ..widgets.table_view import DataTable
from .common import (
    Banner, StatRow, fill_years, from_qdate, guarded, heading, make_date_edit, year_combo,
)

COLUMNS = [
    Col("seq", "N°", "int", 44),
    Col("received_on", "Received", "date", 84),
    Col("client_name", "Client (origin)", width=125),
    Col("description", "Description", width=150),
    Col("amount_gross", "Gross", "money", 76, currency_key="currency"),
    Col("fx_rate", "Rate", "rate", 56, tip="Units of the currency for 1 EUR"),
    Col("eur_gross", "EUR gross", "eur", 76),
    Col("fee_amount", "Fee", "money", 58, currency_key="fee_currency"),
    Col("net_credited", "Net credited", "money", 78, currency_key="net_currency"),
    Col("counted", "Counted", "eur", 76, tip="What this entry adds to turnover under the current setting"),
    Col("set_aside", "Set aside", "eur", 66),
    Col("payment_method", "Method", width=54),
    Col("provider_ref", "Reference", width=80),
    Col("linked_invoice", "Invoice", width=92),
    Col("receipts", "Receipts", "int", 54),
    Col("note", "Note", width=180),
]


class ReverseDialog(QDialog):
    def __init__(self, entry: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Reverse entry {entry['seq']}")
        form = QFormLayout(self)
        form.addRow(heading(f"{entry['received_on']}  ·  {entry['client_name']}", "h2"))
        form.addRow(
            "Amount", QLineEdit(f"{entry['amount_gross']} {entry['currency']} "
                                f"({fmt_money(entry['eur_gross'])})", readOnly=True)
        )
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why this entry is being cancelled")
        form.addRow("Reason", self.reason)
        self.on = make_date_edit(entry["received_on"])
        self.on.setToolTip(
            "Keep the original date to fix a mistake: it cancels in the same period. "
            "Use the real date for a refund."
        )
        form.addRow("Reversal date", self.on)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


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
        top.addWidget(heading("Payments ledger"))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        self.policy_banner = Banner("warn")
        top.addWidget(self.policy_banner, 1)
        layout.addLayout(top)

        self.totals = StatRow([
            ("q1", "T1 total", ""), ("q2", "T2 total", ""), ("q3", "T3 total", ""),
            ("q4", "T4 total", ""), ("year", "Year total", "Turnover under the current setting."),
            ("gross", "EUR gross", "Before fees, at each entry's rate."),
            ("fees", "Provider fees", "In euros."),
            ("set_aside", "Set aside", "Contributions on the year's turnover."),
        ])
        layout.addWidget(self.totals)

        self.table = DataTable(COLUMNS, key="seq")
        self.reverse_button = self.table.add_button(
            "Reverse entry…", self.reverse_selected, danger=True,
            tip="Entries can't be edited. This adds a reversing entry with a reason.",
        )
        self.attach_button = self.table.add_button("Attach receipt…", self.attach_receipt)
        self.table.add_button("Export CSV", self.export_csv)
        self.table.add_button("Export PDF", self.export_pdf)
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

        self.policy_banner.show_text(
            f"Turnover counted: {BASIS_LABELS[policy.basis]} · {FX_LABELS[policy.fx]}. "
            f"USD rate and fees: {UNCONFIRMED}. {FEE_POINTER}"
        )

        from ...core.errors import MissingFigure
        from ...core.ledger_policy import counted_eur

        rows = []
        for entry in self.book.ledger.entries(current):
            row = dict(entry)
            row["counted"] = counted_eur(entry, policy)
            try:
                row["set_aside"] = self.book.limits.set_aside_for(entry, profile)
            except MissingFigure:
                row["set_aside"] = None
            if entry["kind"] == "reversal":
                row["note"] = f"Reverses entry {entry['reverses_seq']}: {entry['reason']}"
                row["_dim"] = True
            elif entry["is_reversed"]:
                row["note"] = "Reversed"
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
        new_seq = guarded(self, "Not reversed", lambda: self.book.ledger.reverse(seq, reason, on))
        if new_seq is not None:
            self.status.emit(f"Entry {seq} reversed by entry {new_seq}.")
            self.changed.emit()
        return new_seq

    def attach_receipt(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Attach a receipt to entry {row['seq']}")
        if path and guarded(self, "Receipt not attached",
                            lambda: self.book.attach_receipt(int(row["seq"]), path)) is not None:
            self.status.emit(f"Receipt attached to entry {row['seq']} and queued for Drive.")
            self.changed.emit()

    def export_csv(self, ask: bool = True) -> int | None:
        return self._export("CSV", lambda: self.book.exports.ledger_csv(self._selected_year()), ask)

    def export_pdf(self, ask: bool = True) -> int | None:
        return self._export("PDF", lambda: self.book.exports.ledger_pdf(self._selected_year()), ask)

    def _export(self, label: str, action: Any, ask: bool) -> int | None:
        doc_id = guarded(self, "Export failed", action)
        if doc_id is None:
            return None
        doc = self.book.documents.get(doc_id)
        path = self.book.documents.path_of(doc)
        self.status.emit(f"{label} export saved and queued for Drive: {doc['rel_path']}")
        self.changed.emit()
        if ask:
            box = QMessageBox(self)
            box.setWindowTitle("Export saved")
            box.setText(f"Saved to:\n{path}\n\nAlso queued for Google Drive.")
            open_button = box.addButton("Open folder", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is open_button:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        return doc_id
