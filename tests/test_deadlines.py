"""Deadlines from the start date. The first two cases are the official examples."""

from __future__ import annotations

from datetime import date

import pytest

from microcompta.core.deadlines import (
    add_months, build_deadlines, first_monthly_due, first_quarterly_due, turnover_declarations,
)
from microcompta.core.profile import Profile

FAR = date(2029, 12, 31)


def by_key(items):
    return {d.key: d for d in items}


def build(book, today=date(2027, 1, 15), **profile):
    return build_deadlines(Profile(**profile), book.figures, today)


# -- first declaration -------------------------------------------------------
def test_official_example_monthly():
    """F23257: start 6 March, first monthly declaration by 31 July."""
    assert first_monthly_due(date(2026, 3, 6)) == date(2026, 7, 31)


def test_official_example_quarterly():
    """F23257: start 12 April, first quarterly declaration by 31 October."""
    assert first_quarterly_due(date(2026, 4, 12)) == date(2026, 10, 31)


@pytest.mark.parametrize("start, due", [
    (date(2027, 3, 1), date(2027, 6, 30)),    # the three months end on a month end
    (date(2027, 3, 2), date(2027, 7, 31)),
    (date(2027, 1, 31), date(2027, 5, 31)),   # short February must not shift it
    (date(2026, 11, 30), date(2027, 3, 31)),
    (date(2026, 12, 1), date(2027, 3, 31)),
    (date(2026, 12, 6), date(2027, 4, 30)),
])
def test_first_monthly_edges(start, due):
    assert first_monthly_due(start) == due


@pytest.mark.parametrize("start, due", [
    (date(2027, 1, 1), date(2027, 7, 31)),
    (date(2027, 3, 31), date(2027, 7, 31)),
    (date(2027, 7, 15), date(2028, 1, 31)),
    (date(2026, 11, 2), date(2027, 4, 30)),   # crosses the year
    (date(2026, 12, 31), date(2027, 4, 30)),
])
def test_first_quarterly_edges(start, due):
    assert first_quarterly_due(start) == due


# -- following declarations --------------------------------------------------
def test_monthly_sequence_covers_every_day_once():
    items = turnover_declarations(date(2026, 3, 6), "monthly", FAR, "€60.10")
    assert items[0].due == date(2026, 7, 31)
    assert items[0].period_start == date(2026, 3, 6)
    assert items[0].period_end == date(2026, 6, 30)
    assert items[1].period_start == date(2026, 7, 1)
    assert items[1].period_end == date(2026, 7, 31)
    assert items[1].due == date(2026, 8, 31)        # June's example: end of the next month
    for earlier, later in zip(items, items[1:]):
        assert (later.period_start - earlier.period_end).days == 1


def test_quarterly_sequence_uses_the_fixed_dates():
    items = turnover_declarations(date(2026, 4, 12), "quarterly", FAR, "€60.10")
    assert items[0].due == date(2026, 10, 31)
    assert items[0].period_start == date(2026, 4, 12)
    assert items[0].period_end == date(2026, 9, 30)
    assert [d.due.strftime("%m-%d") for d in items[1:5]] == ["01-31", "04-30", "07-31", "10-31"]
    assert items[1].period_start == date(2026, 10, 1)
    assert items[1].period_end == date(2026, 12, 31)
    for earlier, later in zip(items, items[1:]):
        assert (later.period_start - earlier.period_end).days == 1


def test_declaration_note_states_neant_and_the_fine_from_the_figures(book):
    book.figures.upsert("late_declaration_fine", date(2027, 1, 1), "75.50")
    items = build(book, start_date=date(2026, 11, 2))
    note = next(d for d in items if d.key.startswith("declaration:")).note
    assert "Néant" in note
    assert "€75.50" in note


def test_quarterly_option_has_its_own_deadline(book):
    items = by_key(build(book, start_date=date(2027, 1, 10), declaration_frequency="quarterly"))
    assert items["declaration:option"].due == date(2027, 2, 10)
    assert "declaration:option" not in by_key(build(book, start_date=date(2027, 1, 10)))


def test_add_months_clamps_to_the_month_end():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2027, 11, 15), 3) == date(2028, 2, 15)


# -- ACRE --------------------------------------------------------------------
def test_acre_request_is_60_days_after_the_start_and_only_if_enabled(book):
    enabled = by_key(build(book, start_date=date(2026, 11, 2), acre_enabled=True))
    assert enabled["acre:request"].due == date(2027, 1, 1)
    assert "acre:request" not in by_key(build(book, start_date=date(2026, 11, 2)))


def test_acre_days_come_from_the_figures(book):
    book.figures.upsert("acre_request_days", date(2026, 1, 1), "45")
    items = by_key(build(book, start_date=date(2026, 11, 2), acre_enabled=True))
    assert items["acre:request"].due == date(2026, 12, 17)


# -- versement libératoire ---------------------------------------------------
@pytest.mark.parametrize("start, due", [
    (date(2027, 1, 20), date(2027, 4, 30)),   # the official example
    (date(2026, 11, 2), date(2027, 2, 28)),
    (date(2027, 11, 2), date(2028, 2, 29)),   # leap year
])
def test_vl_option_last_day_of_the_third_month_after_creation(book, start, due):
    items = build_deadlines(Profile(start_date=start), book.figures, start)
    assert by_key(items)["vl:creation"].due == due


def test_vl_option_then_september_30_for_the_next_year(book):
    items = by_key(build(book, start_date=date(2026, 11, 2)))
    assert items["vl:2028"].due == date(2027, 9, 30)
    assert "vl:2027" not in items   # 2026-09-30 is before the business existed


# -- CFE ---------------------------------------------------------------------
def test_cfe_form_in_the_creation_year_only(book):
    items = by_key(build(book, today=date(2026, 11, 2), start_date=date(2026, 11, 2)))
    assert items["cfe:form"].due == date(2026, 12, 31)


def test_cfe_payment_starts_the_year_after_creation(book):
    items = by_key(build(book, today=date(2026, 11, 2), start_date=date(2026, 11, 2)))
    assert "cfe:pay:2026" not in items    # nothing is owed in the first year
    assert items["cfe:pay:2027"].due == date(2027, 12, 15)


# -- form 2042 and fixed items ------------------------------------------------
def test_form_2042_has_no_hard_coded_date(book):
    item = by_key(build(book, start_date=date(2026, 11, 2)))["2042:2026"]
    assert item.due is None
    assert "Spring 2027" in item.note
    assert item.remind_from == date(2027, 4, 1)


def test_e_reporting_date(book):
    assert by_key(build(book))["ereporting"].due == date(2027, 9, 1)


def test_vat_mention_review_date(book):
    assert by_key(build(book))["vat_mention"].due == date(2027, 12, 31)


def test_e_reporting_date_comes_from_the_figures(book):
    book.figures.upsert("ereporting_deadline", date(2026, 1, 1), "2028-01-15")
    assert by_key(build(book))["ereporting"].due == date(2028, 1, 15)


def test_without_a_start_date_only_the_fixed_items_appear(book):
    assert set(by_key(build(book))) == {"ereporting", "vat_mention", "einvoice_reception"}


def test_receiving_e_invoices_is_due_from_1_september_2026(book):
    """economie.gouv.fr: every business must be able to receive them from that date."""
    item = by_key(build(book, start_date=date(2026, 3, 2)))["einvoice_reception"]
    assert item.due == date(2026, 9, 1)
    assert not item.optional          # an obligation, so it goes overdue rather than passing


def test_a_business_started_later_must_receive_them_from_its_first_day(book):
    item = by_key(build(book, start_date=date(2026, 11, 2)))["einvoice_reception"]
    assert item.due == date(2026, 11, 2)


def test_the_reception_date_comes_from_the_figures(book):
    book.figures.upsert("einvoice_reception_deadline", date(2026, 1, 1), "2026-10-01")
    assert by_key(build(book))["einvoice_reception"].due == date(2026, 10, 1)


def test_reception_shows_as_overdue_until_it_is_marked_done(book, identity):
    identity.start_date = date(2026, 3, 2)
    book.save_profile(identity)
    today = date(2026, 11, 12)
    status = lambda: next(i for i in book.deadlines.items(today) if i["key"] == "einvoice_reception")
    assert status()["status"] == "overdue"
    book.deadlines.set_done("einvoice_reception")
    assert status()["done"] is True


# -- status and reminders ----------------------------------------------------
def _book_with_start(book, identity, start, **changes):
    identity.start_date = start
    for key, value in changes.items():
        setattr(identity, key, value)
    book.save_profile(identity)


def _item(book, key, today):
    return next(r for r in book.deadlines.items(today) if r["key"] == key)


def test_status_follows_the_date(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    assert _item(book, "cfe:form", date(2026, 11, 3))["status"] == "upcoming"
    assert _item(book, "cfe:form", date(2026, 12, 20))["status"] == "due soon"
    assert _item(book, "cfe:form", date(2027, 1, 1))["status"] == "overdue"


def test_done_sticks_and_can_be_undone(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    book.deadlines.set_done("cfe:form")
    assert _item(book, "cfe:form", date(2027, 1, 1))["status"] == "done"
    book.deadlines.set_done("cfe:form", False)
    assert _item(book, "cfe:form", date(2027, 1, 1))["status"] == "overdue"


def test_a_published_date_can_be_entered_for_form_2042(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    today = date(2027, 3, 1)
    assert _item(book, "2042:2026", today)["status"] == "no date yet"
    assert _item(book, "2042:2026", date(2027, 4, 1))["status"] == "due soon"
    book.deadlines.set_date("2042:2026", date(2027, 5, 20))
    item = _item(book, "2042:2026", today)
    assert item["due"] == date(2027, 5, 20)
    assert item["days_left"] == 80


def test_an_optional_choice_passes_quietly_and_never_nags(book, identity):
    """The versement libératoire is a choice. Not taking it isn't overdue."""
    _book_with_start(book, identity, date(2026, 11, 2))
    after = date(2027, 3, 15)
    assert _item(book, "vl:creation", after)["status"] == "passed"
    assert "vl:creation" not in _reminders(book, after)
    assert _item(book, "vl:creation", date(2027, 2, 20))["status"] == "due soon"
    assert "vl:creation" in _reminders(book, date(2027, 2, 20))


def test_a_required_deadline_does_go_overdue(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2), acre_enabled=True)
    assert _item(book, "acre:request", date(2027, 1, 2))["status"] == "overdue"


def _reminders(book, today):
    return {r["key"]: r for r in book.deadlines.pending_reminders(today)}


def test_each_threshold_fires_once(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    today = date(2026, 12, 17)  # 14 days before the CFE form
    pending = _reminders(book, today)
    assert "cfe:form" in pending
    book.deadlines.mark_reminded(pending["cfe:form"])
    assert "cfe:form" not in _reminders(book, today)
    assert "cfe:form" not in _reminders(book, date(2026, 12, 18))
    assert "cfe:form" in _reminders(book, date(2026, 12, 24))  # 7 days


def test_starting_late_sends_one_message_not_a_pile(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    late = date(2026, 12, 30)  # 1 day before: thresholds 14, 7, 3 and 1 have all passed
    pending = _reminders(book, late)["cfe:form"]
    assert sorted(pending["_thresholds"]) == [1, 3, 7, 14]
    book.deadlines.mark_reminded(pending)
    assert "cfe:form" not in _reminders(book, late)
    assert "cfe:form" not in _reminders(book, date(2026, 12, 31))


def test_overdue_repeats_weekly_until_done(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    first = _reminders(book, date(2027, 1, 1))["cfe:form"]
    assert "Overdue" in first["_message"]
    book.deadlines.mark_reminded(first)
    assert "cfe:form" not in _reminders(book, date(2027, 1, 7))
    second = _reminders(book, date(2027, 1, 8))["cfe:form"]
    book.deadlines.mark_reminded(second)
    book.deadlines.set_done("cfe:form")
    assert "cfe:form" not in _reminders(book, date(2027, 2, 15))


def test_form_2042_reminds_from_spring_without_a_date(book, identity):
    _book_with_start(book, identity, date(2026, 11, 2))
    assert "2042:2026" not in _reminders(book, date(2027, 3, 31))
    pending = _reminders(book, date(2027, 4, 1))["2042:2026"]
    book.deadlines.mark_reminded(pending)
    assert "2042:2026" not in _reminders(book, date(2027, 4, 2))


def test_reminders_survive_a_restart(tmp_path, pinned_today, identity):
    from microcompta.core.book import Book
    from microcompta.core.db import Database

    path = tmp_path / "r.duckdb"
    first = Book(Database(path), tmp_path / "d")
    _book_with_start(first, identity, date(2026, 11, 2))
    first.deadlines.mark_reminded(_reminders(first, date(2026, 12, 17))["cfe:form"])
    first.close()
    second = Book(Database(path), tmp_path / "d")
    assert "cfe:form" not in _reminders(second, date(2026, 12, 17))
    second.close()
