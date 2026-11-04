"""Deadlines from the start date, with what to declare for each period."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.money import fmt_money
from ..models import Col
from ..theme import BAD, GOOD, WARN
from ..widgets.table_view import DataTable
from .common import Banner, StatRow, dim_label, from_qdate, guarded, heading, make_date_edit

COLUMNS = [
    Col("when", "Due", width=120, sort_key="sort_date"),
    Col("days_left", "In", "days", 74),
    Col("status", "Status", "status", 82),
    Col("title", "Deadline", width=330),
    Col("category", "Type", width=92),
    Col("to_declare", "To declare", width=96,
        tip="Turnover received in the period, under the current setting. Zero is still declared."),
    Col("note", "Note", width=420),
]


class DeadlinesPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        layout.addWidget(heading("Deadlines"))

        self.banner = Banner("warn")
        layout.addWidget(self.banner)
        self.stats = StatRow([
            ("overdue", "Overdue", "Past their date and not marked done."),
            ("soon", "Due within 14 days", ""),
            ("next", "Next date", ""),
            ("done", "Done", ""),
        ])
        layout.addWidget(self.stats)

        self.table = DataTable(COLUMNS, key="key")
        self.show_done = QCheckBox("Show done and passed")
        self.show_done.toggled.connect(lambda _on: self.reload())
        self.table.add_widget(self.show_done)
        self.done_button = self.table.add_button("Mark done", self.toggle_done, primary=True)
        self.date_button = self.table.add_button(
            "Set date…", self.set_date_selected,
            tip="For a deadline with no fixed date, once the date is published.",
        )
        self.table.row_selected.connect(self._on_selected)
        layout.addWidget(self.table, 1)
        layout.addWidget(dim_label(
            "Reminders reach the tray only while the app is running. They are reminders: the "
            "filing itself happens on URSSAF's and impots.gouv.fr's sites."
        ))
        self._on_selected(None)

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        self.done_button.setEnabled(row is not None)
        self.done_button.setText("Mark not done" if row and row["done"] else "Mark done")
        self.date_button.setEnabled(bool(row and not row["fixed_date"]))

    def reload(self) -> None:
        profile = self.book.profile()
        self.banner.show_text(
            "" if profile.start_date else
            "Enter your start date under Settings to work out the declarations and other dates."
        )
        try:
            items = self.book.deadlines.items()
        except MissingFigure as exc:
            self.banner.show_text(str(exc), "bad")
            return
        rows = []
        for item in items:
            row = dict(item)
            row["when"] = (
                item["due"].isoformat() if item["due"]
                else f"Spring {item['remind_from'].year}" if item["remind_from"] else ""
            )
            row["sort_date"] = item["due"] or item["remind_from"]
            row["to_declare"] = ""
            if item["period_start"] is not None:
                amount = self.book.limits.turnover_between(item["period_start"], item["period_end"])
                row["to_declare"] = "Néant" if amount == 0 else fmt_money(amount)
            row["_dim"] = item["done"] or item["status"] == "passed"
            rows.append(row)
        closed = ("done", "passed")
        visible = rows if self.show_done.isChecked() else [r for r in rows if r["status"] not in closed]
        self.table.set_rows(visible)
        self._on_selected(self.table.current_row())

        overdue = sum(1 for r in rows if r["status"] == "overdue")
        soon = sum(1 for r in rows if r["status"] == "due soon")
        self.stats.set("overdue", str(overdue), BAD if overdue else GOOD)
        self.stats.set("soon", str(soon), WARN if soon else None)
        pending = [r for r in rows if r["status"] not in closed and r["due"]]
        self.stats.set("next", pending[0]["due"].isoformat() if pending else "—")
        self.stats.cards["next"].setToolTip(pending[0]["title"] if pending else "")
        self.stats.set("done", str(sum(1 for r in rows if r["done"])))

    def counts(self) -> tuple[int, int]:
        """(overdue, due soon), for the tab label and the tray."""
        try:
            items = self.book.deadlines.items()
        except MissingFigure:
            return 0, 0
        return (sum(1 for i in items if i["status"] == "overdue"),
                sum(1 for i in items if i["status"] == "due soon"))

    def toggle_done(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        self.book.deadlines.set_done(row["key"], not row["done"])
        self.status.emit(f"{'Not done' if row['done'] else 'Done'}: {row['title']}")
        self.changed.emit()

    def set_date_selected(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(row["title"])
        form = QFormLayout(dialog)
        form.addRow(dim_label("Enter the date published on impots.gouv.fr."))
        edit = make_date_edit(row["due"] or clock.today())
        form.addRow("Date", edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted and guarded(
            self, "Not saved",
            lambda: self.book.deadlines.set_date(row["key"], from_qdate(edit.date())) or True,
        ):
            self.changed.emit()
