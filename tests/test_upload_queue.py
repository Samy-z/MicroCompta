"""The upload queue against a fake Drive: nothing is lost, offline is normal."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from conftest import AuthRequired, PermanentDriveError, TransientDriveError
from microcompta.backup.queue import backoff_seconds
from microcompta.core import clock


def add_doc(book, tmp_path, name="recu.pdf", content=b"receipt body", kind="receipt", year=2027):
    src = tmp_path / name
    src.write_bytes(content)
    return book.documents.add_file(src, kind=kind, year=year, name=name)


def status_of(book, doc_id):
    return book.db.row("SELECT * FROM upload_queue WHERE document_id = ?", [doc_id])


def advance(monkeypatch, seconds=7200):
    later = clock.now() + timedelta(seconds=seconds)
    monkeypatch.setattr(clock, "now", lambda: later)


def test_adding_a_document_queues_it_as_pending(book, tmp_path):
    doc_id = add_doc(book, tmp_path)
    assert status_of(book, doc_id)["status"] == "pending"
    assert book.queue.counts() == {"pending": 1, "uploaded": 0, "failed": 0}


def test_upload_verifies_and_marks_uploaded(book, tmp_path, drive):
    doc_id = add_doc(book, tmp_path)
    report = book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert report.uploaded == 1
    assert row["status"] == "uploaded"
    assert row["drive_md5"] == book.documents.get(doc_id)["md5"]
    assert row["last_error"] is None
    assert "metadata" in drive.calls  # asked Drive, rather than trusting the upload reply


def test_files_are_organised_by_year(book, tmp_path, drive):
    doc_a = add_doc(book, tmp_path, "a.pdf", b"a", "receipt", 2027)
    doc_b = add_doc(book, tmp_path, "b.pdf", b"b", "invoice", 2028)
    book.queue.process_due(drive)
    path_a = drive.path_of(status_of(book, doc_a)["drive_file_id"])
    path_b = drive.path_of(status_of(book, doc_b)["drive_file_id"])
    assert path_a == ["MicroCompta", "2027", "recus"]
    assert path_b == ["MicroCompta", "2028", "factures"]


def test_folders_are_reused_not_recreated(book, tmp_path, drive):
    add_doc(book, tmp_path, "a.pdf", b"a")
    book.queue.process_due(drive)
    made = drive.calls.count("create_folder")
    add_doc(book, tmp_path, "b.pdf", b"b")
    book.queue.process_due(drive)
    assert drive.calls.count("create_folder") == made


def test_offline_stays_pending_and_backs_off(book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path)
    drive.fail_next = [TransientDriveError("No connection to Google Drive.")]
    report = book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert report.deferred == 1
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert "No connection" in row["last_error"]
    assert not book.queue.has_due()
    advance(monkeypatch, 61)
    assert book.queue.has_due()
    assert book.queue.process_due(drive).uploaded == 1
    assert status_of(book, doc_id)["status"] == "uploaded"


def test_going_offline_stops_the_batch(book, tmp_path, drive):
    add_doc(book, tmp_path, "a.pdf", b"a")
    add_doc(book, tmp_path, "b.pdf", b"b")
    drive.fail_next = [TransientDriveError("offline")]
    report = book.queue.process_due(drive)
    assert report.deferred == 1
    assert report.uploaded == 0
    assert len(drive.calls) == 1


def test_a_long_outage_never_counts_as_failed(book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path)
    for _ in range(30):
        drive.fail_next = [TransientDriveError("offline")]
        book.queue.process_due(drive)
        advance(monkeypatch)
    row = status_of(book, doc_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 30


@pytest.mark.parametrize("attempts, seconds", [(1, 60), (2, 120), (3, 240), (7, 3600), (30, 3600)])
def test_backoff_is_capped(attempts, seconds):
    assert backoff_seconds(attempts) == seconds


def test_signed_out_keeps_documents_pending_and_counts_no_attempt(book, tmp_path, drive):
    doc_id = add_doc(book, tmp_path)
    drive.fail_next = [AuthRequired("Reconnect Google Drive.")]
    report = book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert report.needs_sign_in is True
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert "Reconnect" in row["last_error"]


def test_a_hard_error_is_visible_as_failed_and_retried_later(book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path, "x.pdf")
    drive.fail_next = [PermanentDriveError("HTTP 403 storage quota exceeded", status=403)]
    report = book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert report.failed == 1
    assert report.newly_failed == ["x.pdf"]
    assert row["status"] == "failed"
    assert "quota" in row["last_error"]
    assert not book.queue.has_due()
    advance(monkeypatch, 6 * 3600 + 1)
    assert book.queue.has_due()
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "uploaded"


def test_manual_retry_runs_a_failed_document_now(book, tmp_path, drive):
    doc_id = add_doc(book, tmp_path)
    drive.fail_next = [PermanentDriveError("HTTP 403", status=403)]
    book.queue.process_due(drive)
    assert not book.queue.has_due()
    book.queue.retry(doc_id)
    assert book.queue.has_due()
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "uploaded"


def test_one_bad_document_does_not_block_the_next(book, tmp_path, drive):
    first = add_doc(book, tmp_path, "a.pdf", b"a")
    second = add_doc(book, tmp_path, "b.pdf", b"b")
    book.documents.path_of(book.documents.get(first)).unlink()
    report = book.queue.process_due(drive)
    assert report.failed == 1
    assert report.uploaded == 1
    assert status_of(book, first)["status"] == "failed"
    assert status_of(book, second)["status"] == "uploaded"


def test_a_checksum_mismatch_fails_keeps_the_bad_copy_and_uploads_again(
        book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path)
    drive.corrupt_uploads = True
    book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert row["status"] == "failed"
    assert "Checksum mismatch" in row["last_error"]
    assert len(drive.files) == 1  # still there: nothing is ever deleted

    drive.corrupt_uploads = False
    advance(monkeypatch, 6 * 3600 + 1)
    book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert row["status"] == "uploaded"
    assert row["drive_md5"] == book.documents.get(doc_id)["md5"]
    assert len(drive.files) == 2


def test_a_lost_upload_reply_does_not_create_a_duplicate(book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path)
    drive.lose_upload_replies = 1
    assert book.queue.process_due(drive).deferred == 1
    assert len(drive.files) == 1
    advance(monkeypatch)
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "uploaded"
    assert len(drive.files) == 1


def test_a_checksum_not_ready_yet_is_rechecked_not_reuploaded(book, tmp_path, drive, monkeypatch):
    doc_id = add_doc(book, tmp_path)
    drive.hide_md5_once = True
    assert book.queue.process_due(drive).deferred == 1
    assert status_of(book, doc_id)["status"] == "pending"
    advance(monkeypatch)
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "uploaded"
    assert len(drive.files) == 1


def test_a_local_file_that_changed_is_not_uploaded(book, tmp_path, drive):
    doc_id = add_doc(book, tmp_path)
    book.documents.path_of(book.documents.get(doc_id)).write_bytes(b"tampered")
    book.queue.process_due(drive)
    row = status_of(book, doc_id)
    assert row["status"] == "failed"
    assert "no longer matches" in row["last_error"]
    assert drive.files == {}


def test_uploaded_documents_are_not_sent_again(book, tmp_path, drive):
    add_doc(book, tmp_path)
    book.queue.process_due(drive)
    drive.calls.clear()
    book.queue.retry()
    assert not book.queue.has_due()
    assert book.queue.process_due(drive).uploaded == 0
    assert drive.calls == []


def test_the_queue_survives_a_restart(tmp_path, pinned_today, drive):
    from microcompta.core.book import Book
    from microcompta.core.db import Database

    path = tmp_path / "q.duckdb"
    first = Book(Database(path), tmp_path / "docs")
    doc_id = add_doc(first, tmp_path)
    first.close()

    second = Book(Database(path), tmp_path / "docs")
    assert status_of(second, doc_id)["status"] == "pending"
    assert second.queue.process_due(drive).uploaded == 1
    second.close()


def test_a_folder_removed_in_drive_is_looked_up_again(book, tmp_path, drive, monkeypatch):
    add_doc(book, tmp_path, "a.pdf", b"a")
    book.queue.process_due(drive)
    doc_id = add_doc(book, tmp_path, "b.pdf", b"b")
    drive.fail_next = [PermanentDriveError("HTTP 404 File not found", status=404)]
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "failed"
    assert book.db.scalar("SELECT count(*) FROM drive_folders") == 0
    advance(monkeypatch, 6 * 3600 + 1)
    book.queue.process_due(drive)
    assert status_of(book, doc_id)["status"] == "uploaded"


def test_issuing_an_invoice_reaches_drive(book, identity, client_id, tmp_path, drive):
    from conftest import pay

    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = book.invoices.create_monthly_draft(client_id, 2027, 3)
    book.invoices.issue(invoice_id, date(2027, 4, 1), fx_rate="1.08", fx_rate_date=date(2027, 4, 1))
    assert book.queue.process_due(drive).uploaded == 1
    remote = next(iter(drive.files.values()))
    assert remote["name"] == "FA-2027-0001.pdf"
    doc = book.documents.get(int(book.invoices.get(invoice_id)["document_id"]))
    assert remote["content"] == book.documents.path_of(doc).read_bytes()


def test_pending_timestamps_are_naive_utc(book, tmp_path):
    doc_id = add_doc(book, tmp_path)
    assert isinstance(status_of(book, doc_id)["next_attempt_at"], datetime)
