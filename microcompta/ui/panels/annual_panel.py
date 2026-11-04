"""The annual page. Not a bilan: a micro-entrepreneur doesn't have one."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from ...core import clock
from ...core.book import Book
from ...core.errors import MissingFigure
from ...core.ledger_policy import UNCONFIRMED
from ...core.money import fmt_money
from ...core.open_questions import OPEN_QUESTIONS
from ..models import Col
from ..widgets.table_view import DataTable
from .common import (
    Banner, StatRow, card_frame, dim_label, fill_years, heading, scroll_page, year_combo,
)

CHECKLIST = (
    ("vl", "Versement libératoire: keep or change for next year?",
     "The option for next year closes on the date in Deadlines. Depends on your reference tax income."),
    ("regime", "Micro regime, real regime or a company?",
     "Compare your real costs with the flat allowance. The real regime is an option by written "
     "notice to the SIE."),
    ("expert", "One paid consultation with an expert-comptable?",
     ""),
    ("limits", "Limits: any year over, or a second year running?",
     "See the Limits tab for the ceiling, the VAT franchise and the bank account rule."),
    ("figures", "Figures: anything new for next year?",
     "Rates and limits change. Add a row under Settings > Figures."),
    ("backup", "Backup: everything uploaded, and a copy you can open?",
     "See the Backup tab. Open one PDF from Drive to be sure."),
)


class AnnualPanel(QWidget):
    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(heading("Annual review"))
        self.year = year_combo([], clock.today().year)
        self.year.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.year)
        top.addStretch(1)
        layout.addLayout(top)

        layout.addWidget(Banner(
            "info",
            "This page reminds and adds up; it does not give tax advice. A micro-entrepreneur has "
            "no annual bilan: the records are the livre des recettes and the invoices, kept 10 years.",
        ))
        self.problem = Banner("bad")
        layout.addWidget(self.problem)

        self.stats = StatRow([
            ("turnover", "Turnover", "Received in the year, under the current setting."),
            ("contributions", "Contributions", "At the rate in force on each payment's date."),
            ("form", "Form 2042 C PRO", "The year's turnover to report, to the euro."),
            ("base", "Taxable base", "Information only: the tax office applies the allowance."),
            ("run", "Run-rate", ""),
        ])
        layout.addWidget(self.stats)

        self.form_note = dim_label("")
        layout.addWidget(self.form_note)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)
        left_lay.addWidget(heading("Totals every 3 months", "h2"))
        self.quarters = DataTable([
            Col("label", "Quarter", width=90),
            Col("entries", "Entries", "int", 60),
            Col("eur_gross", "EUR gross", "eur", 100),
            Col("fee_eur", "Fees", "eur", 90),
            Col("net_eur", "Net credited", "eur", 100),
            Col("counted", "Turnover", "eur", 100),
        ], toolbar=False)
        self.quarters.setMinimumHeight(135)
        left_lay.addWidget(self.quarters)
        left_lay.addWidget(heading("Still open", "h2"))
        self.questions = DataTable([
            Col("topic", "Question", width=190),
            Col("who", "Who answers", width=78),
            Col("status", "Status", width=120),
            Col("detail", "Detail", width=330),
        ], toolbar=False)
        self.questions.setMinimumHeight(260)
        self.questions.set_wrapped()
        self.questions.set_rows(OPEN_QUESTIONS)
        left_lay.addWidget(self.questions, 1)
        splitter.addWidget(left)

        right = card_frame()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 10, 12, 10)
        right_lay.setSpacing(6)
        right_lay.addWidget(heading("Review checklist", "h2"))
        self.checks: dict[str, QCheckBox] = {}
        self.hints: dict[str, QLabel] = {}
        for key, text, hint in CHECKLIST:
            box = QCheckBox(text)
            box.toggled.connect(lambda on, k=key: self._on_check(k, on))
            self.checks[key] = box
            right_lay.addWidget(box)
            label = dim_label(hint)
            label.setContentsMargins(20, 0, 0, 4)
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
        self.form_note.setText(
            f"The 2042 C PRO figure follows the current turnover setting ({UNCONFIRMED}). The box "
            "depends on your activity and options: see the form's notice. Taxable base: "
            f"{annual['allowance_rate'] * 100:.0f}% allowance, minimum "
            f"{fmt_money(annual['allowance_min'], decimals=0)}, for information."
        )
        self.quarters.set_rows(annual["quarters"])

        trigger = fmt_money(annual["expert_trigger"], decimals=0)
        self.hints["expert"].setText(
            f"On course for about {trigger} or more this year: worth paying for one consultation."
            if annual["expert_suggested"] else
            f"Suggested when on course for about {trigger}. Not there at this pace."
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
