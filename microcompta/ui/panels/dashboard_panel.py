"""The limits dashboard. Every sentence on it comes from core/limits.py."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.ledger_policy import BASIS_LABELS, UNCONFIRMED
from ...core.limits import LimitCard, Limits, LimitsReport, taxable_base
from ...core.money import fmt_money
from ..models import Col
from ..theme import BAD, GOOD, WARN
from ..widgets.table_view import DataTable
from ..widgets.threshold_bar import ThresholdBar
from .common import Banner, Chip, StatRow, card_frame, dim_label, fill_years, heading, scroll_page, year_combo

_CHIP_TEXT = {"ok": "OK", "near": "Watch", "warn": "Warning", "over": "Action needed", "info": "Info"}


class LimitCardWidget(QWidget):
    """One limit: title, status, bar, the numbers, and what it means."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        frame = card_frame()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.title = heading("", "h2")
        self.chip = Chip()
        top.addWidget(self.title, 1)
        top.addWidget(self.chip)
        lay.addLayout(top)

        self.bar = ThresholdBar()
        lay.addWidget(self.bar)
        self.numbers = dim_label("", wrap=False)
        lay.addWidget(self.numbers)
        self.headline = QLabel("")
        self.headline.setWordWrap(True)
        lay.addWidget(self.headline)
        self.details = dim_label("")
        lay.addWidget(self.details)
        lay.addStretch(1)

    def show_card(self, card: LimitCard) -> None:
        self.title.setText(card.title)
        self.chip.setText(_CHIP_TEXT.get(card.level, card.level))
        self.chip.set_level(card.level)
        ticks = [t[0] for t in card.ticks]
        self.bar.set_values(card.value, card.limit, card.projection, ticks, card.level)
        text = f"{fmt_money(card.value)} of {fmt_money(card.limit, decimals=0)}"
        if card.projection is not None:
            text += f"  ·  run-rate {fmt_money(card.projection, decimals=0)}"
        for amount, label in card.ticks:
            text += f"  ·  {label} {fmt_money(amount, decimals=0)}"
        self.numbers.setText(text)
        self.headline.setText(card.headline)
        self.details.setText("\n".join(card.details))
        self.bar.setVisible(card.has_bar)
        self.numbers.setVisible(card.has_bar)
        self.details.setVisible(bool(card.details))


class DashboardPanel(QWidget):
    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(heading("Limits"))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        top.addStretch(1)
        self.basis_chip = Chip("", "near")
        top.addWidget(self.basis_chip)
        layout.addLayout(top)

        self.setup_banner = Banner("warn")
        layout.addWidget(self.setup_banner)
        self.problem_banner = Banner("bad")
        layout.addWidget(self.problem_banner)

        self.stats = StatRow([
            ("ytd", "Year to date", "Turnover received this year."),
            ("projection", "Run-rate", "Year to date carried to 31 December at the same pace."),
            ("ceiling_pct", "Of micro ceiling", ""),
            ("set_aside", "Set aside", "Contributions on this year's turnover."),
            ("rate", "Current rate", "Contribution rate in force today."),
            ("base", "Taxable base", "For information: turnover less the flat allowance."),
            ("next", "Next deadline", ""),
        ])
        layout.addWidget(self.stats)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.cards = {key: LimitCardWidget() for key in ("ceiling", "vat", "bank", "cfe")}
        grid.addWidget(self.cards["ceiling"], 0, 0)
        grid.addWidget(self.cards["vat"], 0, 1)
        grid.addWidget(self.cards["bank"], 1, 0)
        grid.addWidget(self.cards["cfe"], 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.periods = DataTable([
            Col("label", "Period", width=110, sort_key="start"),
            Col("turnover", "Turnover", "eur", 110),
            Col("rates", "Rate", width=90),
            Col("set_aside", "To set aside", "eur", 110),
            Col("entries", "Payments", "int", 70),
        ], title="To set aside by period", key="label")
        self.upcoming = DataTable([
            Col("due", "Due", "date", 90),
            Col("days_left", "In", "days", 75),
            Col("title", "Deadline", width=280),
            Col("status", "Status", "status", 90),
        ], title="Next deadlines", key="key")
        self.periods.layout().setContentsMargins(0, 0, 6, 0)
        self.upcoming.layout().setContentsMargins(6, 0, 0, 0)
        splitter.addWidget(self.periods)
        splitter.addWidget(self.upcoming)
        splitter.setSizes([500, 620])
        splitter.setMinimumHeight(230)
        layout.addWidget(splitter, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def _year_choices(self) -> list[int]:
        years = set(self.book.ledger.years()) | {clock.today().year}
        start = self.book.profile().start_date
        if start:
            years.add(start.year)
        return sorted(y for y in years if not start or y >= start.year)

    def reload(self) -> None:
        current = self.year.currentData() or clock.today().year
        fill_years(self.year, self._year_choices(), current)
        profile = self.book.profile()

        self.basis_chip.setText(
            f"{BASIS_LABELS.get(profile.turnover_basis, profile.turnover_basis)}: {UNCONFIRMED}"
        )
        self.setup_banner.show_text(
            "" if profile.is_set_up else
            "Start here: enter your name, address and start date under Settings. The prorated "
            "limits and the deadlines depend on the start date."
        )

        try:
            report = self.book.limits.report(current)
            annual = self.book.limits.annual(current)
        except MissingFigure as exc:
            self.problem_banner.show_text(str(exc))
            return
        self.problem_banner.show_text("")
        self._show(report, annual)

    def _show(self, report: LimitsReport, annual: dict[str, Any]) -> None:
        profile = self.book.profile()
        self.stats.set("ytd", fmt_money(report.ytd))
        self.stats.set("projection", fmt_money(report.projection, decimals=0))
        self.stats.cards["projection"].setToolTip(
            f"Based on {report.days_elapsed} of {report.days_total} days of activity this year."
        )
        limit = report.ceiling.limit
        pct = report.ytd / limit * 100 if limit else 0
        colour = BAD if report.ceiling.level == "over" else WARN if report.ceiling.level in (
            "warn", "near") else GOOD
        self.stats.set("ceiling_pct", f"{pct:.1f}%", colour)
        self.stats.set("set_aside", fmt_money(report.set_aside))
        self.stats.set("base", fmt_money(annual["taxable_base"], decimals=0))
        self.stats.cards["base"].setToolTip(
            f"Information only: {annual['allowance_rate'] * 100:.0f}% allowance, minimum "
            f"{fmt_money(annual['allowance_min'], decimals=0)}. Not a tax calculation."
        )

        from ...core.limits import contribution_rate

        info = contribution_rate(clock.today(), profile, self.book.figures)
        self.stats.set("rate", f"{info.rate * 100:.1f}%")
        tip = info.label
        if report.acre_until:
            tip += f". ACRE until {report.acre_until}."
        self.stats.cards["rate"].setToolTip(tip)

        for key, widget in self.cards.items():
            widget.show_card(getattr(report, key))

        self.periods.set_rows([
            {"label": p.label, "start": p.start, "turnover": p.turnover, "rates": p.rates,
             "set_aside": p.set_aside, "entries": p.entries}
            for p in report.periods
        ])

        items = [i for i in self.book.deadlines.items() if i["status"] not in ("done", "passed")]
        upcoming = [i for i in items if i["due"] is not None][:12]
        self.upcoming.set_rows(upcoming)
        if upcoming:
            first = upcoming[0]
            colour = BAD if first["status"] == "overdue" else WARN if first["status"] == "due soon" else None
            self.stats.set("next", first["due"].isoformat(), colour)
            self.stats.cards["next"].setToolTip(first["title"])
        else:
            self.stats.set("next", "—")


__all__ = ["DashboardPanel", "Limits", "taxable_base"]
