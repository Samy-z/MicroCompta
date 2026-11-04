"""Deadlines worked out from the start date, and what to remind about.

The rules are in code and the dates they use are in Figures. ``build_deadlines`` is
pure; ``DeadlineBook`` adds what was marked done and what has already been notified.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..i18n import N_, fmt_date, month_name, tr
from . import clock
from .db import Database
from .figures import Figures
from .money import fmt_money
from .profile import Profile, load_profile

# Stored and compared as written here, translated when shown.
DECLARATION = N_("Declaration")
OPTION = N_("Option")
TAX = N_("Tax")
FILING = N_("Filing")
HOUSEKEEPING = N_("Housekeeping")


@dataclass(frozen=True)
class Deadline:
    key: str
    title: str
    due: date | None           # None: no fixed date (form 2042 C PRO)
    category: str
    note: str = ""
    remind_from: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    optional: bool = False     # a choice, not an obligation: passes quietly if not taken

    @property
    def sort_date(self) -> date:
        return self.due or self.remind_from or date.max


# -- date arithmetic ---------------------------------------------------------
def end_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def first_monthly_due(start: date) -> date:
    """End of the month following the first 3 months of activity.

    Start 03-06: the three months run to 06-05, so 07-31 (the official example). A start
    on the 1st gives a period ending on a month end: 03-01 runs to 05-31, so 06-30. Only
    the first case has an official example; the second follows the same wording.
    """
    three_months_end = add_months(start, 3) - timedelta(days=1)
    return end_of_month(add_months(three_months_end.replace(day=1), 1))


def _quarter_end(d: date) -> date:
    month = ((d.month - 1) // 3 + 1) * 3
    return end_of_month(date(d.year, month, 1))


def first_quarterly_due(start: date) -> date:
    """End of the month after the quarter that follows the start quarter (04-12: 10-31)."""
    following_quarter_end = _quarter_end(_quarter_end(start) + timedelta(days=1))
    return end_of_month(following_quarter_end + timedelta(days=1))


def _period_label(first: date, last: date) -> str:
    if first.year == last.year and first.month == last.month:
        return f"{month_name(first.month)} {first.year}"
    if first.year == last.year:
        return f"{month_name(first.month)}–{month_name(last.month)} {first.year}"
    return f"{month_name(first.month)} {first.year}–{month_name(last.month)} {last.year}"


def _declaration_note(fine: str) -> str:
    return tr(
        "File with URSSAF even at zero (\"Néant\"). A missed declaration costs {fine} "
        "plus a surcharge on contributions.", fine=fine,
    )


def turnover_declarations(start: date, frequency: str, until: date, fine: str) -> list[Deadline]:
    items = []
    note = _declaration_note(fine)
    if frequency == "quarterly":
        due = first_quarterly_due(start)
        first = start
        last = _quarter_end(_quarter_end(start) + timedelta(days=1))
        while due <= until:
            items.append(Deadline(
                f"declaration:{last.year}-Q{(last.month - 1) // 3 + 1}",
                tr("Turnover declaration: {period}", period=_period_label(first, last)),
                due, DECLARATION, note, period_start=first, period_end=last,
            ))
            first = last + timedelta(days=1)
            last = _quarter_end(first)
            due = end_of_month(last + timedelta(days=1))
    else:
        due = first_monthly_due(start)
        first = start
        last = end_of_month(add_months(due.replace(day=1), -1))
        while due <= until:
            items.append(Deadline(
                f"declaration:{last.year}-{last.month:02d}",
                tr("Turnover declaration: {period}", period=_period_label(first, last)),
                due, DECLARATION, note, period_start=first, period_end=last,
            ))
            first = last + timedelta(days=1)
            last = end_of_month(first)
            due = end_of_month(last + timedelta(days=1))
    return items


def build_deadlines(profile: Profile, figures: Figures, today: date,
                    horizon_days: int = 430) -> list[Deadline]:
    """Everything due from the start date up to the horizon, sorted by date."""
    until = today + timedelta(days=horizon_days)
    on = today
    items: list[Deadline] = [
        Deadline("ereporting", tr("E-reporting through a plateforme agréée"),
                 figures.date_value("ereporting_deadline", on), FILING,
                 tr("Choose a platform before then. This app does not do e-reporting.")),
        Deadline("vat_mention", tr("Check the art. 293 B reference on invoices"),
                 figures.date_value("vat_mention_tolerated_until", on), HOUSEKEEPING,
                 tr("F23208 says this reference is tolerated until this date. Re-read it and "
                    "update the mention in Settings if needed.")),
    ]
    start = profile.start_date
    if start is None:
        return sorted(items, key=lambda d: (d.sort_date, d.key))

    fine = fmt_money(figures.value("late_declaration_fine", on))
    items += turnover_declarations(start, profile.declaration_frequency, until, fine)

    if profile.declaration_frequency == "quarterly":
        items.append(Deadline(
            "declaration:option", tr("Ask URSSAF for quarterly declarations"),
            add_months(start, 1), OPTION,
            tr("The option must be taken within the month after the start of activity. To change "
               "back for a later year, ask before 31 October of the year before."),
        ))

    if profile.acre_enabled:
        days = int(figures.value("acre_request_days", start))
        items.append(Deadline(
            "acre:request", tr("ACRE request"), start + timedelta(days=days), OPTION,
            tr("Through the guichet unique, then the ACRE form in URSSAF messaging."),
        ))

    vl_note = tr(
        "Optional. Depends on the reference tax income of year N-2; with no French reference "
        "income, ask the SIE."
    )
    items.append(Deadline(
        "vl:creation", tr("Versement libératoire option, first year"),
        end_of_month(add_months(start.replace(day=1), 3)), OPTION, vl_note, optional=True,
    ))
    for year in range(start.year + 1, until.year + 2):
        due = figures.month_day("vl_next_year_md", year - 1)
        if start <= due <= until:
            items.append(Deadline(f"vl:{year}", tr("Versement libératoire option for {year}", year=year),
                                  due, OPTION, vl_note, optional=True))

    items.append(Deadline(
        "cfe:form", tr("CFE form 1447-C-SD"), figures.month_day("cfe_form_md", start.year), FILING,
        tr("Online through impots.gouv.fr, or by post to the SIE. Required even working from home."),
    ))
    # Nothing is owed in the first year, so the first payment is the year after.
    for year in range(start.year + 1, until.year + 1):
        due = figures.month_day("cfe_payment_md", year)
        if due <= until:
            threshold = fmt_money(figures.value("cfe_exempt_turnover", on), decimals=0)
            items.append(Deadline(
                f"cfe:pay:{year}", tr("CFE payment {year}", year=year), due, TAX,
                tr("Notice in your professional space on impots.gouv.fr. No CFE if {reference} "
                   "turnover was at most {threshold}. First taxable year: 50% off the base.",
                   reference=year - 2, threshold=threshold),
            ))

    # Form 2042 C PRO: the date is published each spring, so none is stored.
    for year in range(start.year, until.year + 1):
        remind = figures.month_day("tax_return_remind_md", year + 1)
        if remind <= until:
            items.append(Deadline(
                f"2042:{year}", tr("Form 2042 C PRO: declare {year} turnover", year=year), None, TAX,
                tr("Spring {next_year}. The date is published each year on impots.gouv.fr; "
                   "enter it here once known. The figure is on the Annual page.",
                   next_year=year + 1),
                remind_from=remind,
            ))

    for year in range(start.year + 1, until.year + 1):
        due = figures.month_day("figures_review_md", year)
        if due <= until:
            items.append(Deadline(
                f"figures:{year}", tr("Re-check the figures table for {year}", year=year), due, HOUSEKEEPING,
                tr("Rates and limits change. Add a row under Settings > Figures for anything new."),
            ))
    return sorted(items, key=lambda d: (d.sort_date, d.key))


# -- state -------------------------------------------------------------------
class DeadlineBook:
    SOON_DAYS = 14

    def __init__(self, db: Database, figures: Figures):
        self.db = db
        self.figures = figures

    def _state(self) -> dict[str, dict[str, Any]]:
        return {r["key"]: r for r in self.db.rows("SELECT * FROM deadline_state")}

    def items(self, today: date | None = None) -> list[dict[str, Any]]:
        today = today or clock.today()
        state = self._state()
        rows = []
        for d in build_deadlines(load_profile(self.db), self.figures, today):
            saved = state.get(d.key, {})
            due = saved.get("due_override") or d.due
            done = saved.get("done_at") is not None
            days_left = (due - today).days if due else None
            if done:
                status = "done"
            elif due is None:
                reached = d.remind_from is not None and today >= d.remind_from
                status = "due soon" if reached else "no date yet"
            elif days_left < 0:
                # A window that closed on an optional choice isn't something to chase.
                status = "passed" if d.optional else "overdue"
            elif days_left <= self.SOON_DAYS:
                status = "due soon"
            else:
                status = "upcoming"
            rows.append({
                "key": d.key,
                "title": d.title,
                "due": due,
                "days_left": days_left,
                "category": d.category,
                "note": d.note,
                "remind_from": d.remind_from,
                "period_start": d.period_start,
                "period_end": d.period_end,
                "status": status,
                "done": done,
                "fixed_date": d.due is not None,
            })
        rows.sort(key=lambda r: (r["due"] or r["remind_from"] or date.max, r["key"]))
        return rows

    def set_done(self, key: str, done: bool = True) -> None:
        self.db.execute(
            "INSERT INTO deadline_state (key, done_at) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET done_at = excluded.done_at",
            [key, clock.now() if done else None],
        )

    def set_date(self, key: str, due: date | None) -> None:
        """For a deadline with no fixed date, once the date is published."""
        self.db.execute(
            "INSERT INTO deadline_state (key, due_override) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET due_override = excluded.due_override",
            [key, due],
        )

    # -- reminders ----------------------------------------------------------
    def pending_reminders(self, today: date | None = None) -> list[dict[str, Any]]:
        """Items to notify now. Each threshold fires once, and a tighter one covers the
        looser ones, so starting the app late sends one message rather than a pile.

        Overdue items repeat weekly until they are marked done: a missed declaration
        costs money, and the tray may be the only thing that says so.
        """
        today = today or clock.today()
        profile = load_profile(self.db)
        thresholds = profile.reminder_thresholds()
        sent = {
            (r["key"], int(r["threshold"]))
            for r in self.db.rows("SELECT key, threshold FROM reminder_log")
        }
        pending = []
        for item in self.items(today):
            if item["done"] or item["status"] == "passed":
                continue
            due = item["due"]
            if due is None:
                if item["remind_from"] and today >= item["remind_from"] and (item["key"], 0) not in sent:
                    pending.append({**item, "_thresholds": [0], "_message": item["title"]})
                continue
            days_left = (due - today).days
            if days_left < 0:
                week = (-days_left - 1) // 7 + 1
                code = -week
                if (item["key"], code) not in sent:
                    pending.append({**item, "_thresholds": [code], "_message": tr(
                        "Overdue: {title} (was due {date})", title=item["title"], date=fmt_date(due),
                    )})
                continue
            reached = [t for t in thresholds if days_left <= t]
            fresh = [t for t in reached if (item["key"], t) not in sent]
            if fresh:
                when = tr("today") if days_left == 0 else tr("in {days} day(s)", days=days_left)
                pending.append({**item, "_thresholds": fresh, "_message": tr(
                    "{title}: due {when} ({date})", title=item["title"], when=when, date=fmt_date(due),
                )})
        return pending

    def mark_reminded(self, item: dict[str, Any]) -> None:
        with self.db.transaction():
            for threshold in item["_thresholds"]:
                self.db.execute(
                    "INSERT INTO reminder_log (key, threshold, sent_at) VALUES (?, ?, ?) "
                    "ON CONFLICT DO NOTHING",
                    [item["key"], threshold, clock.now()],
                )
