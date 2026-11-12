"""The whole set of records, opened together. The UI holds one of these."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ..backup.queue import UploadQueue
from ..config import documents_dir
from ..i18n import tr
from .clients import Clients
from .db import Database
from .deadlines import DeadlineBook
from .documents import Documents
from .exports import Exports
from .figures import Figures
from .invoices import Invoices
from .ledger import Ledger
from .limits import Limits, flat_allowance
from .profile import Profile, load_profile, save_profile
from .purchases import Purchases
from .snapshots import Snapshots


class Book:
    def __init__(self, db: Database | None = None, documents_root: Path | None = None):
        self.db = db or Database()
        self.figures = Figures(self.db)
        self.clients = Clients(self.db)
        self.ledger = Ledger(self.db, self.clients)
        self.purchases = Purchases(self.db)
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
        from ..imports.stripe import StripeInbox    # imports sit above core
        self.stripe = StripeInbox(self.db, self.clients)

    def profile(self) -> Profile:
        return load_profile(self.db)

    def save_profile(self, profile: Profile) -> None:
        save_profile(self.db, profile)

    def attach_receipt(self, seq: int, source: Path | str) -> int:
        """Keep a receipt with a ledger entry. The entry itself doesn't change."""
        entry = self.ledger.get(seq)
        if entry is None:
            raise ValueError(tr("Entry {seq} does not exist.", seq=seq))
        source = Path(source)
        return self.documents.add_file(
            source, kind="receipt", year=entry["received_on"].year,
            name=f"ecriture-{seq:05d}_{source.name}", title=f"Justificatif, écriture {seq} : {source.name}",
            ledger_seq=seq,
        )

    def attach_purchase_document(self, seq: int, source: Path | str) -> int:
        """Keep the invoice or receipt for a purchase. The entry itself doesn't change."""
        entry = self.purchases.get(seq)
        if entry is None:
            raise ValueError(tr("Entry {seq} does not exist.", seq=seq))
        source = Path(source)
        with self.db.transaction():
            doc_id = self.documents.add_file(
                source, kind="purchase", year=entry["paid_on"].year,
                name=f"achat-{seq:05d}_{source.name}", title=f"Justificatif d'achat {seq} : {source.name}",
            )
            self.purchases.link_document(seq, doc_id)
        return doc_id

    def regime_comparison(self, year: int) -> dict[str, Any]:
        """The arithmetic behind the micro-or-real question, and nothing more. The allowance is
        meant to cover every charge, social contributions included (F23267), so those go on the
        real side. Contributions are at the micro rate, as a yardstick: under a real regime
        they would be worked out on profit instead."""
        profile = self.profile()
        on = date(year, 1, 1)
        rate = self.figures.value(f"allowance_{profile.activity}", on)
        minimum = self.figures.value("allowance_min", on)
        turnover = self.limits.turnover(year, profile.policy)
        totals = self.purchases.totals(year)
        social = self.limits.social_contributions(year)
        return {
            "year": year,
            "turnover": turnover,
            "allowance": flat_allowance(turnover, rate, minimum),
            "allowance_rate": rate,
            "allowance_min": minimum,
            "purchases": totals,
            "social": social,
            "real_charges": totals["charges"] + social,
            "fixed_asset_threshold": self.figures.value("fixed_asset_threshold", on),
            "vl": profile.vl_enabled,
        }

    def verify(self) -> list[str]:
        """Every integrity check. Empty means the records are intact."""
        return (self.ledger.verify() + self.purchases.verify() + self.invoices.verify()
                + self.documents.verify())

    def close(self) -> None:
        self.db.close()
