"""The purchases register: an insert-only record that changes nothing else."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from pypdf import PdfReader

from conftest import pay
from microcompta import i18n
from microcompta.core.book import Book
from microcompta.core.db import SCHEMA_VERSION, Database
from microcompta.core.errors import ImmutableError, ValidationError
from microcompta.core.limits import flat_allowance
from microcompta.core.purchases import CATEGORIES, FIXED_ASSET, PAYMENT_METHODS


def buy(book: Book, on: date = date(2027, 3, 5), amount: str = "100", **extra) -> int:
    return book.purchases.record(
        paid_on=on,
        supplier=extra.pop("supplier", "Logiciel Exemple"),
        description=extra.pop("description", "Abonnement mensuel"),
        category=extra.pop("category", "Software and subscriptions"),
        amount_eur=amount,
        payment_method=extra.pop("payment_method", "Bank card"),
        **extra,
    )


# -- recording -------------------------------------------------------------------
def test_a_purchase_is_recorded_with_what_the_register_needs(book):
    seq = buy(book, amount="21,60", piece_ref=" EX-2027-03 ", pro_share="0.5")
    row = book.purchases.get(seq)
    assert row["paid_on"] == date(2027, 3, 5)
    assert row["supplier"] == "Logiciel Exemple"
    assert row["amount_eur"] == D("21.60")
    assert row["pro_share"] == D("0.5")
    assert row["payment_method"] == "Bank card"
    assert row["piece_ref"] == "EX-2027-03"
    assert row["kind"] == "purchase"


def test_the_register_reads_in_date_order_whatever_the_entry_order(book):
    later = buy(book, date(2027, 3, 20))
    earlier = buy(book, date(2027, 3, 1))
    assert [e["seq"] for e in book.purchases.entries(2027)] == [earlier, later]


def test_the_professional_amount_is_the_share_of_the_amount(book):
    buy(book, amount="90", pro_share="0.5")
    assert book.purchases.entries(2027)[0]["pro_amount"] == D("45.00")


@pytest.mark.parametrize("change, message", [
    ({"supplier": "  "}, "supplier"),
    ({"description": "  "}, "description"),
    ({"category": "Whatever"}, "category"),
    ({"on": date(2027, 6, 16)}, "future"),
    ({"amount": "0"}, "positive"),
    ({"amount": "-5"}, "positive"),
    ({"amount": "abc"}, "not a number"),
    ({"pro_share": "0"}, "between"),
    ({"pro_share": "1.01"}, "between"),
    ({"payment_method": " "}, "payment method"),
])
def test_a_bad_purchase_is_refused(book, change, message):
    with pytest.raises(ValidationError, match=message):
        buy(book, **change)
    assert book.purchases.entries() == []


def test_today_is_allowed(book):
    assert buy(book, date(2027, 6, 15))


# -- it can only grow ------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "UPDATE purchases SET amount_eur = 1",
    "DELETE FROM purchases",
    "delete from main.purchases",
    'UPDATE "purchases" SET supplier = \'x\'',
    "DROP TABLE purchases",
    "ALTER TABLE purchases ADD COLUMN x INT",
    "TRUNCATE purchases",
])
def test_the_register_refuses_every_write_but_an_insert(book, sql):
    buy(book)
    with pytest.raises(ImmutableError):
        book.db.execute(sql)
    assert len(book.purchases.entries()) == 1


def test_a_reversal_cancels_the_entry_and_keeps_both(book):
    seq = buy(book, amount="100", pro_share="0.5")
    new = book.purchases.reverse(seq, "Saisi deux fois")
    entries = book.purchases.entries(2027)
    assert [e["seq"] for e in entries] == [seq, new]
    assert entries[0]["is_reversed"] is True
    assert entries[1]["amount_eur"] == D("-100.00")
    assert entries[1]["reverses_seq"] == seq
    assert entries[1]["reason"] == "Saisi deux fois"
    totals = book.purchases.totals(2027)
    assert totals["paid"] == 0
    assert totals["pro"] == 0


def test_a_reversal_needs_a_reason_and_only_happens_once(book):
    seq = buy(book)
    with pytest.raises(ValidationError, match="reason"):
        book.purchases.reverse(seq, "  ")
    new = book.purchases.reverse(seq, "Erreur")
    with pytest.raises(ImmutableError, match="already been reversed"):
        book.purchases.reverse(seq, "Encore")
    with pytest.raises(ImmutableError, match="cannot be reversed"):
        book.purchases.reverse(new, "Encore")
    with pytest.raises(ValidationError, match="does not exist"):
        book.purchases.reverse(99, "Absente")


def test_a_refund_can_be_dated_when_it_happened(book):
    seq = buy(book, date(2027, 3, 5))
    new = book.purchases.reverse(seq, "Remboursé", date(2027, 4, 1))
    assert book.purchases.get(new)["paid_on"] == date(2027, 4, 1)


# -- the hash chain --------------------------------------------------------------
def test_the_chain_is_intact_after_normal_use(book):
    seq = buy(book)
    buy(book, date(2027, 3, 6))
    book.purchases.reverse(seq, "Erreur")
    assert book.purchases.verify() == []
    assert book.verify() == []


def test_a_change_made_behind_the_app_is_detected(book):
    buy(book)
    book.db.con.execute("UPDATE purchases SET amount_eur = 1 WHERE seq = 1")
    problems = book.purchases.verify()
    assert any("was changed" in p for p in problems)
    assert book.verify()


def test_a_deleted_entry_is_detected(book):
    buy(book)
    buy(book, date(2027, 3, 6))
    buy(book, date(2027, 3, 7))
    book.db.con.execute("DELETE FROM purchases WHERE seq = 2")
    assert any("is missing" in p for p in book.purchases.verify())


@pytest.mark.parametrize("change", [
    "paid_on = DATE '2027-03-06'", "supplier = 'Autre'", "description = 'Autre'",
    "category = 'Small equipment'", "amount_eur = 1", "pro_share = 0.5", "payment_method = 'Cash'",
    "piece_ref = 'Autre'", "kind = 'reversal'", "reason = 'Autre'", "reverses_seq = 1",
])
def test_a_change_to_any_field_behind_the_app_is_detected(book, change):
    buy(book, piece_ref="F-1")
    book.db.con.execute(f"UPDATE purchases SET {change} WHERE seq = 1")
    assert any("was changed" in p for p in book.purchases.verify()), change


# -- the register changes nothing else: the legal point of the whole tab -----------
def test_a_purchase_changes_no_figure_the_app_reports(book, identity, client_id):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25")
    before = book.limits.annual(2027)
    report_before = book.limits.report(2027)
    deadlines_before = [i["title"] for i in book.deadlines.items()]

    buy(book, amount="5000")

    after = book.limits.annual(2027)
    assert after["turnover"] == before["turnover"]
    assert after["contributions"] == before["contributions"]
    assert after["form_2042_figure"] == before["form_2042_figure"]
    assert after["taxable_base"] == before["taxable_base"]
    report_after = book.limits.report(2027)
    assert report_after.ytd == report_before.ytd
    assert report_after.set_aside == report_before.set_aside
    assert [i["title"] for i in book.deadlines.items()] == deadlines_before


def test_a_purchase_doesnt_touch_the_livre_des_recettes(book, client_id):
    pay(book, client_id, date(2027, 3, 5))
    buy(book)
    assert len(book.ledger.entries()) == 1
    assert book.ledger.verify() == []


# -- the comparison ----------------------------------------------------------------
def test_the_allowance_follows_the_activity_and_its_minimum():
    assert flat_allowance(D("10000"), D("0.34"), D("305")) == D("3400.00")
    assert flat_allowance(D("500"), D("0.34"), D("305")) == D("305.00")   # the minimum
    assert flat_allowance(D("200"), D("0.34"), D("305")) == D("200.00")   # never above turnover
    assert flat_allowance(D("0"), D("0.34"), D("305")) == 0


def _set_up(book, identity, client_id, **profile):
    for key, value in profile.items():
        setattr(identity, key, value)
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "10000", "1", net="10000")   # 10,000 EUR of turnover at rate 1


def test_the_comparison_adds_up_for_a_liberal_activity(book, identity, client_id):
    _set_up(book, identity, client_id)
    buy(book, amount="1000")
    buy(book, amount="400", pro_share="0.5", category="Transport and travel")
    c = book.regime_comparison(2027)
    assert c["turnover"] == D("10000.00")
    assert c["allowance"] == D("3400.00")                  # 34% in micro-BNC
    assert c["purchases"]["paid"] == D("1400.00")
    assert c["purchases"]["pro"] == D("1200.00")
    assert c["social"] == D("2560.00")                     # 25.6%
    assert c["real_charges"] == D("3760.00")               # 1,200 + 2,560


def test_the_comparison_uses_the_higher_allowance_of_a_bic_activity(book, identity, client_id):
    _set_up(book, identity, client_id, activity="bic")
    c = book.regime_comparison(2027)
    assert c["allowance"] == D("5000.00")                  # 50% in micro-BIC services
    assert c["social"] == D("2120.00")                     # 21.2%


def test_a_fixed_asset_stays_out_of_the_charges(book, identity, client_id):
    _set_up(book, identity, client_id)
    buy(book, amount="1200", category=FIXED_ASSET, description="Ordinateur")
    c = book.regime_comparison(2027)
    assert c["purchases"]["fixed_assets"] == D("1200.00")
    assert c["purchases"]["charges"] == 0
    assert c["real_charges"] == c["social"]


def test_a_reversed_purchase_stays_out_of_the_comparison(book, identity, client_id):
    _set_up(book, identity, client_id)
    seq = buy(book, amount="1000")
    book.purchases.reverse(seq, "Erreur")
    assert book.regime_comparison(2027)["real_charges"] == D("2560.00")


def test_the_versement_liberatoire_isnt_counted_as_a_social_charge(book, identity, client_id):
    """It is income tax paid with the contributions, so it must not inflate the real side."""
    _set_up(book, identity, client_id, vl_enabled=True)
    c = book.regime_comparison(2027)
    assert c["social"] == D("2560.00")
    assert book.limits.report(2027).set_aside == D("2780.00")   # 27.8% is what URSSAF collects
    assert c["vl"] is True


def test_acre_lowers_the_contributions_in_the_comparison(book, identity, client_id):
    identity.start_date = date(2027, 1, 1)
    _set_up(book, identity, client_id, acre_enabled=True)
    assert book.regime_comparison(2027)["social"] == D("1920.00")     # 75% of 25.6%


# -- supporting documents ----------------------------------------------------------
def test_a_supporting_document_is_kept_and_queued_without_touching_the_entry(book, tmp_path):
    seq = buy(book)
    before = book.purchases.get(seq)["entry_hash"]
    source = tmp_path / "facture exemple.pdf"
    source.write_bytes(b"facture")
    doc_id = book.attach_purchase_document(seq, source)
    doc = book.documents.get(doc_id)
    assert doc["kind"] == "purchase"
    assert doc["rel_path"] == "2027/achats/achat-00001_facture exemple.pdf"
    assert book.documents.path_of(doc).read_bytes() == b"facture"
    assert [d["id"] for d in book.documents.for_purchase(seq)] == [doc_id]
    assert book.purchases.entries(2027)[0]["receipts"] == 1
    assert book.queue.counts()["pending"] == 1
    assert book.purchases.get(seq)["entry_hash"] == before
    assert book.verify() == []


def test_a_document_goes_with_its_own_entry_only(book, tmp_path):
    first, second = buy(book), buy(book)
    source = tmp_path / "f.pdf"
    source.write_bytes(b"x")
    book.attach_purchase_document(second, source)
    assert book.documents.for_purchase(first) == []
    assert book.purchases.entries(2027)[0]["receipts"] == 0


def test_a_document_for_a_missing_entry_is_refused(book, tmp_path):
    source = tmp_path / "f.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        book.attach_purchase_document(99, source)
    assert book.db.scalar("SELECT count(*) FROM documents") == 0


# -- backups and exports -----------------------------------------------------------
def test_a_purchase_makes_a_snapshot_due(book):
    book.snapshots.run(force=True)
    assert not book.snapshots.needed()
    buy(book)
    assert book.snapshots.needed()


def test_purchases_alone_are_enough_to_back_up(book):
    assert not book.snapshots.has_records()
    buy(book)
    assert book.snapshots.has_records()


def test_a_snapshot_carries_the_register_and_its_csv(book):
    buy(book)
    docs = book.snapshots.run(force=True)
    titles = [book.documents.get(d)["title"] for d in docs]
    assert any("Registre des achats" in t for t in titles)


def test_no_empty_register_is_backed_up(book, client_id):
    pay(book, client_id, date(2027, 3, 5))
    docs = book.snapshots.run(force=True)
    assert not any("Registre des achats" in book.documents.get(d)["title"] for d in docs)


def _pdf_text(path: Path) -> str:
    return " ".join(" ".join(p.extract_text() for p in PdfReader(str(path)).pages).replace(" ", " ").split())


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_register_exports_are_in_french_whatever_the_app_language(book, identity, language):
    book.save_profile(identity)
    i18n.set_language(language)
    seq = buy(book, amount="90", pro_share="0.5", category="Transport and travel",
              payment_method="Direct debit", piece_ref="F-1")
    book.purchases.reverse(seq, "Erreur")
    path = book.documents.path_of(book.documents.get(book.exports.purchases_csv(2027)))
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    assert rows[0][3] == "Fournisseur"
    record = dict(zip(rows[0], rows[1]))
    assert record["Type"] == "Achat"
    assert record["Nature"] == "Transports et déplacements"
    assert record["Mode de paiement"] == "Prélèvement"
    assert record["Part professionnelle (%)"] == "50"
    assert record["Montant professionnel (EUR)"] == "45,00"
    assert record["Référence de la pièce justificative"] == "F-1"
    assert rows[2][1] == "Annulation"
    assert rows[3][1] == "Total 2027"
    pdf = _pdf_text(book.documents.path_of(book.documents.get(book.exports.purchases_pdf(2027))))
    assert "Registre des achats 2027" in pdf
    assert "Transports et déplacements" in pdf
    assert "Annulation de l'écriture 1" in pdf
    assert "Direct debit" not in pdf


def test_stored_values_stay_as_keys_whatever_the_language(book):
    i18n.set_language("fr")
    seq = buy(book, payment_method="Bank card", category="Transport and travel")
    row = book.purchases.get(seq)
    assert row["payment_method"] == "Bank card"
    assert row["category"] == "Transport and travel"


def test_every_category_and_method_has_a_french_word():
    i18n.set_language("fr")
    for key in CATEGORIES:
        assert i18n.tr(key) != key, key
    for key in PAYMENT_METHODS:
        assert key == "PayPal" or i18n.tr(key) != key, key


# -- an existing database -----------------------------------------------------------
def test_a_database_from_before_the_register_gains_it_and_loses_nothing(tmp_path, pinned_today):
    path = tmp_path / "old.duckdb"
    old = Book(Database(path), tmp_path / "documents")
    client = old.clients.add(name="Acme", currency="EUR", taxed_in_france=True)
    seq = pay(old, client, date(2027, 3, 5), "100", "1", net="100")
    entry_hash = old.ledger.get(seq)["entry_hash"]
    for table in ("purchases", "purchase_documents"):
        old.db.con.execute(f"DROP TABLE {table}")
    old.db.con.execute("DELETE FROM figures WHERE key = 'fixed_asset_threshold'")
    old.db.set_meta("schema_version", "1")
    old.close()

    book = Book(Database(path), tmp_path / "documents")
    assert book.db.get_meta("schema_version") == str(SCHEMA_VERSION)
    assert book.ledger.get(seq)["entry_hash"] == entry_hash
    assert book.purchases.entries() == []
    assert book.figures.value("fixed_asset_threshold", date(2027, 1, 1)) == 500
    assert buy(book) == 1
    assert book.verify() == []
    book.close()


def test_a_corrected_source_reaches_an_existing_row_but_never_an_edit(book):
    on = date(2026, 1, 1)
    book.db.execute("UPDATE figures SET source = 'old text' WHERE key = 'vl_next_year_md' AND effective_from = ?", [on])
    book.figures.upsert("cfe_payment_md", date(2026, 1, 1), "12-15", source="Mine", note="Mine too")
    book.figures.seed()
    rows = {(r["key"], r["effective_from"]): r for r in book.figures.rows()}
    assert "DGFiP" in rows[("vl_next_year_md", on)]["source"]
    assert rows[("cfe_payment_md", on)]["source"] == "Mine"
    assert rows[("cfe_payment_md", on)]["note"] == "Mine too"
