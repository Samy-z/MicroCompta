"""The whole set of records, opened together. The UI holds one of these."""

from __future__ import annotations

from pathlib import Path

from ..backup.queue import UploadQueue
from ..config import documents_dir
from .clients import Clients
from .db import Database
from .deadlines import DeadlineBook
from .documents import Documents
from .exports import Exports
from .figures import Figures
from .invoices import Invoices
from .ledger import Ledger
from .limits import Limits
from .profile import Profile, load_profile, save_profile
from .snapshots import Snapshots


class Book:
    def __init__(self, db: Database | None = None, documents_root: Path | None = None):
        self.db = db or Database()
        self.figures = Figures(self.db)
        self.clients = Clients(self.db)
        self.ledger = Ledger(self.db, self.clients)
        self.queue = UploadQueue(self.db)
        self.documents = Documents(
            self.db, documents_root or documents_dir(), on_added=self.queue.enqueue
        )
        self.queue.documents = self.documents
        self.documents.clear_tmp()
        self.invoices = Invoices(self.db, self.clients, self.figures, self.documents)
        self.limits = Limits(self.ledger, self.figures, self.profile)
        self.deadlines = DeadlineBook(self.db, self.figures)
        self.exports = Exports(self)
        self.snapshots = Snapshots(self)

    def profile(self) -> Profile:
        return load_profile(self.db)

    def save_profile(self, profile: Profile) -> None:
        save_profile(self.db, profile)

    def attach_receipt(self, seq: int, source: Path | str) -> int:
        """Keep a receipt with a ledger entry. The entry itself doesn't change."""
        entry = self.ledger.get(seq)
        if entry is None:
            raise ValueError(f"Entry {seq} does not exist.")
        source = Path(source)
        return self.documents.add_file(
            source, kind="receipt", year=entry["received_on"].year,
            name=f"ecriture-{seq:05d}_{source.name}", title=f"Reçu, écriture {seq}: {source.name}",
            ledger_seq=seq,
        )

    def verify(self) -> list[str]:
        """Every integrity check. Empty means the records are intact."""
        return self.ledger.verify() + self.invoices.verify() + self.documents.verify()

    def close(self) -> None:
        self.db.close()
