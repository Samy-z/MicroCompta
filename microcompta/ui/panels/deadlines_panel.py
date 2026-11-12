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
from ...i18n import fmt_date, tr
from ..models import Col
from ..theme import BAD, GOOD, WARN
from ..widgets.table_view import DataTable
from .common import (
    Banner, StatRow, bubble, button_box, dim_label, form_row, from_qdate, guarded, heading,
    make_date_edit,
)


def _columns() -> list[Col]:
    return [
        Col("when", tr("Due"), width=120, sort_key="sort_date", tip=tr(
            "The last day for this. Form 2042 C PRO shows only the season until you enter the "
            "published date."
        )),
        Col("days_left", tr("In"), "days", 74, tip=tr("Days from today.")),
        Col("status", tr("Status"), "status", 82, tip=tr(
            "Upcoming, due soon (within 14 days), overdue, done, or passed for an optional choice "
            "you didn't take."
        )),
        Col("title", tr("Deadline"), width=330, tip=tr("What is due.")),
        Col("category_shown", tr("Type"), width=92, tip=tr(
            "Declaration, tax, filing, option, or housekeeping for the app itself."
        )),
        Col("to_declare", tr("To declare"), width=96, tip=tr(
            "Turnover received in the period, under the current setting. Zero is still declared, "
            "as \"Néant\"."
        )),
        Col("note", tr("Note"), width=420, tip=tr("What to do, and what happens if it's missed.")),
    ]


class DeadlinesPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(7)
        layout.addWidget(heading(tr("Deadlines"), tr(
            "Worked out from your start date. The app reminds; the filing itself happens on URSSAF's "
            "and impots.gouv.fr's sites."
        )))

        self.banner = Banner("warn", tip=tr("Declarations and most other dates depend on your start date."))
        layout.addWidget(self.banner)
        self.stats = StatRow([
            ("overdue", tr("Overdue"), tr("Past their date and not marked done.")),
            ("soon", tr("Due within 14 days"), tr("Coming up soon and not marked done.")),
            ("next", tr("Next date"), tr("The nearest date not yet marked done.")),
            ("done", tr("Done"), tr("Deadlines you have marked done.")),
        ])
        layout.addWidget(self.stats)

        self.table = DataTable(_columns(), key="key")
        self.show_done = QCheckBox(tr("Show done and passed"))
        bubble(self.show_done, tr("Also list what you've marked done, and optional choices whose date has passed."))
        self.show_done.toggled.connect(lambda _on: self.reload())
        self.table.add_widget(self.show_done)
        self.done_button = self.table.add_button(tr("Mark done"), self.toggle_done, primary=True, tip=tr(
            "Records that this is done, which stops its reminders. It can be undone."
        ))
        self.date_button = self.table.add_button(tr("Set date…"), self.set_date_selected, tip=tr(
            "For a deadline with no fixed date, once the date is published."
        ))
        self.table.row_selected.connect(self._on_selected)
        layout.addWidget(self.table, 1)
        layout.addWidget(dim_label(
            tr("Reminders reach the tray only while the app is running. They are reminders: the "
               "filing itself happens on URSSAF's and impots.gouv.fr's sites."),
            tip=tr("Closing the window keeps the app in the tray, so reminders still fire."),
        ))
        self._on_selected(None)

    def _on_selected(self, row: dict[str, Any] | None) -> None:
        self.done_button.setEnabled(row is not None)
        self.done_button.setText(tr("Mark not done") if row and row["done"] else tr("Mark done"))
        self.date_button.setEnabled(bool(row and not row["fixed_date"]))

    def reload(self) -> None:
        profile = self.book.profile()
        self.banner.show_text(
            "" if profile.start_date else tr(
                "Enter your start date in Settings, the gear icon at the top right, to work out the "
                "declarations and other dates."
            )
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
                fmt_date(item["due"]) if item["due"]
                else tr("Spring {year}", year=item["remind_from"].year) if item["remind_from"] else ""
            )
            row["sort_date"] = item["due"] or item["remind_from"]
            row["category_shown"] = tr(item["category"])
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
        self.stats.set("next", fmt_date(pending[0]["due"]) if pending else "—")
        self.stats.cards["next"].set_tip(
            tr("The nearest date not yet marked done: {title}.", title=pending[0]["title"]) if pending
            else tr("The nearest date not yet marked done.")
        )
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
        self.status.emit(
            tr("Not done: {title}", title=row["title"]) if row["done"]
            else tr("Done: {title}", title=row["title"])
        )
        self.changed.emit()

    def set_date_selected(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(row["title"])
        form = QFormLayout(dialog)
        form.addRow(dim_label(tr("Enter the date published on impots.gouv.fr."), tip=tr(
            "The filing date changes every year, so the app stores none of its own."
        )))
        edit = make_date_edit(row["due"] or clock.today())
        form_row(form, tr("Date"), edit, tr("The last day for this filing, as published."))
        form.addRow(button_box(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog.accept, dialog.reject))
        if dialog.exec() == QDialog.Accepted and guarded(
            self, tr("Not saved"),
            lambda: self.book.deadlines.set_date(row["key"], from_qdate(edit.date())) or True,
        ):
            self.changed.emit()
