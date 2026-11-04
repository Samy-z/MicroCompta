"""The annual page. Not a bilan: a micro-entrepreneur doesn't have one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.ledger_policy import UNCONFIRMED
from ...core.money import fmt_money
from ...core.open_questions import OPEN_QUESTIONS
from ...i18n import fmt_percent, tr
from ..models import Col
from ..widgets.table_view import DataTable
from .common import (
    Banner, StatRow, bubble, card_frame, dim_label, fill_years, heading, scroll_page, year_combo,
)


def _checklist() -> list[tuple[str, str, str]]:
    return [
        ("vl", tr("Versement libératoire: keep or change for next year?"), tr(
            "The option for next year closes on the date in Deadlines. Depends on your reference "
            "tax income."
        )),
        ("regime", tr("Micro regime, real regime or a company?"), tr(
            "Compare your real costs with the flat allowance. The real regime is an option by "
            "written notice to the SIE."
        )),
        ("expert", tr("One paid consultation with an expert-comptable?"), ""),
        ("limits", tr("Limits: any year over, or a second year running?"), tr(
            "See the Limits tab for the ceiling, the VAT franchise and the bank account rule."
        )),
        ("figures", tr("Figures: anything new for next year?"), tr(
            "Rates and limits change. Add a row under Settings > Figures."
        )),
        ("backup", tr("Backup: everything uploaded, and a copy you can open?"), tr(
            "See the Backup tab. Open one PDF from Drive to be sure."
        )),
    ]


class AnnualPanel(QWidget):
    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(heading(tr("Annual review"), tr(
            "The year's totals and a checklist. Not a bilan: a micro-entrepreneur doesn't have one."
        )))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        top.addStretch(1)
        layout.addLayout(top)

        layout.addWidget(Banner(
            "info",
            tr("This page reminds and adds up; it does not give tax advice. A micro-entrepreneur has "
               "no annual bilan: the records are the livre des recettes and the invoices, kept 10 years."),
            tip=tr("Check anything that matters with URSSAF, the SIE or an expert-comptable."),
        ))
        self.problem = Banner("bad", tip=tr("A rate or limit is missing for this date."))
        layout.addWidget(self.problem)

        self.stats = StatRow([
            ("turnover", tr("Turnover"), tr("Received in the year, under the current setting.")),
            ("contributions", tr("Contributions"), tr("At the rate in force on each payment's date.")),
            ("form", tr("Form 2042 C PRO"), tr("The year's turnover to report on your income tax return, to the euro.")),
            ("base", tr("Taxable base"), tr("Information only: the tax office applies the allowance.")),
            ("run", tr("Run-rate"), tr("The year's turnover carried to 31 December at the same pace.")),
        ])
        layout.addWidget(self.stats)

        self.form_note = dim_label("", tip=tr(
            "Which box to use depends on your activity and options, so the app doesn't name one."
        ))
        layout.addWidget(self.form_note)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)
        left_lay.addWidget(heading(tr("Totals every 3 months"), tr(
            "The livre des recettes must show totals every 3 months."
        ), "h2"))
        self.quarters = DataTable([
            Col("quarter_label", tr("Quarter"), width=90, tip=tr("A calendar quarter.")),
            Col("entries", tr("Entries"), "int", 60, tip=tr("How many ledger entries it holds.")),
            Col("eur_gross", tr("EUR gross"), "eur", 100, tip=tr("Received, before fees, at each entry's rate.")),
            Col("fee_eur", tr("Fees"), "eur", 90, tip=tr("What the providers kept.")),
            Col("net_eur", tr("Net credited"), "eur", 100, tip=tr("What reached your account in euros.")),
            Col("counted", tr("Turnover"), "eur", 100, tip=tr("What counts as turnover under the current setting.")),
        ], toolbar=False)
        self.quarters.setMinimumHeight(135)
        left_lay.addWidget(self.quarters)
        left_lay.addWidget(heading(tr("Still open"), tr(
            "Questions the official sources read so far don't settle, and who can answer them."
        ), "h2"))
        self.questions = DataTable([
            Col("topic", tr("Question"), width=190, tip=tr("What isn't settled.")),
            Col("who", tr("Who answers"), width=92, tip=tr("Who to ask.")),
            Col("status", tr("Status"), width=120, tip=tr("Where it stands.")),
            Col("detail", tr("Detail"), width=330, tip=tr("What is known, and what the app assumes.")),
        ], toolbar=False)
        self.questions.setMinimumHeight(260)
        self.questions.set_wrapped()
        self.questions.set_rows([
            {key: tr(value) for key, value in question.items()} for question in OPEN_QUESTIONS
        ])
        left_lay.addWidget(self.questions, 1)
        splitter.addWidget(left)

        right = card_frame()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 10, 12, 10)
        right_lay.setSpacing(6)
        right_lay.addWidget(heading(tr("Review checklist"), tr(
            "A reminder of what to look at each year. Ticks are kept per year."
        ), "h2"))
        self.checks: dict[str, QCheckBox] = {}
        self.hints: dict[str, QLabel] = {}
        for key, text, hint in _checklist():
            box = QCheckBox(text)
            box.toggled.connect(lambda on, k=key: self._on_check(k, on))
            bubble(box, hint or tr("Suggested when on course for the amount in Settings > Figures."))
            self.checks[key] = box
            right_lay.addWidget(box)
            label = dim_label(hint)
            label.setContentsMargins(20, 0, 0, 4)
            bubble(label, hint or tr("Suggested when on course for the amount in Settings > Figures."))
            self.hints[key] = label
            right_lay.addWidget(label)
        right_lay.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([740, 420])
        layout.addWidget(splitter, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def _selected_year(self) -> int:
        return self.year.currentData() or clock.today().year

    def reload(self) -> None:
        current = self._selected_year()
        start = self.book.profile().start_date
        years = set(self.book.ledger.years()) | {clock.today().year}
        if start:
            years = {y for y in years | {start.year} if y >= start.year}
        fill_years(self.year, years, current)
        current = self._selected_year()

        try:
            annual = self.book.limits.annual(current)
        except MissingFigure as exc:
            self.problem.show_text(str(exc))
            return
        self.problem.show_text("")
        self.stats.set("turnover", fmt_money(annual["turnover"]))
        self.stats.set("contributions", fmt_money(annual["contributions"]))
        self.stats.set("form", fmt_money(annual["form_2042_figure"], decimals=0))
        self.stats.set("base", fmt_money(annual["taxable_base"], decimals=0))
        self.stats.set("run", fmt_money(annual["projection"], decimals=0))
        self.form_note.setText(tr(
            "The 2042 C PRO figure follows the current turnover setting ({label}). The box depends on "
            "your activity and options: see the form's notice. Taxable base: {rate} allowance, minimum "
            "{minimum}, for information.",
            label=tr(UNCONFIRMED), rate=fmt_percent(annual["allowance_rate"], 0),
            minimum=fmt_money(annual["allowance_min"], decimals=0),
        ))
        self.quarters.set_rows([
            dict(q, quarter_label=tr("Q{quarter} {year}", quarter=q["quarter"], year=current))
            for q in annual["quarters"]
        ])

        trigger = fmt_money(annual["expert_trigger"], decimals=0)
        self.hints["expert"].setText(
            tr("On course for about {amount} or more this year: worth paying for one consultation.",
               amount=trigger)
            if annual["expert_suggested"] else
            tr("Suggested when on course for about {amount}. Not there at this pace.", amount=trigger)
        )

        saved = {
            r["item"]: r["done"]
            for r in self.book.db.rows("SELECT item, done FROM annual_review WHERE year = ?", [current])
        }
        for key, box in self.checks.items():
            box.blockSignals(True)
            box.setChecked(bool(saved.get(key)))
            box.blockSignals(False)

    def _on_check(self, key: str, on: bool) -> None:
        self.book.db.execute(
            "INSERT INTO annual_review (year, item, done) VALUES (?, ?, ?) "
            "ON CONFLICT (year, item) DO UPDATE SET done = excluded.done",
            [self._selected_year(), key, on],
        )
