"""The purchases register, in the app: add, copy, reverse, attach, export.

The tab is called Expenses because that is what people look for. The register is its legal
name, so that is what the heading and the documents say.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.money import fmt_money
from ...core.purchases import CATEGORIES, PAYMENT_METHODS
from ...i18n import fmt_date, fmt_number, fmt_percent, tr
from ..models import Col
from ..widgets.table_view import DataTable
from .common import (
    FittedDialog,
    Banner, StatRow, button_box, dim_label, fill_years, form_row, from_qdate, guarded, heading,
    make_date_edit, run_export, year_combo,
)


def _columns() -> list[Col]:
    return [
        Col("seq", tr("N°"), "int", 44, tip=tr("Entry number, in the order recorded. It never changes.")),
        Col("paid_on", tr("Paid on"), "date", 84, tip=tr("The day you paid.")),
        Col("supplier", tr("Supplier"), width=130, tip=tr("Who you paid, as recorded at the time.")),
        Col("description", tr("Description"), width=210, tip=tr("What you bought.")),
        Col("category_shown", tr("Category"), width=170, tip=tr(
            "What kind of expense it is. Fixed assets are counted apart."
        )),
        Col("amount_eur", tr("Amount paid"), "eur", 100, tip=tr("What left your account, in euros, VAT included.")),
        Col("share_shown", tr("Pro share"), width=70, tip=tr("The share used for the activity.")),
        Col("pro_amount", tr("Pro amount"), "eur", 92, tip=tr("The amount paid times the professional share.")),
        Col("method_shown", tr("Method"), width=100, tip=tr("How you paid.")),
        Col("piece_ref", tr("Document ref."), width=110, tip=tr(
            "The number of the invoice or receipt for this purchase."
        )),
        Col("receipts", tr("Receipts"), "int", 84, tip=tr("How many files are attached to this entry.")),
        Col("note", tr("Note"), width=180, tip=tr("Shows when an entry was reversed, or what a reversal cancels.")),
    ]


class PurchaseDialog(FittedDialog):
    """Stays open on a refusal, so nothing typed is lost. ``seq`` holds the new entry."""

    def __init__(self, book: Book, parent: QWidget | None = None,
                 template: dict[str, Any] | None = None):
        super().__init__(parent)
        self.book = book
        self.seq: int | None = None
        self.setWindowTitle(tr("Add a purchase"))
        self.setMinimumWidth(520)
        form = QFormLayout(self)

        self.paid_on = make_date_edit(clock.today())
        form_row(form, tr("Date paid"), self.paid_on, tr(
            "The day you paid. The register is kept in date order."
        ))
        self.supplier = QLineEdit()
        form_row(form, tr("Supplier"), self.supplier, tr("Who you paid, as on the invoice."))
        self.description = QLineEdit()
        form_row(form, tr("Description"), self.description, tr(
            "What you bought. The register must give the detail of each purchase."
        ))
        self.category = QComboBox()
        for key in CATEGORIES:
            self.category.addItem(tr(key), key)
        threshold = fmt_money(book.figures.value("fixed_asset_threshold", clock.today()), decimals=0)
        form_row(form, tr("Category"), self.category, tr(
            "What kind of expense it is. Fixed asset: lasting equipment above {amount} excluding VAT, "
            "such as a computer. Small equipment: at or below that amount. Under the micro regime "
            "this changes nothing you pay; it matters only when comparing with a real regime.",
            amount=threshold,
        ))
        self.amount = QLineEdit()
        form_row(form, tr("Amount paid (EUR)"), self.amount, tr(
            "What left your account, in euros, VAT included: in the VAT franchise, you can't recover "
            "the VAT on what you buy. For a bill in dollars, enter what your bank debited."
        ))
        self.share = QSpinBox()
        self.share.setRange(1, 100)
        self.share.setValue(100)
        self.share.setSuffix(" %")
        form_row(form, tr("Professional share"), self.share, tr(
            "100% if it only serves the activity. Less for mixed use, such as a travel pass: your "
            "honest estimate of the share used for work."
        ))
        self.method = QComboBox()
        for key in PAYMENT_METHODS:
            self.method.addItem(tr(key), key)
        form_row(form, tr("Payment method"), self.method, tr("How you paid. The register states it."))
        self.reference = QLineEdit()
        form_row(form, tr("Document ref."), self.reference, tr(
            "The number of the invoice or receipt, so the entry can be matched to its supporting "
            "document. Attach the file itself afterwards."
        ))
        form.addRow(dim_label(
            tr("This can't be edited afterwards. A correction is a reversing entry."),
            tip=tr("A record stays true to the day it was made."),
        ))
        form.addRow(button_box(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self.accept, self.reject))

        if template is not None:
            self._fill_from(template)

    def _fill_from(self, template: dict[str, Any]) -> None:
        """A copy for this month's bill: the same purchase, today's date, no document number."""
        self.setWindowTitle(tr("Copy a purchase"))
        self.supplier.setText(template["supplier"])
        self.description.setText(template["description"])
        self.category.setCurrentIndex(self.category.findData(template["category"]))
        self.amount.setText(fmt_number(abs(Decimal(template["amount_eur"])), 2))
        self.share.setValue(int(Decimal(template["pro_share"]) * 100))
        method = self.method.findData(template["payment_method"])
        if method >= 0:
            self.method.setCurrentIndex(method)

    def accept(self) -> None:
        seq = guarded(self, tr("Purchase not recorded"), lambda: self.book.purchases.record(
            paid_on=from_qdate(self.paid_on.date()),
            supplier=self.supplier.text(),
            description=self.description.text(),
            category=self.category.currentData(),
            amount_eur=self.amount.text(),
            pro_share=Decimal(self.share.value()) / 100,
            payment_method=self.method.currentData(),
            piece_ref=self.reference.text(),
        ))
        if seq is not None:
            self.seq = seq
            super().accept()


class ReversePurchaseDialog(FittedDialog):
    def __init__(self, entry: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Reverse entry {seq}", seq=entry["seq"]))
        form = QFormLayout(self)
        form.addRow(heading(
            f"{fmt_date(entry['paid_on'])}  ·  {entry['supplier']}", tr("The entry this cancels."), "h2",
        ))
        amount = QLineEdit(fmt_money(entry["amount_eur"]))
        amount.setReadOnly(True)
        form_row(form, tr("Amount"), amount, tr("The amount that will be cancelled by a negative entry."))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("Why this entry is being cancelled"))
        form_row(form, tr("Reason"), self.reason, tr(
            "Required. It stays with the reversal in the register and its exports."
        ))
        self.on = make_date_edit(entry["paid_on"])
        form_row(form, tr("Reversal date"), self.on, tr(
            "Keep the original date to fix a mistake: it cancels in the same year. Use the real "
            "date for a refund."
        ))
        form.addRow(button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self.accept, self.reject))


class PurchasesPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.addWidget(heading(tr("Purchases register"), tr(
            "The legal name of this record. In the VAT franchise you must keep it: a yearly register "
            "with the detail of your purchases of goods and services (art. 286 CGI, F23266)."
        )))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        top.addStretch(1)
        layout.addLayout(top)

        self.rule_banner = Banner(
            "info",
            tr("Under the micro regime, expenses aren't deducted: not from turnover, contributions or "
               "income tax. The flat allowance stands in for them. Nothing here is declared to URSSAF "
               "or the tax office: the register is kept with its supporting documents and shown on "
               "request."),
            tip=tr("Adding a purchase changes no other figure in the app. Sources: impots.gouv.fr, "
                   "F23266, BOFiP BOI-TVA-DECLA-40-10-20 s.290."),
        )
        layout.addWidget(self.rule_banner)
        self.problem = Banner("bad", tip=tr("A rate or limit is missing for this date."))
        layout.addWidget(self.problem)

        self.stats = StatRow([
            ("paid", tr("Purchases this year"), tr(
                "Everything paid in the year, VAT included: in the franchise, VAT isn't recovered."
            )),
            ("pro", tr("Professional share"), tr("The share of these purchases used for the activity.")),
            ("assets", tr("Of which fixed assets"), tr(
                "Lasting equipment. Under a real regime it would be depreciated over several years, "
                "not deducted at once."
            )),
            ("allowance", tr("Flat allowance"), tr(
                "What the tax office takes off turnover to stand in for your charges."
            )),
            ("real", tr("Estimated real charges"), tr(
                "Professional share without fixed assets, plus the year's social contributions at the "
                "micro rate. Only a yardstick: under a real regime, contributions are worked out differently."
            )),
        ])
        layout.addWidget(self.stats)

        self.note = dim_label("", tip=tr(
            "The flat allowance is meant to cover every charge, social contributions included "
            "(F23267), so they count on the real side. Fixed assets aren't included."
        ))
        layout.addWidget(self.note)

        self.table = DataTable(_columns(), key="seq")
        self.table.add_button(tr("Add a purchase…"), self.add_purchase, primary=True, tip=tr(
            "Records a purchase. It can't be edited afterwards, only reversed."
        ))
        self.copy_button = self.table.add_button(tr("Copy…"), self.copy_selected, tip=tr(
            "Opens a new purchase filled in from the selected one, dated today. Handy for a monthly "
            "subscription."
        ))
        self.reverse_button = self.table.add_button(tr("Reverse entry…"), self.reverse_selected, danger=True, tip=tr(
            "Entries can't be edited. This adds a reversing entry with a reason."
        ))
        self.attach_button = self.table.add_button(tr("Attach receipt…"), self.attach_receipt, tip=tr(
            "Keeps a copy of a file with the selected entry and queues it for Google Drive."
        ))
        self.table.add_button(tr("Export CSV"), self.export_csv, tip=tr(
            "Saves this year's register as a spreadsheet file, in French, and queues it for Drive."
        ))
        self.table.add_button(tr("Export PDF"), self.export_pdf, tip=tr(
            "Saves this year's register as a PDF, in French, and queues it for Drive."
        ))
        self.table.row_selected.connect(self._on_selected)
        layout.addWidget(self.table, 1)
        self._on_selected(None)

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        purchase = bool(row and row["kind"] == "purchase")
        self.copy_button.setEnabled(purchase)
        self.reverse_button.setEnabled(purchase and not row["is_reversed"])
        self.attach_button.setEnabled(row is not None)

    def _selected_year(self) -> int:
        return self.year.currentData() or clock.today().year

    def reload(self) -> None:
        current = self._selected_year()
        fill_years(self.year, set(self.book.purchases.years()) | {clock.today().year}, current)

        rows = []
        for entry in self.book.purchases.entries(current):
            row = dict(entry)
            row["category_shown"] = tr(entry["category"])
            row["method_shown"] = tr(entry["payment_method"])
            row["share_shown"] = fmt_percent(entry["pro_share"], 0)
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
        self._on_selected(self.table.current_row())

        try:
            comparison = self.book.regime_comparison(current)
        except MissingFigure as exc:
            self.problem.show_text(str(exc))
            return
        self.problem.show_text("")
        totals = comparison["purchases"]
        self.stats.set("paid", fmt_money(totals["paid"]))
        self.stats.set("pro", fmt_money(totals["pro"]))
        self.stats.set("assets", fmt_money(totals["fixed_assets"]))
        self.stats.set("allowance", fmt_money(comparison["allowance"]))
        self.stats.set("real", fmt_money(comparison["real_charges"]))
        self.stats.cards["assets"].set_tip(tr(
            "Lasting equipment above {amount} excluding VAT. Under a real regime it would be depreciated "
            "over several years, not deducted at once.",
            amount=fmt_money(comparison["fixed_asset_threshold"], decimals=0),
        ))
        self.stats.cards["allowance"].set_tip(tr(
            "What the tax office takes off turnover to stand in for your charges: {rate} of turnover, "
            "minimum {minimum}.",
            rate=fmt_percent(comparison["allowance_rate"], 0),
            minimum=fmt_money(comparison["allowance_min"], decimals=0),
        ))
        text = tr(
            "For {year}: about {real} of real charges ({charges} of purchases and {social} of contributions "
            "at the micro rate), against a flat allowance of {allowance}. This compares income tax only. A "
            "real regime also works out contributions on profit, with minimum amounts, and brings heavier "
            "accounting and filing duties: check with URSSAF's simulators or an expert-comptable before "
            "deciding.",
            year=current, real=fmt_money(comparison["real_charges"]), charges=fmt_money(totals["charges"]),
            social=fmt_money(comparison["social"]), allowance=fmt_money(comparison["allowance"]),
        )
        if comparison["vl"]:
            text += " " + tr(
                "You opted for the versement libératoire: the allowance doesn't apply to your tax, so "
                "this is only a yardstick."
            )
        self.note.setText(text)

    # -- actions ------------------------------------------------------------
    def add_purchase(self) -> None:
        self._open(PurchaseDialog(self.book, self))

    def copy_selected(self) -> None:
        row = self.table.current_row()
        if row is not None and row["kind"] == "purchase":
            self._open(PurchaseDialog(self.book, self, template=row))

    def _open(self, dialog: PurchaseDialog) -> None:
        if dialog.exec() == QDialog.Accepted and dialog.seq is not None:
            self.recorded(dialog.seq)

    def recorded(self, seq: int) -> None:
        self.status.emit(tr("Purchase {seq} recorded. Attach its invoice or receipt if you have it.", seq=seq))
        self.changed.emit()

    def reverse_selected(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        dialog = ReversePurchaseDialog(row, self)
        if dialog.exec() == QDialog.Accepted:
            self.reverse(int(row["seq"]), dialog.reason.text(), from_qdate(dialog.on.date()))

    def reverse(self, seq: int, reason: str, on: date | None = None) -> int | None:
        new_seq = guarded(self, tr("Not reversed"), lambda: self.book.purchases.reverse(seq, reason, on))
        if new_seq is not None:
            self.status.emit(tr("Entry {seq} reversed by entry {new}.", seq=seq, new=new_seq))
            self.changed.emit()
        return new_seq

    def attach_receipt(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        path, _filter = QFileDialog.getOpenFileName(self, tr("Attach a receipt to entry {seq}", seq=row["seq"]))
        if path:
            self.attach(int(row["seq"]), path)

    def attach(self, seq: int, path: str) -> int | None:
        doc_id = guarded(self, tr("Receipt not attached"), lambda: self.book.attach_purchase_document(seq, path))
        if doc_id is not None:
            self.status.emit(tr("Receipt attached to entry {seq} and queued for Drive.", seq=seq))
            self.changed.emit()
        return doc_id

    def export_csv(self, ask: bool = True) -> int | None:
        return run_export(self, "CSV", lambda: self.book.exports.purchases_csv(self._selected_year()), ask)

    def export_pdf(self, ask: bool = True) -> int | None:
        return run_export(self, "PDF", lambda: self.book.exports.purchases_pdf(self._selected_year()), ask)


__all__ = ["PurchaseDialog", "PurchasesPanel", "ReversePurchaseDialog"]
