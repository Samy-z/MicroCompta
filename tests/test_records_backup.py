"""Snapshots and exports: the records must survive without the app."""

from __future__ import annotations

import csv
import zipfile
from datetime import date
from decimal import Decimal as D

import duckdb
from pypdf import PdfReader

from conftest import pay


def _docs(book, kind):
    return book.db.rows("SELECT * FROM documents WHERE kind = ? ORDER BY id", [kind])


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def test_snapshot_is_a_readable_copy_of_the_records(book, identity, client_id, drive, tmp_path):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25", provider_ref="po_1")
    added = book.snapshots.run()
    assert len(added) == 3
    snapshot = _docs(book, "snapshot")[0]
    with zipfile.ZipFile(book.documents.path_of(snapshot)) as bundle:
        path = bundle.extract("microcompta.duckdb", tmp_path)
    con = duckdb.connect(str(path), read_only=True)
    try:
        row = con.execute("SELECT eur_gross, provider_ref, entry_hash FROM ledger").fetchone()
    finally:
        con.close()
    assert row[0] == D("800.00")
    assert row[1] == "po_1"
    assert row[2] == book.ledger.get(1)["entry_hash"]


def test_snapshot_only_when_something_changed(book, identity, client_id):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    assert book.snapshots.run() != []
    assert book.snapshots.needed() is False
    assert book.snapshots.run() == []
    pay(book, client_id, date(2027, 3, 6))
    assert book.snapshots.needed() is True
    assert book.snapshots.run() != []


def test_an_upload_changing_the_queue_does_not_force_a_new_snapshot(book, identity, client_id, drive):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    book.snapshots.run()
    book.queue.process_due(drive)
    assert book.snapshots.needed() is False


def test_nothing_to_snapshot_on_an_empty_book(book):
    assert book.snapshots.run() == []
    assert book.db.scalar("SELECT count(*) FROM documents") == 0


def test_snapshot_and_csvs_are_queued_and_reach_drive(book, identity, client_id, drive):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    book.snapshots.run()
    assert book.queue.counts()["pending"] == 3
    assert book.queue.process_due(drive).uploaded == 3
    names = sorted(f["name"] for f in drive.files.values())
    assert any(n.endswith(".duckdb.zip") for n in names)
    assert any(n.startswith("livre_recettes_complet") and n.endswith(".csv") for n in names)
    assert any(n.startswith("registre_factures") for n in names)
    assert drive.path_of(next(iter(drive.files))) == ["MicroCompta", "2027", "sauvegardes"]


def test_the_copy_uses_the_database_rather_than_the_locked_file(book, client_id, tmp_path):
    """An open DuckDB file can't be copied on Windows. This is what proves the route works."""
    pay(book, client_id, date(2027, 3, 5))
    dest = tmp_path / "copy.duckdb"
    book.db.copy_to(dest)
    con = duckdb.connect(str(dest), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM ledger").fetchone()[0] == 1
    finally:
        con.close()
    pay(book, client_id, date(2027, 3, 6))  # still usable afterwards
    assert len(book.ledger.entries()) == 2


def test_ledger_csv_has_every_field_and_the_quarter_totals(book, identity, client_id):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25", fee="30", net="770",
        provider_ref="po_1", description="Annotation, semaine 9")
    doc = book.documents.get(book.exports.ledger_csv(2027))
    rows = _read_csv(book.documents.path_of(doc))
    header, entry = rows[0], rows[1]
    assert header[:5] == ["N° écriture", "Type", "Date d'encaissement", "Client (origine)", "Objet"]
    record = dict(zip(header, entry))
    assert record["Date d'encaissement"] == "2027-03-05"
    assert record["Montant brut"] == "1000,00"
    assert record["Taux (devise pour 1 EUR)"] == "1,250000"
    assert record["Brut EUR"] == "800,00"
    assert record["Frais EUR"] == "24,00"
    assert record["Net crédité"] == "770,00"
    assert record["Mode de règlement"] == "Stripe"
    assert record["Référence prestataire"] == "po_1"
    totals = {r[1]: r for r in rows if r[1].startswith("Total")}
    assert totals["Total T1 2027"][9] == "800,00"
    assert totals["Total T2 2027"][9] == "0,00"
    assert totals["Total 2027"][20] == "800,00"
    assert doc["rel_path"].startswith("2027/exports/")
    assert book.queue.counts()["pending"] == 1


def test_ledger_csv_shows_reversals_with_their_reason(book, identity, client_id):
    book.save_profile(identity)
    seq = pay(book, client_id, date(2027, 3, 5), "1000", "1.25")
    book.ledger.reverse(seq, "Enregistré deux fois")
    rows = _read_csv(book.documents.path_of(book.documents.get(book.exports.ledger_csv(2027))))
    header = rows[0]
    reversal = dict(zip(header, rows[2]))
    assert reversal["Type"] == "Annulation"
    assert reversal["Écriture annulée"] == "1"
    assert reversal["Motif"] == "Enregistré deux fois"
    assert reversal["Brut EUR"] == "-800,00"
    assert dict(zip(header, [r for r in rows if r[1] == "Total 2027"][0]))["Brut EUR"] == "0,00"


def test_ledger_pdf_is_french_with_quarter_totals_and_the_unconfirmed_label(
        book, identity, client_id):
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25", description="Annotation")
    seq = pay(book, client_id, date(2027, 4, 5), "1000", "1.25")
    book.ledger.reverse(seq, "Doublon")
    doc = book.documents.get(book.exports.ledger_pdf(2027))
    text = " ".join(
        " ".join(p.extract_text() for p in PdfReader(str(book.documents.path_of(doc))).pages)
        .replace(" ", " ").split()
    )
    for expected in ("Livre des recettes 2027", "Camille Exemple EI", "Total T1 2027", "Total T2 2027",
                     "Annulation de l'écriture 2 : Doublon", "Acme Annotation LLC",
                     "à confirmer auprès de l'URSSAF", "800,00 €"):
        assert expected in text, expected
    assert book.queue.counts()["pending"] == 1


def test_leftover_previews_are_cleared_at_the_next_start(tmp_path, pinned_today):
    from microcompta.core.book import Book
    from microcompta.core.db import Database

    first = Book(Database(tmp_path / "a.duckdb"), tmp_path / "docs")
    (first.documents.tmp_dir() / "apercu.pdf").write_bytes(b"x")
    first.close()
    second = Book(Database(tmp_path / "a.duckdb"), tmp_path / "docs")
    assert list(second.documents.tmp_dir().iterdir()) == []
    second.close()


def test_receipt_attachment_keeps_the_entry_untouched_and_is_queued(book, client_id, tmp_path):
    seq = pay(book, client_id, date(2027, 3, 5))
    before = book.ledger.get(seq)
    src = tmp_path / "stripe payout.pdf"
    src.write_bytes(b"%PDF receipt")
    doc_id = book.attach_receipt(seq, src)
    assert book.ledger.get(seq) == before
    assert book.ledger.verify() == []
    doc = book.documents.get(doc_id)
    assert doc["rel_path"] == "2027/recus/ecriture-00001_stripe payout.pdf"
    assert book.queue.counts()["pending"] == 1
    assert book.ledger.entries(2027)[0]["receipts"] == 1
    assert src.exists()  # a copy, not a move
