"""The purchases register (registre des achats). Insert-only, like the ledger.

Required under the VAT franchise: a yearly register with the detail of purchases of goods
and services, backed by invoices and other supporting documents, shown on request (1 of II
of art. 286 CGI; BOI-TVA-DECLA-40-10-20 s.290; F23266).

Nothing here touches turnover, contributions or the form 2042-C-PRO figure: under the micro
regime, real costs are not deducted. The flat allowance stands in for them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ..i18n import N_, tr
from . import clock
from .chain import GENESIS, chain_hash
from .db import Database
from .errors import ImmutableError, ValidationError
from .money import ZERO, round_money, to_decimal

# Stored as written here, translated when shown.
PAYMENT_METHODS = (N_("Bank card"), N_("Direct debit"), N_("Bank transfer"), "PayPal", N_("Cash"),
                   N_("Cheque"), N_("Other"))

FIXED_ASSET = N_("Fixed asset")
CATEGORIES = (
    N_("Software and subscriptions"),
    N_("Transport and travel"),
    N_("Office supplies, documentation, phone"),
    N_("Small equipment"),
    FIXED_ASSET,
    N_("Professional fees"),
    N_("Insurance premiums"),
    N_("Financial charges"),
    N_("Other management costs"),
)


def _payload(e: dict[str, Any]) -> dict[str, Any]:
    """The fields the hash covers, in a form that survives a round trip through DuckDB."""
    return {
        "seq": int(e["seq"]),
        "kind": e["kind"],
        "reverses_seq": None if e["reverses_seq"] is None else int(e["reverses_seq"]),
        "reason": e["reason"],
        "paid_on": e["paid_on"].isoformat(),
        "supplier": e["supplier"],
        "description": e["description"],
        "category": e["category"],
        "amount_eur": f"{Decimal(e['amount_eur']):.2f}",
        "pro_share": f"{Decimal(e['pro_share']):.4f}",
        "payment_method": e["payment_method"],
        "piece_ref": e["piece_ref"],
        "recorded_at": e["recorded_at"].isoformat(),
    }


def professional_amount(entry: dict[str, Any]) -> Decimal:
    return round_money(Decimal(entry["amount_eur"]) * Decimal(entry["pro_share"]))


class Purchases:
    def __init__(self, db: Database):
        self.db = db

    # -- recording ----------------------------------------------------------
    def record(
        self,
        *,
        paid_on: date,
        supplier: str,
        description: str,
        category: str,
        amount_eur: Any,
        payment_method: str,
        pro_share: Any = "1",
        piece_ref: str = "",
    ) -> int:
        supplier = supplier.strip()
        if not supplier:
            raise ValidationError(tr("A purchase needs a supplier."))
        description = description.strip()
        if not description:
            raise ValidationError(tr("A purchase needs a description: the register must give the detail."))
        if category not in CATEGORIES:
            raise ValidationError(tr("Choose a category."))
        if paid_on > clock.today():
            raise ValidationError(tr("The payment date cannot be in the future."))
        if not payment_method.strip():
            raise ValidationError(tr("The payment method is required."))
        amount = round_money(to_decimal(amount_eur, tr("Amount paid")))
        if amount <= 0:
            raise ValidationError(tr("The amount paid must be positive. Corrections are reversals."))
        share = to_decimal(pro_share, tr("Professional share"))
        if not Decimal("0.01") <= share <= 1:
            raise ValidationError(tr("The professional share must be between 1% and 100%."))
        return self._insert({
            "kind": "purchase",
            "reverses_seq": None,
            "reason": None,
            "paid_on": paid_on,
            "supplier": supplier,
            "description": description,
            "category": category,
            "amount_eur": amount,
            "pro_share": share,
            "payment_method": payment_method.strip(),
            "piece_ref": piece_ref.strip(),
        })

    def reverse(self, seq: int, reason: str, on: date | None = None) -> int:
        """Cancel an entry with a new one. Defaults to the date of the entry it cancels."""
        reason = reason.strip()
        if not reason:
            raise ValidationError(tr("A reversal needs a reason."))
        original = self.get(seq)
        if original is None:
            raise ValidationError(tr("Entry {seq} does not exist.", seq=seq))
        if original["kind"] != "purchase":
            raise ImmutableError(tr("A reversal cannot be reversed. Record a new purchase instead."))
        with self.db.transaction():
            if self.db.scalar("SELECT seq FROM purchases WHERE reverses_seq = ?", [seq]) is not None:
                raise ImmutableError(tr("Entry {seq} has already been reversed.", seq=seq))
            return self._insert({
                "kind": "reversal",
                "reverses_seq": seq,
                "reason": reason,
                "paid_on": on or original["paid_on"],
                "supplier": original["supplier"],
                "description": original["description"],
                "category": original["category"],
                "amount_eur": -Decimal(original["amount_eur"]),
                "pro_share": original["pro_share"],
                "payment_method": original["payment_method"],
                "piece_ref": original["piece_ref"],
            })

    def _insert(self, entry: dict[str, Any]) -> int:
        with self.db.transaction():
            head = self.db.row("SELECT seq, entry_hash FROM purchases ORDER BY seq DESC LIMIT 1")
            seq = int(head["seq"]) + 1 if head else 1
            prev_hash = head["entry_hash"] if head else GENESIS
            entry = {**entry, "seq": seq, "recorded_at": clock.now()}
            self.db.execute(
                "INSERT INTO purchases (seq, kind, reverses_seq, reason, paid_on, supplier, description, "
                "category, amount_eur, pro_share, payment_method, piece_ref, recorded_at, prev_hash, "
                "entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [seq, entry["kind"], entry["reverses_seq"], entry["reason"], entry["paid_on"],
                 entry["supplier"], entry["description"], entry["category"], entry["amount_eur"],
                 entry["pro_share"], entry["payment_method"], entry["piece_ref"], entry["recorded_at"],
                 prev_hash, chain_hash(prev_hash, _payload(entry))],
            )
            return seq

    def link_document(self, seq: int, document_id: int) -> None:
        """A supporting document is added after the entry exists, and must not touch it."""
        self.db.execute("INSERT INTO purchase_documents (seq, document_id) VALUES (?, ?)", [seq, document_id])

    # -- reading ------------------------------------------------------------
    def get(self, seq: int) -> dict[str, Any] | None:
        return self.db.row("SELECT * FROM purchases WHERE seq = ?", [seq])

    def years(self) -> list[int]:
        rows = self.db.rows("SELECT DISTINCT year(paid_on) AS y FROM purchases ORDER BY y DESC")
        return [int(r["y"]) for r in rows]

    def entries(self, year: int | None = None) -> list[dict[str, Any]]:
        """Chronological by date paid, as the register must be."""
        where = "WHERE year(p.paid_on) = ?" if year is not None else ""
        rows = self.db.rows(
            "SELECT p.*, EXISTS (SELECT 1 FROM purchases r WHERE r.reverses_seq = p.seq) AS is_reversed, "
            "(SELECT count(*) FROM purchase_documents d WHERE d.seq = p.seq) AS receipts "
            f"FROM purchases p {where} ORDER BY p.paid_on, p.seq",
            [year] if year is not None else [],
        )
        for row in rows:
            row["pro_amount"] = professional_amount(row)
        return rows

    def totals(self, year: int) -> dict[str, Any]:
        """A reversal carries a negative amount, so a cancelled entry nets out here."""
        paid = pro = fixed_assets = ZERO
        entries = self.entries(year)
        for e in entries:
            paid += Decimal(e["amount_eur"])
            pro += e["pro_amount"]
            if e["category"] == FIXED_ASSET:
                fixed_assets += e["pro_amount"]
        return {
            "paid": paid,
            "pro": pro,
            "fixed_assets": fixed_assets,
            "charges": pro - fixed_assets,
            "entries": len(entries),
        }

    # -- verification -------------------------------------------------------
    def verify(self) -> list[str]:
        """Problems found in the chain, as sentences. Empty means intact."""
        problems: list[str] = []
        prev_hash = GENESIS
        expected_seq = 1
        for row in self.db.rows("SELECT * FROM purchases ORDER BY seq"):
            seq = int(row["seq"])
            if seq != expected_seq:
                problems.append(tr("Purchases register entry {seq} is missing.", seq=expected_seq))
                expected_seq = seq
            if row["prev_hash"] != prev_hash:
                problems.append(tr("Purchases register entry {seq} does not follow the entry before it.", seq=seq))
            if chain_hash(row["prev_hash"], _payload(row)) != row["entry_hash"]:
                problems.append(tr("Purchases register entry {seq} was changed after it was recorded.", seq=seq))
            prev_hash = row["entry_hash"]
            expected_seq += 1
        return problems
