"""The ledger cannot be edited, and the turnover choices recompute without changing it."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from conftest import pay
from microcompta.core.errors import ImmutableError, ValidationError
from microcompta.core.ledger import Ledger
from microcompta.core.ledger_policy import TurnoverPolicy, counted_eur


def test_entry_stores_each_value_separately(book, client_id):
    seq = book.ledger.record_payment(
        received_on=date(2027, 3, 5), client_id=client_id, description="Annotation, week 9",
        amount_gross="1000.00", fx_rate="1.25", fee_amount="30.00", net_credited="770.00",
        payment_method="Stripe", provider_ref="po_test_1",
    )
    e = book.ledger.get(seq)
    assert e["amount_gross"] == D("1000.00")
    assert e["fx_rate"] == D("1.250000")
    assert e["eur_gross"] == D("800.00")
    assert e["fee_amount"] == D("30.00")
    assert e["fee_eur"] == D("24.00")
    assert e["net_credited"] == D("770.00")
    assert e["client_name"] == "Acme Annotation LLC"
    assert e["payment_method"] == "Stripe"
    assert e["provider_ref"] == "po_test_1"


@pytest.mark.parametrize("change", [
    {"amount_gross": "0"}, {"amount_gross": "-5"}, {"fx_rate": "0"}, {"fee_amount": "-1"},
    {"net_credited": "0"}, {"description": "  "}, {"payment_method": ""},
    {"received_on": date(2027, 6, 16)},  # the day after the pinned date
])
def test_bad_input_is_refused(book, client_id, change):
    args = dict(received_on=date(2027, 3, 5), client_id=client_id, description="Work",
                amount_gross="100", fx_rate="1.25", net_credited="80", payment_method="Stripe")
    args.update(change)
    with pytest.raises(ValidationError):
        book.ledger.record_payment(**args)
    assert book.ledger.entries() == []


def test_a_provider_reference_cannot_be_recorded_twice(book, client_id):
    pay(book, client_id, date(2027, 3, 5), provider_ref="po_dup")
    with pytest.raises(ValidationError, match="already recorded"):
        pay(book, client_id, date(2027, 3, 6), provider_ref="po_dup")


def test_a_reversed_reference_can_be_recorded_again(book, client_id):
    seq = pay(book, client_id, date(2027, 3, 5), provider_ref="po_again")
    book.ledger.reverse(seq, "Wrong amount")
    pay(book, client_id, date(2027, 3, 5), provider_ref="po_again")


# -- immutability ------------------------------------------------------------
def test_the_ledger_has_no_way_to_edit_or_delete():
    public = {name for name in dir(Ledger) if not name.startswith("_")}
    assert public == {"record_payment", "reverse", "get", "years", "entries",
                      "quarter_totals", "verify"}


@pytest.mark.parametrize("sql", [
    "UPDATE ledger SET amount_gross = 1",
    "update  ledger set description = 'x'",
    "DELETE FROM ledger",
    "delete from main.ledger where seq = 1",
    "TRUNCATE ledger",
    "DROP TABLE ledger",
    "ALTER TABLE ledger DROP COLUMN reason",
    'UPDATE "ledger" SET reason = 1',
    "UPDATE invoice_register SET total = 1",
    "DELETE FROM invoice_register",
])
def test_the_app_write_path_refuses_to_touch_the_guarded_tables(book, client_id, sql):
    pay(book, client_id, date(2027, 3, 5))
    with pytest.raises(ImmutableError):
        book.db.execute(sql)
    assert len(book.ledger.entries()) == 1


def test_a_direct_change_to_the_file_is_detected(book, client_id):
    """DuckDB has no triggers, so someone can edit the file directly. They can't hide it."""
    seq = pay(book, client_id, date(2027, 3, 5), "1000", "1.25")
    pay(book, client_id, date(2027, 3, 6), "1000", "1.25")
    assert book.verify() == []
    book.db.con.execute("UPDATE ledger SET eur_gross = 1.00 WHERE seq = ?", [seq])
    assert any("entry 1 was changed" in p for p in book.verify())


def test_a_deleted_entry_is_detected(book, client_id):
    for day in (5, 6, 7):
        pay(book, client_id, date(2027, 3, day))
    book.db.con.execute("DELETE FROM ledger WHERE seq = 2")
    problems = book.ledger.verify()
    assert any("entry 2 is missing" in p for p in problems)
    assert any("entry 3 does not follow" in p for p in problems)


def test_the_chain_survives_a_reopen(tmp_path, pinned_today):
    from microcompta.core.book import Book
    from microcompta.core.db import Database

    path = tmp_path / "reopen.duckdb"
    first = Book(Database(path), tmp_path / "docs")
    client = first.clients.add(name="X", address="Y")
    first.ledger.record_payment(received_on=date(2027, 3, 5), client_id=client, description="A",
                                amount_gross="123.45", fx_rate="1.0823", fee_amount="3.10",
                                net_credited="111.11", payment_method="PayPal")
    first.close()
    second = Book(Database(path), tmp_path / "docs")
    assert second.ledger.verify() == []
    second.close()


# -- reversal ----------------------------------------------------------------
def test_reversal_needs_a_reason(book, client_id):
    seq = pay(book, client_id, date(2027, 3, 5))
    with pytest.raises(ValidationError):
        book.ledger.reverse(seq, "  ")


def test_reversal_nets_out_and_leaves_the_original_untouched(book, client_id):
    seq = pay(book, client_id, date(2027, 3, 5), "1000", "1.25", fee="30")
    before = book.ledger.get(seq)
    rev = book.ledger.reverse(seq, "Recorded twice")
    assert book.ledger.get(seq) == before
    reversal = book.ledger.get(rev)
    assert reversal["kind"] == "reversal"
    assert reversal["reverses_seq"] == seq
    assert reversal["reason"] == "Recorded twice"
    assert reversal["eur_gross"] == -before["eur_gross"]
    assert reversal["net_credited"] == -before["net_credited"]
    assert reversal["received_on"] == before["received_on"]
    assert book.limits.turnover(2027) == D("0.00")


def test_a_reversal_can_carry_its_own_date(book, client_id):
    seq = pay(book, client_id, date(2027, 3, 5))
    rev = book.ledger.reverse(seq, "Refunded", on=date(2027, 6, 1))
    assert book.ledger.get(rev)["received_on"] == date(2027, 6, 1)
    totals = book.ledger.quarter_totals(2027, TurnoverPolicy())
    assert totals[0]["counted"] == D("800.00")
    assert totals[1]["counted"] == D("-800.00")


def test_cannot_reverse_twice_or_reverse_a_reversal(book, client_id):
    seq = pay(book, client_id, date(2027, 3, 5))
    rev = book.ledger.reverse(seq, "Mistake")
    with pytest.raises(ImmutableError):
        book.ledger.reverse(seq, "Again")
    with pytest.raises(ImmutableError):
        book.ledger.reverse(rev, "Undo")


# -- turnover ----------------------------------------------------------------
def test_turnover_counts_on_the_date_received_not_the_invoice_date(book, client_id, identity):
    identity.start_date = date(2026, 11, 2)
    book.save_profile(identity)
    pay(book, client_id, date(2026, 12, 31), "1250", "1.25")
    pay(book, client_id, date(2027, 1, 1), "2500", "1.25")
    assert book.limits.turnover(2026) == D("1000.00")
    assert book.limits.turnover(2027) == D("2000.00")


def test_quarter_totals_land_in_the_right_quarters(book, client_id):
    for on in (date(2027, 3, 31), date(2027, 4, 1), date(2027, 6, 15)):
        pay(book, client_id, on, "1250", "1.25", fee="125")
    totals = book.ledger.quarter_totals(2027, TurnoverPolicy())
    assert [q["entries"] for q in totals] == [1, 2, 0, 0]
    assert totals[0]["counted"] == D("1000.00")
    assert totals[1]["counted"] == D("2000.00")
    assert totals[1]["fee_eur"] == D("200.00")


ENTRY = {
    "amount_gross": D("1000.00"), "currency": "USD", "fx_rate": D("1.25"), "eur_gross": D("800.00"),
    "fee_amount": D("30.00"), "fee_currency": "USD", "fee_eur": D("24.00"),
    "net_credited": D("760.00"), "net_currency": "EUR",
}


def test_default_policy_is_gross_before_fees_at_the_recorded_rate():
    assert TurnoverPolicy().basis == "gross"
    assert TurnoverPolicy().fx == "entry_rate"
    assert counted_eur(ENTRY, TurnoverPolicy()) == D("800.00")


def test_net_of_fees_at_the_recorded_rate():
    assert counted_eur(ENTRY, TurnoverPolicy(basis="net_of_fees")) == D("776.00")


def test_provider_rate_is_derived_from_what_was_credited():
    """970 USD became 760 EUR. Fee at that rate is 23.51; gross is 760 + 23.51."""
    assert counted_eur(ENTRY, TurnoverPolicy(fx="provider_effective")) == D("783.51")
    assert counted_eur(ENTRY, TurnoverPolicy(basis="net_of_fees", fx="provider_effective")) == D("760.00")


def test_provider_rate_falls_back_when_no_euros_were_credited():
    kept_in_usd = {**ENTRY, "net_currency": "USD", "net_credited": D("970.00")}
    assert counted_eur(kept_in_usd, TurnoverPolicy(fx="provider_effective")) == D("800.00")


def test_changing_the_setting_recomputes_without_touching_an_entry(book, client_id, identity):
    identity.start_date = date(2026, 11, 2)
    book.save_profile(identity)
    seq = pay(book, client_id, date(2027, 3, 5), "1000", "1.25", fee="30", net="760")
    before = book.ledger.get(seq)
    assert book.limits.turnover(2027) == D("800.00")
    identity.turnover_basis = "net_of_fees"
    book.save_profile(identity)
    assert book.limits.turnover(2027) == D("776.00")
    assert book.ledger.get(seq) == before
    assert book.verify() == []


def test_a_reversal_cancels_exactly_under_every_policy():
    reversal = {**ENTRY, "amount_gross": -ENTRY["amount_gross"], "eur_gross": -ENTRY["eur_gross"],
                "fee_amount": -ENTRY["fee_amount"], "fee_eur": -ENTRY["fee_eur"],
                "net_credited": -ENTRY["net_credited"]}
    for basis in ("gross", "net_of_fees"):
        for fx in ("entry_rate", "provider_effective"):
            policy = TurnoverPolicy(basis=basis, fx=fx)
            assert counted_eur(ENTRY, policy) + counted_eur(reversal, policy) == 0
