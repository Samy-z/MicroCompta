"""Backups of the records themselves: a database snapshot and CSV copies.

The invoice PDFs and receipts are uploaded one by one. These cover everything else,
and the CSVs mean the records can be read with nothing but a spreadsheet.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

import duckdb

from ..i18n import tr
from . import clock

# What the records are. The queue, folder cache and reminder log change on their own
# and would make every check look like new data.
_FINGERPRINT_TABLES = (
    ("ledger", "seq"),
    ("purchases", "seq"),
    ("purchase_documents", "seq, document_id"),
    ("invoice_register", "seq"),
    ("invoices", "id"),
    ("invoice_lines", "id"),
    ("clients", "id"),
    ("settings", "key"),
    ("figures", "key, effective_from"),
    ("deadline_state", "key"),
    ("annual_review", "year, item"),
)
_META_KEY = "last_snapshot_fingerprint"
SNAPSHOT_MEMBER = "microcompta.duckdb"


class Snapshots:
    def __init__(self, book: Any):
        self.book = book

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for table, order in _FINGERPRINT_TABLES:
            for row in self.book.db.rows(f"SELECT * FROM {table} ORDER BY {order}"):
                digest.update(repr(sorted(row.items())).encode("utf-8"))
        return digest.hexdigest()

    def needed(self) -> bool:
        return self.fingerprint() != self.book.db.get_meta(_META_KEY)

    def has_records(self) -> bool:
        return any(
            self.book.db.scalar(f"SELECT count(*) FROM {table}")
            for table in ("ledger", "purchases", "clients")
        )

    def run(self, force: bool = False) -> list[int]:
        """Snapshot if anything changed. Returns the documents added."""
        fingerprint = self.fingerprint()
        if not force and (fingerprint == self.book.db.get_meta(_META_KEY) or not self.has_records()):
            return []

        when = clock.now()
        stamp = when.strftime("%Y%m%d-%H%M%S")
        scratch = self.book.documents.tmp_dir()
        tmp = scratch / f"snapshot-{stamp}.duckdb"
        archive = scratch / f"snapshot-{stamp}.zip"
        tmp.unlink(missing_ok=True)
        try:
            self.book.db.copy_to(tmp)
            self._verify(tmp)
            # An almost empty database is still several MB of blocks, and this runs every
            # week or so for years. Zipped, it is a small fraction of that.
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.write(tmp, arcname=SNAPSHOT_MEMBER)
            doc_ids = [
                self.book.documents.add_file(
                    archive, kind="snapshot", year=when.year, name=f"microcompta_{stamp}.duckdb.zip",
                    title=f"Sauvegarde de la base {when:%Y-%m-%d %H:%M} UTC", move=True,
                )
            ]
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
        finally:
            tmp.unlink(missing_ok=True)
        doc_ids.append(self.book.exports.ledger_csv(None))
        doc_ids.append(self.book.exports.invoices_csv())
        if self.book.purchases.years():
            doc_ids.append(self.book.exports.purchases_csv(None))
        self.book.db.set_meta(_META_KEY, fingerprint)
        self.book.db.set_meta("last_snapshot_at", when.isoformat())
        return doc_ids

    def _verify(self, path: Path) -> None:
        """A snapshot that cannot be opened is worse than none, because it looks like one."""
        con = duckdb.connect(str(path), read_only=True)
        try:
            for table in ("ledger", "purchases", "invoice_register", "clients"):
                copied = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                live = self.book.db.scalar(f"SELECT count(*) FROM {table}")
                if copied != live:
                    raise RuntimeError(tr(
                        "Snapshot check failed: {table} has {copied} rows, expected {live}.",
                        table=table, copied=copied, live=live,
                    ))
        finally:
            con.close()
