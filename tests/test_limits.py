"""Proration, limits, contributions. Expected values are the official examples."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from conftest import pay
from microcompta.core.errors import MissingFigure, ValidationError
from microcompta.core.limits import (
    acre_end, contribution_rate, days_active, prorate, run_rate, taxable_base,
)
from microcompta.core.profile import Profile


# -- proration ---------------------------------------------------------------
def test_urssaf_example_start_on_march_first():
    """URSSAF: a start on 03-01 gives 83,600 x 306 / 365 = 70,087."""
    assert days_active(date(2027, 3, 1), 2027) == 306
    assert prorate(D(83600), date(2027, 3, 1), 2027, D(365)) == D(70087)


@pytest.mark.parametrize("limit, expected", [(D(37500), D(20856)), (D(41250), D(22942))])
def test_bofip_vat_example_start_on_june_twelfth(limit, expected):
    """BOFiP s.290 and s.295: 12 June is 203 days, giving 20,856 and 22,942."""
    assert days_active(date(2026, 6, 12), 2026) == 203
    assert prorate(limit, date(2026, 6, 12), 2026, D(365)) == expected


def test_full_amount_after_the_creation_year():
    assert prorate(D(83600), date(2027, 3, 1), 2028, D(365)) == D(83600)


def test_january_first_is_never_above_the_full_amount_even_in_a_leap_year():
    assert days_active(date(2028, 1, 1), 2028) == 366
    assert prorate(D(83600), date(2028, 1, 1), 2028, D(365)) == D(83600)


def test_no_start_date_means_no_proration():
    assert prorate(D(83600), None, 2027, D(365)) == D(83600)


def test_days_active_edges():
    assert days_active(date(2027, 12, 31), 2027) == 1
    assert days_active(date(2028, 1, 5), 2027) == 0
    assert days_active(None, 2027) == 365


# -- run rate ----------------------------------------------------------------
def test_run_rate_scales_from_the_days_active_in_the_year():
    # Start 07-01: 184 days to year-end; 92 elapsed by 09-30.
    assert run_rate(D(10000), date(2027, 7, 1), 2027, date(2027, 9, 30)) == D("20000.00")


def test_run_rate_is_the_actual_figure_once_the_year_is_over():
    assert run_rate(D(12345), date(2027, 1, 1), 2027, date(2028, 3, 1)) == D(12345)


# -- ACRE --------------------------------------------------------------------
@pytest.mark.parametrize("start, end", [
    (date(2026, 9, 3), date(2027, 6, 30)),   # the official example
    (date(2026, 11, 10), date(2027, 9, 30)),
    (date(2027, 1, 15), date(2027, 12, 31)),
    (date(2027, 4, 2), date(2028, 3, 31)),
])
def test_acre_runs_to_the_end_of_the_third_civil_quarter_after_the_start(start, end):
    assert acre_end(start) == end


# -- rates -------------------------------------------------------------------
@pytest.mark.parametrize("activity, vl, acre, on, expected", [
    ("bnc", False, False, date(2027, 3, 1), "0.256"),
    ("bic", False, False, date(2027, 3, 1), "0.212"),
    ("bnc", True, False, date(2027, 3, 1), "0.278"),
    ("bic", True, False, date(2027, 3, 1), "0.229"),
    ("bnc", False, True, date(2027, 3, 1), "0.192"),   # 75% of 25.6
    ("bic", False, True, date(2027, 3, 1), "0.159"),   # 75% of 21.2
    ("bnc", False, True, date(2028, 3, 1), "0.256"),   # ACRE is over by then
])
def test_contribution_rates(book, activity, vl, acre, on, expected):
    profile = Profile(start_date=date(2026, 11, 2), activity=activity, vl_enabled=vl,
                      acre_enabled=acre)
    assert contribution_rate(on, profile, book.figures).rate == D(expected)


def test_acre_ends_on_the_last_day_of_the_quarter_not_the_next(book):
    profile = Profile(start_date=date(2026, 11, 2), activity="bnc", acre_enabled=True)
    assert contribution_rate(date(2027, 9, 30), profile, book.figures).rate == D("0.192")
    assert contribution_rate(date(2027, 10, 1), profile, book.figures).rate == D("0.256")


def test_rates_follow_effective_dates_without_a_code_change(book):
    book.figures.upsert("rate_bnc", date(2028, 1, 1), "0.30", "test")
    profile = Profile(start_date=date(2026, 11, 2), activity="bnc")
    assert contribution_rate(date(2027, 12, 31), profile, book.figures).rate == D("0.256")
    assert contribution_rate(date(2028, 1, 1), profile, book.figures).rate == D("0.30")


def test_a_date_before_any_figure_is_an_error_not_a_guess(book):
    with pytest.raises(MissingFigure):
        book.figures.value("rate_bnc", date(2020, 1, 1))


def test_seed_never_overwrites_an_edit(book):
    book.figures.upsert("micro_ceiling", date(2026, 1, 1), "90000", "my edit")
    book.figures.seed()
    assert book.figures.value("micro_ceiling", date(2027, 1, 1)) == D(90000)


@pytest.mark.parametrize("key, value", [("micro_ceiling", "lots"), ("cfe_payment_md", "13-40"),
                                        ("ereporting_deadline", "soon")])
def test_figures_refuse_values_that_dont_fit_their_unit(book, key, value):
    with pytest.raises(ValidationError):
        book.figures.upsert(key, date(2030, 1, 1), value)


# -- allowance ---------------------------------------------------------------
@pytest.mark.parametrize("turnover, expected", [
    (D(50000), D("33000.00")),   # 34% allowance
    (D(500), D("195.00")),       # the 305 minimum bites: 34% would be 170
    (D(100), D("0.00")),         # never below zero
    (D(0), D("0.00")),
])
def test_taxable_base(turnover, expected):
    assert taxable_base(turnover, D("0.34"), D(305)) == expected


# -- cards -------------------------------------------------------------------
def _setup(book, identity, start, **changes):
    identity.start_date = start
    for key, value in changes.items():
        setattr(identity, key, value)
    book.save_profile(identity)


def test_ceiling_card_prorates_and_says_how(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2027, 3, 1))
    pinned_today(date(2027, 6, 30))
    pay(book, client_id, date(2027, 4, 1), "12500", "1.25")
    card = book.limits.report(2027).ceiling
    assert card.limit == D(70087)
    assert card.value == D("10000.00")
    assert card.level == "ok"
    assert "306" in card.details[0] and "70,087" in card.details[0]


def test_ceiling_warns_when_the_run_rate_passes_it(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2027, 1, 1))
    pinned_today(date(2027, 3, 31))
    pay(book, client_id, date(2027, 3, 1), "37500", "1.25")  # 30,000 EUR in 90 days
    report = book.limits.report(2027)
    assert report.projection > D(83600)
    assert report.ceiling.level == "warn"
    assert "pace" in report.ceiling.headline


def test_one_year_over_is_allowed_and_says_so(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 11, 2))
    pinned_today(date(2027, 12, 31))
    pay(book, client_id, date(2027, 6, 1), "125000", "1.25")  # 100,000 EUR
    card = book.limits.report(2027).ceiling
    assert card.level == "warn"
    assert "One year over is allowed" in card.headline


def test_two_consecutive_years_over_leaves_the_regime_on_january_first(
        book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2028, 12, 31))
    pay(book, client_id, date(2027, 6, 1), "125000", "1.25")
    pay(book, client_id, date(2028, 6, 1), "125000", "1.25")
    card = book.limits.report(2028).ceiling
    assert card.level == "over"
    assert "1 January 2029" in card.headline


def test_two_years_over_with_one_year_between_is_not_consecutive(
        book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2029, 12, 31))
    pay(book, client_id, date(2027, 6, 1), "125000", "1.25")
    pay(book, client_id, date(2029, 6, 1), "125000", "1.25")
    card = book.limits.report(2029).ceiling
    assert card.level == "warn"
    assert "One year over" in card.headline


def test_vat_counts_only_clients_taxed_in_france(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2027, 12, 31))
    french = book.clients.add(name="Client FR", address="Paris", currency="EUR", taxed_in_france=True)
    pay(book, client_id, date(2027, 2, 1), "62500", "1.25")  # 50,000 EUR, excluded
    book.ledger.record_payment(received_on=date(2027, 3, 1), client_id=french, description="Work",
                               amount_gross="5000", fx_rate="1", net_credited="5000",
                               payment_method="Bank transfer")
    card = book.limits.report(2027).vat
    assert card.value == D("5000.00")
    assert card.level == "ok"
    assert any("probably; SIE to confirm" in d for d in card.details)


def test_vat_above_base_ends_the_franchise_next_january(book, identity, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2027, 12, 31))
    fr = book.clients.add(name="FR", address="Paris", currency="EUR", taxed_in_france=True)
    book.ledger.record_payment(received_on=date(2027, 3, 1), client_id=fr, description="Work",
                               amount_gross="38000", fx_rate="1", net_credited="38000",
                               payment_method="Bank transfer")
    card = book.limits.report(2027).vat
    assert card.level == "warn"
    assert "1 January 2028" in card.headline


def test_vat_above_upper_applies_from_the_day_of_crossing(book, identity, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2027, 12, 31))
    fr = book.clients.add(name="FR", address="Paris", currency="EUR", taxed_in_france=True)
    for on, amount in ((date(2027, 3, 1), "30000"), (date(2027, 5, 20), "15000")):
        book.ledger.record_payment(received_on=on, client_id=fr, description="Work",
                                   amount_gross=amount, fx_rate="1", net_credited=amount,
                                   payment_method="Bank transfer")
    card = book.limits.report(2027).vat
    assert card.level == "over"
    assert "2027-05-20" in card.headline


def test_vat_creation_year_uses_the_adjusted_limits(book, identity, pinned_today):
    """BOFiP s.295: between the adjusted limits, the franchise ends on 1 January."""
    _setup(book, identity, date(2026, 6, 12))
    pinned_today(date(2026, 12, 31))
    fr = book.clients.add(name="FR", address="Paris", currency="EUR", taxed_in_france=True)
    book.ledger.record_payment(received_on=date(2026, 9, 1), client_id=fr, description="Work",
                               amount_gross="21000", fx_rate="1", net_credited="21000",
                               payment_method="Bank transfer")
    card = book.limits.report(2026).vat
    assert card.limit == D(22942)
    assert card.ticks[0][0] == D(20856)
    assert card.level == "warn"
    assert "1 January 2027" in card.headline


def test_vat_second_year_after_passing_the_adjusted_base_shows_the_franchise_ended(
        book, identity, pinned_today):
    _setup(book, identity, date(2026, 6, 12))
    pinned_today(date(2027, 2, 1))
    fr = book.clients.add(name="FR", address="Paris", currency="EUR", taxed_in_france=True)
    book.ledger.record_payment(received_on=date(2026, 9, 1), client_id=fr, description="Work",
                               amount_gross="21000", fx_rate="1", net_credited="21000",
                               payment_method="Bank transfer")
    card = book.limits.report(2027).vat
    assert card.level == "over"
    assert "1 January 2027" in card.headline


def test_bank_account_needs_two_consecutive_years(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2028, 12, 31))
    pay(book, client_id, date(2027, 6, 1), "15000", "1.25")   # 12,000
    assert book.limits.report(2027).bank.level == "near"
    pay(book, client_id, date(2028, 6, 1), "15000", "1.25")
    card = book.limits.report(2028).bank
    assert card.level == "over"
    assert "mandatory" in card.headline


def test_cfe_card_uses_turnover_from_two_years_before(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 5))
    pinned_today(date(2029, 6, 1))
    pay(book, client_id, date(2026, 6, 1), "5000", "1.25")   # 4,000: at most 5,000
    pay(book, client_id, date(2027, 6, 1), "12500", "1.25")  # 10,000: above
    assert "Nothing is owed" in book.limits.report(2026).cfe.headline
    assert "no CFE owed" in book.limits.report(2028).cfe.headline
    assert "CFE is owed" in book.limits.report(2029).cfe.headline


def test_set_aside_per_payment_and_period(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 11, 2), acre_enabled=True)
    pinned_today(date(2027, 6, 30))
    seq = pay(book, client_id, date(2027, 2, 10), "1250", "1.25")   # 1,000 EUR
    entry = book.ledger.get(seq)
    profile = book.profile()
    assert book.limits.set_aside_for(entry, profile) == D("192.00")
    february = [p for p in book.limits.periods(2027, profile) if p.label == "Feb 2027"][0]
    assert february.set_aside == D("192.00")
    assert february.rates == "19.2%"


def test_annual_page_arithmetic(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 5))
    pinned_today(date(2027, 12, 31))
    pay(book, client_id, date(2027, 2, 10), "12500", "1.25")   # 10,000 EUR
    annual = book.limits.annual(2027)
    assert annual["turnover"] == D("10000.00")
    assert annual["contributions"] == D("2560.00")
    assert annual["form_2042_figure"] == D(10000)
    assert annual["taxable_base"] == D("6600.00")
    assert annual["expert_suggested"] is False


def test_annual_page_suggests_an_expert_on_course_for_the_trigger(
        book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 1, 5))
    pinned_today(date(2027, 3, 31))
    pay(book, client_id, date(2027, 2, 10), "20000", "1.25")   # 16,000 in 90 days: about 65,000
    assert book.limits.annual(2027)["expert_suggested"] is True


def test_missing_figure_for_a_first_year_with_no_prior_turnover_does_not_break_the_report(
        book, identity, client_id, pinned_today):
    """2026 is the first year with figures, so nothing may look up 2025."""
    _setup(book, identity, date(2026, 1, 1))
    pinned_today(date(2026, 12, 31))
    pay(book, client_id, date(2026, 6, 1), "1250", "1.25")
    assert book.limits.report(2026).ytd == D("1000.00")


def test_periods_start_at_the_start_date_and_stop_at_today(book, identity, client_id, pinned_today):
    _setup(book, identity, date(2026, 7, 6))
    pinned_today(date(2026, 11, 4))
    pay(book, client_id, date(2026, 7, 10), "1250", "1.25")
    labels = [p.label for p in book.limits.report(2026).periods]
    assert labels == ["Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026"]


def test_cfe_card_shows_no_bar_with_nothing_to_compare(book, identity, pinned_today):
    _setup(book, identity, date(2026, 7, 6))
    pinned_today(date(2026, 11, 4))
    assert book.limits.report(2026).cfe.has_bar is False
    assert book.limits.report(2027).cfe.has_bar is False
    assert book.limits.report(2028).cfe.has_bar is True


def test_acre_multiplier_follows_the_start_date_not_the_payment_date(book):
    """Created before 2026-07-01: half the rate. From that date: 75%. F11677."""
    on = date(2026, 8, 3)
    before = Profile(start_date=date(2026, 3, 2), activity="bnc", acre_enabled=True)
    after = Profile(start_date=date(2026, 7, 1), activity="bnc", acre_enabled=True)
    assert contribution_rate(on, before, book.figures).rate == D("0.128")
    assert contribution_rate(on, after, book.figures).rate == D("0.192")
