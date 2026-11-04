"""The payments ledger (livre des recettes). Insert-only.

One entry per payment received. Turnover counts on the date received. There is no
edit or delete method: a correction is a reversing entry with a reason, followed by
a new entry if needed. Links to invoices and receipts live in their own tables,
because they are made after the entry exists and must not touch it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ..i18n import N_, tr
from . import clock
from .chain import GENESIS, chain_hash
from .clients import Clients
from .db import Database
from .errors import ImmutableError, ValidationError
from .ledger_policy import TurnoverPolicy, counted_eur
from .money import ZERO, round_money, to_decimal

# Stored as written here, translated when shown.
PAYMENT_METHODS = ("Stripe", "PayPal", N_("Bank transfer"), N_("Other"))
RATE_SOURCES = (N_("ECB reference"), N_("Provider rate"), N_("Other"))


def _payload(e: dict[str, Any]) -> dict[str, Any]:
    """The fields the hash covers, in a form that survives a round trip through DuckDB."""
    return {
        "seq": int(e["seq"]),
        "kind": e["kind"],
        "reverses_seq": None if e["reverses_seq"] is None else int(e["reverses_seq"]),
        "reason": e["reason"],
        "received_on": e["received_on"].isoformat(),
        "client_id": None if e["client_id"] is None else int(e["client_id"]),
        "client_name": e["client_name"],
        "description": e["description"],
        "currency": e["currency"],
        "amount_gross": f"{Decimal(e['amount_gross']):.2f}",
        "fx_rate": f"{Decimal(e['fx_rate']):.6f}",
        "fx_source": e["fx_source"],
        "eur_gross": f"{Decimal(e['eur_gross']):.2f}",
        "fee_amount": f"{Decimal(e['fee_amount']):.2f}",
        "fee_currency": e["fee_currency"],
        "fee_eur": f"{Decimal(e['fee_eur']):.2f}",
        "net_credited": f"{Decimal(e['net_credited']):.2f}",
        "net_currency": e["net_currency"],
        "payment_method": e["payment_method"],
        "provider_ref": e["provider_ref"],
        "recorded_at": e["recorded_at"].isoformat(),
    }


class Ledger:
    def __init__(self, db: Database, clients: Clients):
        self.db = db
        self.clients = clients

    # -- recording ----------------------------------------------------------
    def record_payment(
        self,
        *,
        received_on: date,
        client_id: int,
        description: str,
        amount_gross: Any,
        fx_rate: Any,
        net_credited: Any,
        payment_method: str,
        fx_source: str = "ECB reference",
        fee_amount: Any = "0",
        fee_currency: str | None = None,
        net_currency: str = "EUR",
        provider_ref: str = "",
    ) -> int:
        client = self.clients.get(client_id)
        if client is None:
            raise ValidationError(tr("Choose a client."))
        description = description.strip()
        if not description:
            raise ValidationError(tr("A description is required: the ledger must state the origin."))
        if received_on > clock.today():
            raise ValidationError(tr("The date received cannot be in the future."))
        if not payment_method.strip():
            raise ValidationError(tr("The payment method is required."))

        currency = client["currency"]
        gross = round_money(to_decimal(amount_gross, tr("Gross amount")))
        if gross <= 0:
            raise ValidationError(tr("The gross amount must be positive. Corrections are reversals."))
        rate = to_decimal(fx_rate, tr("Exchange rate"))
        if currency == "EUR":
            rate = Decimal(1)
        if rate <= 0:
            raise ValidationError(tr("The exchange rate must be positive."))
        fee = round_money(to_decimal(fee_amount or "0", tr("Provider fee")))
        if fee < 0:
            raise ValidationError(tr("The provider fee cannot be negative."))
        fee_currency = (fee_currency or currency).upper()
        net = round_money(to_decimal(net_credited, tr("Net credited")))
        if net <= 0:
            raise ValidationError(tr("The net credited must be positive."))

        provider_ref = provider_ref.strip()
        with self.db.transaction():
            if provider_ref:
                dup = self.db.scalar(
                    "SELECT seq FROM ledger l WHERE provider_ref = ? AND client_id = ? AND kind = 'payment' "
                    "AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reverses_seq = l.seq)",
                    [provider_ref, client_id],
                )
                if dup is not None:
                    raise ValidationError(tr(
                        "Reference '{reference}' is already recorded as entry {entry}.",
                        reference=provider_ref, entry=dup,
                    ))
            return self._insert({
                "kind": "payment",
                "reverses_seq": None,
                "reason": None,
                "received_on": received_on,
                "client_id": client_id,
                "client_name": client["name"],
                "description": description,
                "currency": currency,
                "amount_gross": gross,
                "fx_rate": rate,
                "fx_source": fx_source,
                "eur_gross": round_money(gross / rate),
                "fee_amount": fee,
                "fee_currency": fee_currency,
                "fee_eur": fee if fee_currency == "EUR" else round_money(fee / rate),
                "net_credited": net,
                "net_currency": net_currency.upper(),
                "payment_method": payment_method.strip(),
                "provider_ref": provider_ref,
            })

    def reverse(self, seq: int, reason: str, on: date | None = None) -> int:
        """Cancel an entry with a new one. Defaults to the date of the entry it cancels,
        so a mistake nets out in the period where it was counted."""
        reason = reason.strip()
        if not reason:
            raise ValidationError(tr("A reversal needs a reason."))
        original = self.get(seq)
        if original is None:
            raise ValidationError(tr("Entry {seq} does not exist.", seq=seq))
        if original["kind"] != "payment":
            raise ImmutableError(tr("A reversal cannot be reversed. Record a new payment instead."))
        with self.db.transaction():
            if self.db.scalar("SELECT seq FROM ledger WHERE reverses_seq = ?", [seq]) is not None:
                raise ImmutableError(tr("Entry {seq} has already been reversed.", seq=seq))
            return self._insert({
                "kind": "reversal",
                "reverses_seq": seq,
                "reason": reason,
                "received_on": on or original["received_on"],
                "client_id": original["client_id"],
                "client_name": original["client_name"],
                "description": original["description"],
                "currency": original["currency"],
                "amount_gross": -Decimal(original["amount_gross"]),
                "fx_rate": original["fx_rate"],
                "fx_source": original["fx_source"],
                "eur_gross": -Decimal(original["eur_gross"]),
                "fee_amount": -Decimal(original["fee_amount"]),
                "fee_currency": original["fee_currency"],
                "fee_eur": -Decimal(original["fee_eur"]),
                "net_credited": -Decimal(original["net_credited"]),
                "net_currency": original["net_currency"],
                "payment_method": original["payment_method"],
                "provider_ref": original["provider_ref"],
            })

    def _insert(self, entry: dict[str, Any]) -> int:
        with self.db.transaction():
            head = self.db.row("SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1")
            seq = int(head["seq"]) + 1 if head else 1
            prev_hash = head["entry_hash"] if head else GENESIS
            entry = {**entry, "seq": seq, "recorded_at": clock.now()}
            entry_hash = chain_hash(prev_hash, _payload(entry))
            self.db.execute(
                "INSERT INTO ledger (seq, kind, reverses_seq, reason, received_on, client_id, "
                "client_name, description, currency, amount_gross, fx_rate, fx_source, eur_gross, "
                "fee_amount, fee_currency, fee_eur, net_credited, net_currency, payment_method, "
                "provider_ref, recorded_at, prev_hash, entry_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [seq, entry["kind"], entry["reverses_seq"], entry["reason"], entry["received_on"],
                 entry["client_id"], entry["client_name"], entry["description"], entry["currency"],
                 entry["amount_gross"], entry["fx_rate"], entry["fx_source"], entry["eur_gross"],
                 entry["fee_amount"], entry["fee_currency"], entry["fee_eur"],
                 entry["net_credited"], entry["net_currency"], entry["payment_method"],
                 entry["provider_ref"], entry["recorded_at"], prev_hash, entry_hash],
            )
            return seq

    # -- reading ------------------------------------------------------------
    def get(self, seq: int) -> dict[str, Any] | None:
        return self.db.row("SELECT * FROM ledger WHERE seq = ?", [seq])

    def years(self) -> list[int]:
        rows = self.db.rows(
            "SELECT DISTINCT year(received_on) AS y FROM ledger ORDER BY y DESC"
        )
        return [int(r["y"]) for r in rows]

    def entries(self, year: int | None = None) -> list[dict[str, Any]]:
        """Chronological by date received, with everything derived joined on."""
        where = "WHERE year(l.received_on) = ?" if year is not None else ""
        rows = self.db.rows(
            "SELECT l.*, coalesce(c.taxed_in_france, FALSE) AS taxed_in_france, "
            "EXISTS (SELECT 1 FROM ledger r WHERE r.reverses_seq = l.seq) AS is_reversed "
            f"FROM ledger l LEFT JOIN clients c ON c.id = l.client_id {where} "
            "ORDER BY l.received_on, l.seq",
            [year] if year is not None else [],
        )
        links = self._invoice_links()
        receipts = self._receipt_counts()
        for row in rows:
            row["linked_invoice"] = ", ".join(links.get(int(row["seq"]), []))
            row["receipts"] = receipts.get(int(row["seq"]), 0)
        return rows

    def _invoice_links(self) -> dict[int, list[str]]:
        links: dict[int, list[str]] = {}
        for row in self.db.rows(
            "SELECT il.ledger_seq AS seq, r.number FROM invoice_lines il "
            "JOIN invoice_register r ON r.invoice_id = il.invoice_id "
            "WHERE il.ledger_seq IS NOT NULL ORDER BY r.seq"
        ):
            links.setdefault(int(row["seq"]), []).append(row["number"])
        return links

    def _receipt_counts(self) -> dict[int, int]:
        return {
            int(r["seq"]): int(r["n"])
            for r in self.db.rows(
                "SELECT ledger_seq AS seq, count(*) AS n FROM documents "
                "WHERE ledger_seq IS NOT NULL AND kind = 'receipt' GROUP BY ledger_seq"
            )
        }

    def quarter_totals(self, year: int, policy: TurnoverPolicy) -> list[dict[str, Any]]:
        """The totals every 3 months the livre des recettes must show."""
        totals = [
            {"quarter": q, "label": f"T{q} {year}", "eur_gross": ZERO, "fee_eur": ZERO,
             "net_eur": ZERO, "counted": ZERO, "entries": 0}
            for q in (1, 2, 3, 4)
        ]
        for e in self.entries(year):
            bucket = totals[(e["received_on"].month - 1) // 3]
            bucket["eur_gross"] += Decimal(e["eur_gross"])
            bucket["fee_eur"] += Decimal(e["fee_eur"])
            if e["net_currency"] == "EUR":
                bucket["net_eur"] += Decimal(e["net_credited"])
            bucket["counted"] += counted_eur(e, policy)
            bucket["entries"] += 1
        return totals

    # -- verification -------------------------------------------------------
    def verify(self) -> list[str]:
        """Problems found in the chain, as sentences. Empty means intact."""
        problems: list[str] = []
        prev_hash = GENESIS
        expected_seq = 1
        for row in self.db.rows("SELECT * FROM ledger ORDER BY seq"):
            seq = int(row["seq"])
            if seq != expected_seq:
                problems.append(tr("Ledger entry {seq} is missing.", seq=expected_seq))
                expected_seq = seq
            if row["prev_hash"] != prev_hash:
                problems.append(tr("Ledger entry {seq} does not follow the entry before it.", seq=seq))
            if chain_hash(row["prev_hash"], _payload(row)) != row["entry_hash"]:
                problems.append(tr("Ledger entry {seq} was changed after it was recorded.", seq=seq))
            prev_hash = row["entry_hash"]
            expected_seq += 1
        return problems
