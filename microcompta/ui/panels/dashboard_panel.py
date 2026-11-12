"""The limits dashboard. Every sentence on it comes from core/limits.py."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.ledger_policy import BASIS_LABELS, FEE_POINTER, UNCONFIRMED
from ...core.limits import LimitCard, LimitsReport, contribution_rate
from ...core.money import fmt_money
from ...i18n import fmt_date, fmt_number, fmt_percent, tr
from ..models import Col
from ..theme import BAD, GOOD, WARN
from ..widgets.table_view import DataTable
from ..widgets.threshold_bar import ThresholdBar
from .common import (
    Banner, Chip, StatCard, _BubbleOnFocus, bubble, card_frame, dim_label, fill_years, heading,
    scroll_page, year_combo,
)


class LimitCardWidget(_BubbleOnFocus, QWidget):
    """One limit: title, status, bar, the numbers, and what it means."""

    def __init__(self, tip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)
        self._tip = tip
        frame = card_frame()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(5)

        top = QHBoxLayout()
        self.title = heading("", object_name="h2")
        self.chip = Chip()
        top.addWidget(self.title, 1)
        top.addWidget(self.chip)
        lay.addLayout(top)

        self.bar = ThresholdBar()
        bubble(self.bar, tr(
            "The solid part is the amount so far. A faint part is where this year's pace leads. "
            "The white line is the limit, and a grey line marks a lower limit."
        ), tr("How full this limit is"))
        lay.addWidget(self.bar)
        self.numbers = dim_label("", wrap=False, tip=tr(
            "The amount so far against this year's limit, in euros."
        ))
        lay.addWidget(self.numbers)
        self.headline = QLabel("")
        self.headline.setWordWrap(True)
        lay.addWidget(self.headline)
        self.details = dim_label("")
        lay.addWidget(self.details)
        lay.addStretch(1)
        bubble(frame, tip)
        bubble(self, tip)

    def show_card(self, card: LimitCard) -> None:
        chip_text = {"ok": tr("OK"), "near": tr("Watch"), "warn": tr("Warning"),
                     "over": tr("Action needed"), "info": tr("Info")}
        chip_tip = {
            "ok": tr("Nothing to do for this limit."),
            "near": tr("Getting close to this limit, or past it for one year only."),
            "warn": tr("This limit is passed or about to be. Read the line below."),
            "over": tr("This limit has consequences now. Read the line below."),
            "info": tr("For information. Nothing to compare yet."),
        }
        self.title.setText(card.title)
        self.chip.setText(chip_text.get(card.level, card.level))
        self.chip.set_level(card.level)
        bubble(self.chip, chip_tip.get(card.level, self._tip))
        ticks = [t[0] for t in card.ticks]
        self.bar.set_values(card.value, card.limit, card.projection, ticks, card.level)
        text = tr("{value} of {limit}", value=fmt_money(card.value), limit=fmt_money(card.limit, decimals=0))
        if card.projection is not None:
            text += "  ·  " + tr("run-rate {amount}", amount=fmt_money(card.projection, decimals=0))
        for amount, label in card.ticks:
            text += f"  ·  {label} {fmt_money(amount, decimals=0)}"
        self.numbers.setText(text)
        self.headline.setText(card.headline)
        self.details.setText("\n".join(card.details))
        self.details.setVisible(bool(card.details))
        self.bar.setVisible(card.has_bar)
        self.numbers.setVisible(card.has_bar)
        self.setAccessibleName(f"{card.title}: {card.headline}")


class KpiBoard(QWidget):
    """The year at a glance, as tiles of different sizes: the number that matters most is the
    biggest. Each number keeps its own card, caption and bubble, reached by key as in StatRow."""

    def __init__(self, specs: dict[str, tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.cards: dict[str, StatCard] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        hero, lay = self._tile()
        lay.addWidget(self._card(specs, "ytd", "hero"))
        row = QHBoxLayout()
        row.setSpacing(28)
        for key in ("projection", "ceiling_pct", "base"):
            row.addWidget(self._card(specs, key, "small"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        contributions, lay = self._tile()
        lay.addWidget(self._card(specs, "set_aside", "large"))
        lay.addWidget(self._card(specs, "rate", "small"))
        lay.addStretch(1)

        upcoming, lay = self._tile()
        lay.addWidget(self._card(specs, "next", "large"))
        self.next_note = QLabel("")
        self.next_note.setObjectName("tileNote")
        self.next_note.setWordWrap(True)
        bubble(self.next_note, tr("What is due on that date. The full list is on the Deadlines tab."))
        lay.addWidget(self.next_note)
        lay.addStretch(1)

        grid.addWidget(hero, 0, 0)
        grid.addWidget(contributions, 0, 1)
        grid.addWidget(upcoming, 0, 2)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

    @staticmethod
    def _tile() -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("tile")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(10)
        return frame, lay

    def _card(self, specs: dict[str, tuple[str, str]], key: str, size: str) -> StatCard:
        label, tip = specs[key]
        card = StatCard(label, tip, size=size)
        self.cards[key] = card
        return card

    def set(self, key: str, text: str, colour: str | None = None) -> None:
        self.cards[key].set_text(text, colour)


class DashboardPanel(QWidget):
    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(heading(tr("Limits"), tr(
            "The legal limits that depend on your turnover, and what to set aside."
        )))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        top.addStretch(1)
        self.basis_chip = Chip("", "near", tr(FEE_POINTER))
        top.addWidget(self.basis_chip)
        layout.addLayout(top)

        self.setup_banner = Banner("warn", tip=tr("The limits and deadlines need your start date."))
        layout.addWidget(self.setup_banner)
        self.problem_banner = Banner("bad", tip=tr("A rate or limit is missing for this date."))
        layout.addWidget(self.problem_banner)

        self.stats = KpiBoard(dict((key, (label, tip)) for key, label, tip in [
            ("ytd", tr("Year to date"), tr(
                "Turnover received from 1 January to today, counted on the date each payment arrived."
            )),
            ("projection", tr("Run-rate"), tr(
                "Year to date carried to 31 December at the same pace. An estimate, not a forecast."
            )),
            ("ceiling_pct", tr("Of micro ceiling"), tr(
                "Year to date as a share of this year's micro ceiling. Green is fine, amber means "
                "watch it, red means it has consequences."
            )),
            ("set_aside", tr("Set aside"), tr(
                "Contributions on this year's turnover, at the rate in force on each payment's "
                "date. Keep this money aside: URSSAF collects it with each declaration."
            )),
            ("rate", tr("Current rate"), tr(
                "The share of turnover to set aside for a payment received today."
            )),
            ("base", tr("Taxable base"), tr(
                "For information: turnover less the flat allowance. Not a tax calculation."
            )),
            ("next", tr("Next deadline"), tr("The nearest date not yet marked done.")),
        ]))
        layout.addWidget(self.stats)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {
            "ceiling": LimitCardWidget(tr(
                "The most turnover the micro regime allows per year, prorated by days of activity "
                "in the first year. One year over is allowed; two consecutive years over means "
                "leaving the regime on 1 January."
            )),
            "vat": LimitCardWidget(tr(
                "Above these limits you must charge VAT. Only turnover taxed in France counts. "
                "Above the base limit, the franchise ends on 1 January; above the upper limit, on "
                "the day it is crossed."
            )),
            "bank": LimitCardWidget(tr(
                "A separate bank account becomes mandatory when turnover is above this amount two "
                "years in a row."
            )),
            "cfe": LimitCardWidget(tr(
                "Cotisation foncière des entreprises, a local business tax. Nothing is owed in the "
                "first year, and none when turnover two years earlier is at or below this amount."
            )),
        }
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
            Col("label", tr("Period"), width=110, sort_key="start",
                tip=tr("A month or a quarter, following your declaration frequency.")),
            Col("turnover", tr("Turnover"), "eur", 110,
                tip=tr("Received in the period, under the current turnover setting.")),
            Col("rates", tr("Rate"), width=90,
                tip=tr("The contribution rate in force for the payments of this period.")),
            Col("set_aside", tr("To set aside"), "eur", 110,
                tip=tr("Turnover times the rate, payment by payment.")),
            Col("entries", tr("Payments"), "int", 78, tip=tr("How many ledger entries this period holds.")),
        ], title=tr("To set aside by period"),
           title_tip=tr("What to keep aside for each declaration."), key="label")
        self.upcoming = DataTable([
            Col("due", tr("Due"), "date", 90, tip=tr("The last day for this.")),
            Col("days_left", tr("In"), "days", 75, tip=tr("Days from today.")),
            Col("title", tr("Deadline"), width=280, tip=tr("What is due. The full list is on the Deadlines tab.")),
            Col("status", tr("Status"), "status", 90,
                tip=tr("Upcoming, due soon (within 14 days) or overdue.")),
        ], title=tr("Next deadlines"), title_tip=tr("The nearest dates, from the Deadlines tab."), key="key")
        self.periods.layout().setContentsMargins(0, 0, 0, 0)
        self.upcoming.layout().setContentsMargins(0, 0, 0, 0)
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

        self.basis_chip.setText(tr(
            "{basis}: {label}",
            basis=tr(BASIS_LABELS.get(profile.turnover_basis, profile.turnover_basis)),
            label=tr(UNCONFIRMED),
        ))
        self.setup_banner.show_text(
            "" if profile.is_set_up else tr(
                "Start here: enter your name, address and start date in Settings, the gear icon at "
                "the top right. The prorated limits and the deadlines depend on the start date."
            )
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
        self.stats.cards["projection"].set_tip(tr(
            "Year to date carried to 31 December at the same pace. An estimate, not a forecast. "
            "Based on {elapsed} of {total} days of activity this year.",
            elapsed=report.days_elapsed, total=report.days_total,
        ))
        limit = report.ceiling.limit
        share = report.ytd / limit if limit else 0
        colour = BAD if report.ceiling.level == "over" else WARN if report.ceiling.level in (
            "warn", "near") else GOOD
        self.stats.set("ceiling_pct", fmt_percent(share), colour)
        self.stats.cards["ceiling_pct"].set_tip(tr(
            "Year to date as a share of this year's micro ceiling, {limit}. Green is fine, amber "
            "means watch it, red means it has consequences.", limit=fmt_money(limit, decimals=0),
        ))
        self.stats.set("set_aside", fmt_money(report.set_aside))
        self.stats.set("base", fmt_money(annual["taxable_base"], decimals=0))
        self.stats.cards["base"].set_tip(tr(
            "For information: turnover less the flat allowance of {rate}, minimum {minimum}. Not a "
            "tax calculation: the tax office applies it.",
            rate=fmt_percent(annual["allowance_rate"], 0),
            minimum=fmt_money(annual["allowance_min"], decimals=0),
        ))

        info = contribution_rate(clock.today(), profile, self.book.figures)
        self.stats.set("rate", fmt_percent(info.rate))
        tip = tr("The share of turnover to set aside for a payment received today: {label}.", label=info.label)
        if report.acre_until:
            tip += " " + tr("ACRE until {date}.", date=fmt_date(report.acre_until))
        self.stats.cards["rate"].set_tip(tip)

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
            self.stats.set("next", fmt_date(first["due"]), colour)
            self.stats.cards["next"].set_tip(tr(
                "The nearest date not yet marked done: {title}.", title=first["title"],
            ))
            self.stats.next_note.setText(first["title"])
        else:
            self.stats.set("next", "—")
            self.stats.next_note.setText("")


__all__ = ["DashboardPanel", "fmt_number"]
