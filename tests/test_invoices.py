"""Numbering, immutability, credit notes and what the PDF must say."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D

import pytest
from pypdf import PdfReader

from conftest import pay
from microcompta.core.errors import ImmutableError, IssueBlocked, ValidationError
from microcompta.core.money import fmt_amount_fr
from microcompta.core.profile import siren_is_valid


@pytest.fixture
def ready(book, identity, client_id):
    """A complete profile and two March payments."""
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25", description="Annotation, week 9")
    pay(book, client_id, date(2027, 3, 12), "1500", "1.25", description="Annotation, week 10")
    return client_id


def draft_for(book, client_id, month=3):
    return book.invoices.create_monthly_draft(client_id, 2027, month)


def issue(book, invoice_id, on=date(2027, 4, 1)):
    return book.invoices.issue(invoice_id, on, fx_rate="1.0823", fx_rate_date=on)


def pdf_text(path) -> str:
    text = "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)
    return " ".join(text.replace(" ", " ").split())


def pdf_of(book, invoice_id):
    invoice = book.invoices.get(invoice_id)
    return book.documents.path_of(book.documents.get(int(invoice["document_id"])))


# -- drafts ------------------------------------------------------------------
def test_monthly_draft_has_one_line_per_payment_of_that_month(book, ready):
    pay(book, ready, date(2027, 4, 2), "700", "1.25")
    invoice_id = draft_for(book, ready)
    invoice = book.invoices.get(invoice_id)
    assert invoice["status"] == "draft"
    assert invoice["number"] is None
    assert invoice["service_start"] == date(2027, 3, 1)
    assert invoice["service_end"] == date(2027, 3, 31)
    lines = book.invoices.lines(invoice_id)
    assert [l["total"] for l in lines] == [D("1000.00"), D("1500.00")]
    assert [l["payment_date"] for l in lines] == [date(2027, 3, 5), date(2027, 3, 12)]


def test_a_payment_goes_on_only_one_live_invoice(book, ready):
    draft_for(book, ready)
    with pytest.raises(ValidationError, match="No payment to invoice"):
        draft_for(book, ready)


def test_a_reversed_payment_is_not_offered_for_invoicing(book, identity, client_id):
    book.save_profile(identity)
    seq = pay(book, client_id, date(2027, 3, 5))
    book.ledger.reverse(seq, "Mistake")
    with pytest.raises(ValidationError):
        draft_for(book, client_id)


def test_a_deleted_draft_gives_its_payments_back(book, ready):
    invoice_id = draft_for(book, ready)
    book.invoices.delete_draft(invoice_id)
    assert len(book.invoices.uninvoiced_payments(ready, 2027, 3)) == 2
    draft_for(book, ready)


def test_draft_lines_can_be_hours_and_a_rate(book, ready):
    invoice_id = draft_for(book, ready)
    lines = book.invoices.lines(invoice_id)
    book.invoices.set_lines(invoice_id, [
        {"description": "Annotation, week 9", "quantity": "16.5", "unit_price": "60.61",
         "ledger_seq": lines[0]["ledger_seq"], "payment_date": lines[0]["payment_date"]},
        {"description": lines[1]["description"], "quantity": "25", "unit_price": "60",
         "ledger_seq": lines[1]["ledger_seq"], "payment_date": lines[1]["payment_date"]},
    ])
    new_lines = book.invoices.lines(invoice_id)
    assert new_lines[0]["total"] == D("1000.07")
    assert new_lines[1]["total"] == D("1500.00")
    warnings = book.invoices.issue_warnings(invoice_id)
    assert len(warnings) == 1 and "1000.07" in warnings[0]


# -- SIREN -------------------------------------------------------------------
@pytest.mark.parametrize("siren, valid", [
    ("123456782", True), ("123 456 782", True), ("123456789", False),
    ("12345678", False), ("abcdefghi", False), ("000000000", False), ("", False),
])
def test_siren_format_and_check_digit(siren, valid):
    assert siren_is_valid(siren) is valid


def test_draft_without_siren_is_allowed_and_previews(book, identity, client_id, tmp_path):
    identity.siren = ""
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = draft_for(book, client_id)
    path = book.invoices.preview(invoice_id, tmp_path / "preview.pdf")
    text = pdf_text(path)
    assert "BROUILLON" in text or "brouillon" in text
    assert "SIREN : à venir" in text


def test_final_invoice_without_siren_is_refused(book, identity, client_id):
    identity.siren = ""
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = draft_for(book, client_id)
    with pytest.raises(IssueBlocked) as caught:
        issue(book, invoice_id)
    assert any("SIREN" in r for r in caught.value.reasons)
    assert book.invoices.get(invoice_id)["status"] == "draft"
    assert book.invoices.register() == []


def test_final_invoice_with_an_invalid_siren_is_refused(book, identity, client_id):
    identity.siren = "123456789"
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    with pytest.raises(IssueBlocked):
        issue(book, draft_for(book, client_id))


def test_every_reason_is_reported_at_once(book, client_id):
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = draft_for(book, client_id)
    with pytest.raises(IssueBlocked) as caught:
        book.invoices.issue(invoice_id, date(2027, 4, 1))
    joined = " ".join(caught.value.reasons)
    for expected in ("SIREN", "name", "address", "exchange rate"):
        assert expected in joined


# -- numbering ---------------------------------------------------------------
def test_numbers_are_unbroken_and_chronological(book, ready):
    numbers = [issue(book, draft_for(book, ready))]
    for month, day in ((4, 2), (5, 3)):
        pay(book, ready, date(2027, month, day))
        numbers.append(issue(book, draft_for(book, ready, month), date(2027, month + 1, 1)))
    assert numbers == ["FA-2027-0001", "FA-2027-0002", "FA-2027-0003"]
    assert [r["seq"] for r in book.invoices.register()] == [1, 2, 3]
    assert book.invoices.verify() == []


def test_numbering_continues_across_years(book, identity, client_id, pinned_today):
    book.save_profile(identity)
    pinned_today(date(2028, 2, 1))
    pay(book, client_id, date(2027, 12, 3))
    pay(book, client_id, date(2028, 1, 3))
    first = book.invoices.issue(book.invoices.create_monthly_draft(client_id, 2027, 12),
                                date(2027, 12, 31), fx_rate="1.1", fx_rate_date=date(2027, 12, 31))
    second = book.invoices.issue(book.invoices.create_monthly_draft(client_id, 2028, 1),
                                 date(2028, 2, 1), fx_rate="1.1", fx_rate_date=date(2028, 2, 1))
    assert first == "FA-2027-0001"
    assert second == "FA-2028-0002"


def test_an_invoice_cannot_be_dated_before_the_last_one(book, ready):
    issue(book, draft_for(book, ready), date(2027, 5, 1))
    pay(book, ready, date(2027, 4, 2))
    with pytest.raises(IssueBlocked, match="chronological"):
        issue(book, draft_for(book, ready, 4), date(2027, 4, 30))


def test_an_invoice_cannot_be_dated_in_the_future(book, ready):
    with pytest.raises(IssueBlocked, match="future"):
        issue(book, draft_for(book, ready), date(2027, 6, 16))


def test_a_failed_render_leaves_no_gap_no_document_and_a_draft(book, ready):
    invoice_id = draft_for(book, ready)
    real_render = book.invoices.render

    def broken(*args, **kwargs):
        raise OSError("disk full")

    book.invoices.render = broken
    with pytest.raises(OSError):
        issue(book, invoice_id)
    book.invoices.render = real_render

    assert book.invoices.get(invoice_id)["status"] == "draft"
    assert book.invoices.register() == []
    assert book.db.scalar("SELECT count(*) FROM documents") == 0
    assert list(book.documents.tmp_dir().iterdir()) == []
    assert issue(book, invoice_id) == "FA-2027-0001"


def test_a_failed_registration_rolls_back_the_document_and_the_queue(book, ready):
    invoice_id = draft_for(book, ready)
    book.db.con.execute(
        "INSERT INTO invoice_register SELECT 1, 'FA-2027-0001', 999, 'invoice', DATE '2027-01-01', "
        "'x', 'USD', 1, 1, 1, '{}', 'x', 999, TIMESTAMP '2027-01-01', 'x', 'x'"
    )
    # The next number is 2, so collide on it instead: force a clash on the UNIQUE invoice_id.
    book.db.con.execute(
        f"INSERT INTO invoice_register SELECT 2, 'FA-2027-0009', {invoice_id}, 'invoice', "
        "DATE '2027-01-01', 'x', 'USD', 1, 1, 1, '{}', 'x', 999, TIMESTAMP '2027-01-01', 'x', 'x'"
    )
    with pytest.raises(Exception):
        issue(book, invoice_id)
    assert book.db.scalar("SELECT count(*) FROM documents") == 0
    assert book.db.scalar("SELECT count(*) FROM upload_queue") == 0
    pdfs = [p for p in book.documents.root.rglob("*.pdf")]
    assert pdfs == []


# -- immutability ------------------------------------------------------------
def test_an_issued_invoice_cannot_change(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    with pytest.raises(ImmutableError):
        book.invoices.update_draft(invoice_id, notes="x")
    with pytest.raises(ImmutableError):
        book.invoices.set_lines(invoice_id, [])
    with pytest.raises(ImmutableError):
        book.invoices.delete_draft(invoice_id)
    with pytest.raises(ImmutableError):
        issue(book, invoice_id, date(2027, 4, 2))


def test_a_later_change_of_identity_or_client_does_not_alter_an_issued_invoice(
        book, ready, identity):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    before = book.invoices.register()[0]["snapshot_json"]
    identity.address = "Somewhere else"
    book.save_profile(identity)
    book.clients.update(ready, name="Renamed LLC")
    after = book.invoices.register()[0]
    assert after["snapshot_json"] == before
    assert after["client_name"] == "Acme Annotation LLC"
    assert book.verify() == []


def test_a_pdf_changed_on_disk_is_detected(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    path = pdf_of(book, invoice_id)
    path.chmod(0o666)
    path.write_bytes(b"%PDF-1.4 forged")
    assert any("changed on disk" in p for p in book.verify())


def test_tampering_with_the_register_directly_is_detected(book, ready):
    issue(book, draft_for(book, ready))
    book.db.con.execute("UPDATE invoice_register SET total = 1")
    assert any("changed after it was issued" in p for p in book.verify())


def test_issued_pdf_is_read_only_and_queued_for_backup(book, ready):
    import os
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    assert not os.access(pdf_of(book, invoice_id), os.W_OK)
    assert book.queue.counts()["pending"] == 1
    doc = book.documents.get(int(book.invoices.get(invoice_id)["document_id"]))
    assert doc["rel_path"] == "2027/factures/FA-2027-0001.pdf"


# -- credit notes ------------------------------------------------------------
def test_credit_note_shares_the_sequence_and_mirrors_the_original(book, ready):
    invoice_id = draft_for(book, ready)
    number = issue(book, invoice_id)
    credit = book.invoices.credit_note(invoice_id, "Wrong client", date(2027, 4, 2))
    assert number == "FA-2027-0001"
    assert credit == "AV-2027-0002"
    original, note = book.invoices.register()
    assert note["kind"] == "credit_note"
    assert note["total"] == -original["total"]
    assert note["total_eur"] == -original["total_eur"]
    assert note["fx_rate"] == original["fx_rate"]
    assert json.loads(note["snapshot_json"])["credits_number"] == number
    assert book.verify() == []


def test_credit_note_pdf_refers_to_the_original_and_states_the_reason(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    book.invoices.credit_note(invoice_id, "Wrong client", date(2027, 4, 2))
    note_id = book.invoices.list()[0]["id"]
    text = pdf_text(pdf_of(book, note_id))
    assert "AVOIR" in text
    assert "FA-2027-0001" in text
    assert "Wrong client" in text
    assert "AV-2027-0002" in text


def test_credit_note_owes_nothing(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    book.invoices.credit_note(invoice_id, "Correction", date(2027, 4, 2))
    text = pdf_text(pdf_of(book, book.invoices.list()[0]["id"]))
    assert "Total de l'avoir (USD)" in text
    assert "Total à payer" not in text
    assert "frais de recouvrement" not in text


def test_credit_note_releases_the_payments(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    assert book.invoices.uninvoiced_payments(ready, 2027, 3) == []
    book.invoices.credit_note(invoice_id, "Correction", date(2027, 4, 2))
    assert len(book.invoices.uninvoiced_payments(ready, 2027, 3)) == 2
    assert issue(book, draft_for(book, ready), date(2027, 4, 3)) == "FA-2027-0003"


def test_credit_note_rules(book, ready):
    invoice_id = draft_for(book, ready)
    with pytest.raises(ValidationError):
        book.invoices.credit_note(invoice_id, "Not issued yet", date(2027, 4, 1))
    issue(book, invoice_id)
    with pytest.raises(ValidationError):
        book.invoices.credit_note(invoice_id, " ", date(2027, 4, 1))
    book.invoices.credit_note(invoice_id, "Once", date(2027, 4, 1))
    with pytest.raises(ImmutableError):
        book.invoices.credit_note(invoice_id, "Twice", date(2027, 4, 1))
    note_id = book.invoices.list()[0]["id"]
    with pytest.raises(ValidationError):
        book.invoices.credit_note(note_id, "Of a credit note", date(2027, 4, 1))


def test_an_invoice_with_a_reversed_payment_is_flagged_for_a_credit_note(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    assert book.invoices.stale() == []
    seq = book.invoices.lines(invoice_id)[0]["ledger_seq"]
    book.ledger.reverse(seq, "Refund")
    assert [s["number"] for s in book.invoices.stale()] == ["FA-2027-0001"]
    book.invoices.credit_note(invoice_id, "Refund", date(2027, 4, 2))
    assert book.invoices.stale() == []


def test_a_draft_with_a_reversed_payment_cannot_be_issued(book, ready):
    invoice_id = draft_for(book, ready)
    book.ledger.reverse(book.invoices.lines(invoice_id)[0]["ledger_seq"], "Refund")
    with pytest.raises(IssueBlocked, match="reversed payment"):
        issue(book, invoice_id)


# -- the document itself -----------------------------------------------------
def test_pdf_carries_every_mandatory_mention(book, ready):
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id, date(2027, 4, 1))
    text = pdf_text(pdf_of(book, invoice_id))
    for mention in (
        "Camille Exemple EI",                  # name with EI
        "Entrepreneur individuel",
        "12 rue de l'Exemple",                 # address
        "SIREN : 123456782",
        "Date d'émission : 01/04/2027",
        "n° FA-2027-0001",                     # unique number
        "du 01/03/2027 au 31/03/2027",         # service date
        "Acme Annotation LLC",                 # client identity
        "1 Example Street",
        "Annotation, week 9",                  # description
        "Quantité",
        "Prix unitaire HT",
        "Total HT",
        "2 500,00 USD",                        # totals
        "05/03/2027, 12/03/2027",              # payment dates
        "pénalités au taux de 3 fois le taux d'intérêt légal",   # late-payment rate
        "frais de recouvrement",               # recovery indemnity
        "40,00 €",
        "TVA non applicable, art. 293 B du CGI",
    ):
        assert mention in text, mention


def test_pdf_presents_usd_as_the_ministry_page_requires(book, ready):
    """Amount in the currency, euro counter-value, the rate applied, ECB as reference."""
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id, date(2027, 4, 1))
    text = pdf_text(pdf_of(book, invoice_id))
    assert "2 500,00 USD" in text
    assert "Contre-valeur en euros" in text
    assert "2 309,90 €" in text                 # 2500 / 1.0823
    assert "1 EUR = 1,0823 USD" in text
    assert "taux de référence BCE du 01/04/2027" in text
    assert book.invoices.register()[0]["total_eur"] == D("2309.90")


def test_a_usd_invoice_needs_its_rate_and_rate_date(book, ready):
    invoice_id = draft_for(book, ready)
    with pytest.raises(IssueBlocked, match="exchange rate"):
        book.invoices.issue(invoice_id, date(2027, 4, 1))
    with pytest.raises(IssueBlocked, match="date of the exchange rate"):
        book.invoices.issue(invoice_id, date(2027, 4, 1), fx_rate="1.08")
    with pytest.raises(IssueBlocked, match="after the issue date"):
        book.invoices.issue(invoice_id, date(2027, 4, 1), fx_rate="1.08",
                            fx_rate_date=date(2027, 4, 2))


def test_a_weekend_issue_can_show_the_last_published_rate(book, ready):
    """The ECB publishes nothing at weekends. 2027-04-03 is a Saturday."""
    invoice_id = draft_for(book, ready)
    book.invoices.issue(invoice_id, date(2027, 4, 3), fx_rate="1.08", fx_rate_date=date(2027, 4, 2))
    assert "BCE du 02/04/2027" in pdf_text(pdf_of(book, invoice_id))


def test_a_euro_invoice_shows_no_conversion(book, identity):
    book.save_profile(identity)
    client = book.clients.add(name="Client FR", address="Paris", currency="EUR", taxed_in_france=True)
    book.ledger.record_payment(received_on=date(2027, 3, 5), client_id=client, description="Work",
                               amount_gross="500", fx_rate="1", net_credited="500",
                               payment_method="Bank transfer")
    invoice_id = book.invoices.create_monthly_draft(client, 2027, 3)
    book.invoices.issue(invoice_id, date(2027, 4, 1))
    text = pdf_text(pdf_of(book, invoice_id))
    assert "Contre-valeur" not in text
    assert "Taux de change" not in text
    assert "500,00 €" in text


def test_editable_mentions_reach_the_pdf(book, ready, identity):
    identity.vat_mention = "TVA non applicable, article 293 B du code général des impôts"
    book.save_profile(identity)
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    assert "article 293 B du code général des impôts" in pdf_text(pdf_of(book, invoice_id))


def test_recovery_indemnity_comes_from_the_figures(book, ready):
    book.figures.upsert("recovery_indemnity", date(2027, 1, 1), "45", "test")
    invoice_id = draft_for(book, ready)
    issue(book, invoice_id)
    assert "45,00 €" in pdf_text(pdf_of(book, invoice_id))


def test_awkward_text_cannot_break_the_pdf(book, identity, client_id):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), description="R&D <b>sprint</b> \"été\" €5")
    invoice_id = draft_for(book, client_id)
    issue(book, invoice_id)
    assert "R&D <b>sprint</b>" in pdf_text(pdf_of(book, invoice_id))


def test_french_amount_format():
    assert fmt_amount_fr(D("1234.5"), "USD").replace(" ", " ") == "1 234,50 USD"
    assert fmt_amount_fr(D("-40"), "EUR").replace(" ", " ") == "-40,00 €"
