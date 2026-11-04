"""Limits, contributions and the yearly figures.

Plain functions for the arithmetic, and ``Limits`` to assemble them for a year. All
amounts come from Figures, and every sentence a card shows is written here, so what
the dashboard says is what the tests check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import clock
from .clients import EXCLUSION_LABEL
from .figures import Figures
from .ledger import Ledger
from .ledger_policy import TurnoverPolicy, counted_eur
from .money import ZERO, fmt_money, round_euro, round_money
from .profile import Profile


# -- arithmetic --------------------------------------------------------------
def days_active(start: date | None, year: int) -> int:
    """Days of activity in ``year``, both ends included."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    if start is None or start <= first:
        return (last - first).days + 1
    if start > last:
        return 0
    return (last - start).days + 1


def prorate(amount: Decimal, start: date | None, year: int, basis: Decimal) -> Decimal:
    """A limit in the creation year: amount x days / basis, to the euro.

    Never above the full amount: 1 January of a leap year is 366 days over a 365 basis.
    """
    if start is None or start.year != year:
        return amount
    days = days_active(start, year)
    if days >= basis:
        return amount
    return round_euro(amount * days / basis)


def run_rate(ytd: Decimal, start: date | None, year: int, as_of: date) -> Decimal:
    """Year-to-date turnover carried at the same pace to 31 December."""
    first_active = max(date(year, 1, 1), start) if start else date(year, 1, 1)
    last = date(year, 12, 31)
    if as_of >= last or start and start.year > year:
        return ytd
    elapsed = (as_of - first_active).days + 1
    if elapsed <= 0:
        return ZERO
    total = (last - first_active).days + 1
    return round_money(ytd * total / elapsed)


def acre_end(start: date) -> date:
    """End of the 3rd civil quarter after the quarter of the start date."""
    quarter = (start.month - 1) // 3 + 1          # 1..4
    target = quarter + 3
    year = start.year + (target - 1) // 4
    target = (target - 1) % 4 + 1
    month_after = target * 3 + 1
    if month_after > 12:
        return date(year, 12, 31)
    return date(year, month_after, 1) - timedelta(days=1)


def taxable_base(turnover: Decimal, allowance_rate: Decimal, allowance_min: Decimal) -> Decimal:
    """Turnover less the flat allowance, for information. The allowance has a minimum,
    and the base cannot go below zero."""
    if turnover <= 0:
        return ZERO
    allowance = max(turnover * allowance_rate, allowance_min)
    return round_money(max(turnover - allowance, Decimal(0)))


@dataclass(frozen=True)
class RateInfo:
    rate: Decimal
    label: str
    acre_applied: bool
    vl_applied: bool


def contribution_rate(on: date, profile: Profile, figures: Figures) -> RateInfo:
    """The share of turnover to set aside for a payment received on ``on``."""
    activity = profile.activity
    base = figures.value(f"rate_{activity}", on)
    with_vl = figures.value(f"rate_{activity}_vl", on)
    social = base
    acre = bool(
        profile.acre_enabled and profile.start_date and on <= acre_end(profile.start_date)
    )
    if acre:
        social = base * figures.value("acre_multiplier", profile.start_date)
    rate = social + (with_vl - base) if profile.vl_enabled else social
    parts = [activity.upper()]
    if acre:
        parts.append("ACRE")
    if profile.vl_enabled:
        parts.append("VL")
    return RateInfo(rate=rate, label=" + ".join(parts), acre_applied=acre,
                    vl_applied=profile.vl_enabled)


# -- report ------------------------------------------------------------------
@dataclass
class LimitCard:
    key: str
    title: str
    value: Decimal
    limit: Decimal
    level: str                 # ok | near | warn | over | info
    headline: str
    details: list[str] = field(default_factory=list)
    projection: Decimal | None = None
    ticks: list[tuple[Decimal, str]] = field(default_factory=list)
    has_bar: bool = True       # False when there is nothing yet to compare with the limit


@dataclass
class PeriodRow:
    label: str
    start: date
    end: date
    turnover: Decimal
    rates: str
    set_aside: Decimal
    entries: int


@dataclass
class LimitsReport:
    year: int
    as_of: date
    ytd: Decimal
    projection: Decimal
    days_elapsed: int
    days_total: int
    ceiling: LimitCard
    vat: LimitCard
    bank: LimitCard
    cfe: LimitCard
    set_aside: Decimal
    periods: list[PeriodRow]
    acre_until: date | None


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Limits:
    def __init__(self, ledger: Ledger, figures: Figures, profile_loader: Any):
        self.ledger = ledger
        self.figures = figures
        self.profile_loader = profile_loader

    # -- totals -------------------------------------------------------------
    def turnover(self, year: int, policy: TurnoverPolicy | None = None,
                 france_only: bool = False, until: date | None = None) -> Decimal:
        policy = policy or self.profile_loader().policy
        total = ZERO
        for e in self.ledger.entries(year):
            if france_only and not e["taxed_in_france"]:
                continue
            if until is not None and e["received_on"] > until:
                continue
            total += counted_eur(e, policy)
        return total

    def turnover_between(self, start: date, end: date, policy: TurnoverPolicy | None = None) -> Decimal:
        """Counted turnover received in a date range, both ends included."""
        policy = policy or self.profile_loader().policy
        total = ZERO
        for year in range(start.year, end.year + 1):
            for e in self.ledger.entries(year):
                if start <= e["received_on"] <= end:
                    total += counted_eur(e, policy)
        return total

    def _ceiling_for(self, year: int, start: date | None) -> Decimal:
        on = date(year, 1, 1)
        full = self.figures.value("micro_ceiling", on)
        basis = self.figures.value("proration_days_basis", on)
        return prorate(full, start, year, basis)

    def _is_over_ceiling(self, year: int, profile: Profile) -> bool:
        if profile.start_date and year < profile.start_date.year:
            return False
        turnover = self.turnover(year, profile.policy)
        return turnover > 0 and turnover > self._ceiling_for(year, profile.start_date)

    # -- cards --------------------------------------------------------------
    def _ceiling_card(self, year: int, ytd: Decimal, projection: Decimal, profile: Profile,
                      as_of: date) -> LimitCard:
        start = profile.start_date
        on = date(year, 1, 1)
        limit = self._ceiling_for(year, start)
        full = self.figures.value("micro_ceiling", on)
        near = self.figures.value("near_limit_ratio", on)
        over_now = ytd > limit
        over_prev = self._is_over_ceiling(year - 1, profile)
        over_prev2 = self._is_over_ceiling(year - 2, profile)

        details: list[str] = []
        if start and start.year == year and limit != full:
            basis = self.figures.value("proration_days_basis", on)
            details.append(
                f"First year, prorated: {fmt_money(full, decimals=0)} × "
                f"{days_active(start, year)} / {basis} = {fmt_money(limit, decimals=0)}."
            )
        if over_prev and over_prev2:
            level, headline = "over", (
                f"Over in {year - 2} and {year - 1}: the micro regime ended on 1 January {year}."
            )
        elif over_now and over_prev:
            level, headline = "over", (
                f"Over two years running: you leave the micro regime on 1 January {year + 1}."
            )
        elif over_now:
            level, headline = "warn", (
                "Over the ceiling this year. One year over is allowed; "
                f"a second in {year + 1} ends the regime on 1 January {year + 2}."
            )
        elif over_prev and projection > limit:
            level, headline = "warn", (
                f"Over last year and on course to be over again: that ends the regime on "
                f"1 January {year + 1}."
            )
        elif projection > limit:
            level, headline = "warn", "On course to pass the ceiling by year-end at this pace."
        elif limit and ytd >= limit * near:
            level, headline = "near", f"Above {near * 100:.0f}% of the ceiling."
        else:
            level, headline = "ok", "Within the ceiling."
        if (over_now or over_prev) and start and year - 1 <= start.year <= year:
            details.append(
                "Whether a prorated first year counts as a year over isn't stated in the "
                "official sources read."
            )
        return LimitCard("ceiling", "Micro ceiling", ytd, limit, level, headline, details,
                         projection=projection if as_of.year == year else None)

    def _vat_limits(self, year: int, start: date | None) -> tuple[Decimal, Decimal]:
        on = date(year, 1, 1)
        basis = self.figures.value("proration_days_basis", on)
        return (prorate(self.figures.value("vat_base", on), start, year, basis),
                prorate(self.figures.value("vat_upper", on), start, year, basis))

    def _crossing_date(self, year: int, limit: Decimal, policy: TurnoverPolicy) -> date | None:
        running = ZERO
        for e in self.ledger.entries(year):
            if not e["taxed_in_france"]:
                continue
            running += counted_eur(e, policy)
            if running > limit:
                return e["received_on"]
        return None

    def _vat_card(self, year: int, profile: Profile) -> LimitCard:
        start = profile.start_date
        policy = profile.policy
        counted = self.turnover(year, policy, france_only=True)
        everything = self.turnover(year, policy)
        excluded = everything - counted
        base, upper = self._vat_limits(year, start)

        details: list[str] = []
        if start and start.year == year:
            details.append(
                f"Creation year: limits adjusted by {days_active(start, year)} days of activity."
            )
        if excluded:
            details.append(
                f"{fmt_money(excluded)} of turnover excluded: clients marked as not taxed in "
                f"France. A non-EU business client is excluded, {EXCLUSION_LABEL}."
            )

        # Only look up last year's limit if there was turnover to test against it, so a
        # first year on record never needs a figure from before it.
        previous = self.turnover(year - 1, policy, france_only=True)
        ended_prior = previous > 0 and previous > self._vat_limits(year - 1, start)[0]

        crossing = self._crossing_date(year, upper, policy) if counted > upper else None
        if crossing:
            level, headline = "over", (
                f"Above the upper limit: VAT applies from {crossing.isoformat()}, the day it was "
                "crossed. Tell the SIE and stop using the art. 293 B mention."
            )
        elif ended_prior:
            level, headline = "over", (
                f"Above the base limit in {year - 1}: the franchise ended on 1 January {year}."
            )
        elif counted > base:
            level, headline = "warn", (
                f"Above the base limit: the franchise ends on 1 January {year + 1}."
            )
        else:
            near = self.figures.value("near_limit_ratio", date(year, 1, 1))
            if base and counted >= base * near:
                level, headline = "near", f"Above {near * 100:.0f}% of the base limit."
            else:
                level, headline = "ok", "Within the franchise."
        return LimitCard("vat", "VAT franchise (turnover taxed in France)", counted, upper, level,
                         headline, details, ticks=[(base, "base")])

    def _bank_card(self, year: int, ytd: Decimal, profile: Profile) -> LimitCard:
        limit = self.figures.value("bank_account_threshold", date(year, 1, 1))
        prev = self.turnover(year - 1, profile.policy)
        if ytd > limit and prev > limit:
            level, headline = "over", (
                f"Above {fmt_money(limit, decimals=0)} two years running: a separate bank "
                "account is mandatory."
            )
        elif ytd > limit:
            level, headline = "near", (
                f"Above {fmt_money(limit, decimals=0)} this year. A second year above makes a "
                "separate bank account mandatory."
            )
        else:
            level, headline = "ok", "No separate account required yet."
        details = [f"{year - 1} turnover: {fmt_money(prev)}."]
        return LimitCard("bank", "Separate bank account", ytd, limit, level, headline, details)

    def _cfe_card(self, year: int, profile: Profile) -> LimitCard:
        limit = self.figures.value("cfe_exempt_turnover", date(year, 1, 1))
        start = profile.start_date
        if start and year == start.year:
            return LimitCard("cfe", "CFE", ZERO, limit, "info",
                             "Nothing is owed in the first year of activity.",
                             ["The CFE form is still due: see Deadlines."], has_bar=False)
        reference = self.turnover(year - 2, profile.policy)
        if start and year - 2 < start.year:
            return LimitCard(
                "cfe", "CFE", ZERO, limit, "info",
                f"No {year - 2} turnover to compare with {fmt_money(limit, decimals=0)}.",
                ["First taxable year: 50% off the base. A first-year turnover may be prorated "
                 "to 12 months for this test."],
                has_bar=False,
            )
        if reference <= limit:
            level, headline = "ok", (
                f"{year - 2} turnover at or below {fmt_money(limit, decimals=0)}: no CFE owed "
                f"for {year}."
            )
        else:
            level, headline = "info", (
                f"{year - 2} turnover above {fmt_money(limit, decimals=0)}: CFE is owed for "
                f"{year}. The amount is on your notice."
            )
        return LimitCard("cfe", f"CFE ({year - 2} turnover)", reference, limit, level, headline)

    # -- periods ------------------------------------------------------------
    def periods(self, year: int, profile: Profile, by: str | None = None) -> list[PeriodRow]:
        by = by or ("quarter" if profile.declaration_frequency == "quarterly" else "month")
        spans: list[tuple[str, date, date]] = []
        if by == "quarter":
            for q in range(4):
                first = date(year, q * 3 + 1, 1)
                last = (date(year + 1, 1, 1) if q == 3 else date(year, q * 3 + 4, 1)) - timedelta(days=1)
                spans.append((f"Q{q + 1} {year}", first, last))
        else:
            for m in range(1, 13):
                first = date(year, m, 1)
                last = (date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)) - timedelta(days=1)
                spans.append((f"{MONTHS[m - 1]} {year}", first, last))
        entries = self.ledger.entries(year)
        rows = []
        for label, first, last in spans:
            in_span = [e for e in entries if first <= e["received_on"] <= last]
            turnover = ZERO
            set_aside = ZERO
            rates: dict[str, Decimal] = {}
            for e in in_span:
                amount = counted_eur(e, profile.policy)
                info = contribution_rate(e["received_on"], profile, self.figures)
                turnover += amount
                set_aside += round_money(amount * info.rate)
                rates[info.label] = info.rate
            rate_text = " / ".join(f"{r * 100:.1f}%" for r in rates.values())
            rows.append(PeriodRow(label, first, last, turnover, rate_text, set_aside, len(in_span)))
        return rows

    def set_aside_for(self, entry: dict[str, Any], profile: Profile) -> Decimal:
        """What to put aside for one payment."""
        info = contribution_rate(entry["received_on"], profile, self.figures)
        return round_money(counted_eur(entry, profile.policy) * info.rate)

    # -- the report ---------------------------------------------------------
    def report(self, year: int, as_of: date | None = None) -> LimitsReport:
        profile = self.profile_loader()
        as_of = as_of or clock.today()
        reference = min(as_of, date(year, 12, 31))
        ytd = self.turnover(year, profile.policy, until=reference)
        projection = run_rate(ytd, profile.start_date, year, reference)
        total_days = days_active(profile.start_date, year)
        first_active = max(date(year, 1, 1), profile.start_date) if profile.start_date else date(year, 1, 1)
        elapsed = max(0, min((reference - first_active).days + 1, total_days))
        periods = self.periods(year, profile)
        relevant = [
            p for p in periods
            if p.entries or (p.start <= reference and (not profile.start_date or p.end >= profile.start_date))
        ]
        return LimitsReport(
            year=year,
            as_of=reference,
            ytd=ytd,
            projection=projection,
            days_elapsed=elapsed,
            days_total=total_days,
            ceiling=self._ceiling_card(year, ytd, projection, profile, reference),
            vat=self._vat_card(year, profile),
            bank=self._bank_card(year, ytd, profile),
            cfe=self._cfe_card(year, profile),
            set_aside=sum((p.set_aside for p in periods), ZERO),
            periods=relevant,
            acre_until=acre_end(profile.start_date) if profile.acre_enabled and profile.start_date else None,
        )

    def annual(self, year: int, as_of: date | None = None) -> dict[str, Any]:
        """What the Annual page shows. No advice, only the arithmetic."""
        profile = self.profile_loader()
        as_of = as_of or clock.today()
        report = self.report(year, as_of)
        on = date(year, 1, 1)
        turnover = self.turnover(year, profile.policy)
        base = taxable_base(
            turnover,
            self.figures.value(f"allowance_{profile.activity}", on),
            self.figures.value("allowance_min", on),
        )
        trigger = self.figures.value("expert_review_trigger", on)
        return {
            "year": year,
            "turnover": turnover,
            "contributions": report.set_aside,
            "form_2042_figure": round_euro(turnover),
            "taxable_base": base,
            "allowance_rate": self.figures.value(f"allowance_{profile.activity}", on),
            "allowance_min": self.figures.value("allowance_min", on),
            "projection": report.projection,
            "expert_trigger": trigger,
            "expert_suggested": max(report.projection, turnover) >= trigger,
            "quarters": self.ledger.quarter_totals(year, profile.policy),
        }
