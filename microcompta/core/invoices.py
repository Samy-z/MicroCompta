"""Invoices and credit notes.

A draft can change. Issuing allocates the next number, freezes everything printed
into the register, and writes the PDF; all of that succeeds together or not at all,
so a failure can never leave a gap in the numbering. After that the only correction
is a credit note.
"""

from __future__ import annotations

import calendar
import json
import os
import stat
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from ..i18n import fmt_date, tr
from . import clock
from .chain import GENESIS, chain_hash
from .clients import Clients
from .db import Database
from .documents import Documents, file_hashes
from .errors import ImmutableError, IssueBlocked, ValidationError
from .figures import Figures
from .invoice_pdf import render_invoice_pdf
from .money import ZERO, round_money, to_decimal
from .profile import Profile, load_profile, siren_is_valid

NUMBER_PREFIX = {"invoice": "FA", "credit_note": "AV"}


def _register_payload(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": int(r["seq"]),
        "number": r["number"],
        "invoice_id": int(r["invoice_id"]),
        "kind": r["kind"],
        "issue_date": r["issue_date"].isoformat(),
        "client_name": r["client_name"],
        "currency": r["currency"],
        "total": f"{Decimal(r['total']):.2f}",
        "fx_rate": f"{Decimal(r['fx_rate']):.6f}",
        "total_eur": f"{Decimal(r['total_eur']):.2f}",
        "snapshot_json": r["snapshot_json"],
        "pdf_sha256": r["pdf_sha256"],
        "document_id": int(r["document_id"]),
        "issued_at": r["issued_at"].isoformat(),
    }


class Invoices:
    def __init__(self, db: Database, clients: Clients, figures: Figures, documents: Documents,
                 render: Callable[..., None] = render_invoice_pdf):
        self.db = db
        self.clients = clients
        self.figures = figures
        self.documents = documents
        self.render = render

    # -- drafts -------------------------------------------------------------
    def uninvoiced_payments(self, client_id: int, year: int, month: int) -> list[dict[str, Any]]:
        """Payments of the month not reversed and not on a live invoice or draft."""
        return self.db.rows(
            "SELECT l.* FROM ledger l WHERE l.kind = 'payment' AND l.client_id = ? "
            "AND year(l.received_on) = ? AND month(l.received_on) = ? "
            "AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reverses_seq = l.seq) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id "
            "  WHERE il.ledger_seq = l.seq AND i.kind = 'invoice' "
            "  AND NOT EXISTS (SELECT 1 FROM invoices c WHERE c.credited_invoice_id = i.id "
            "                  AND c.status = 'issued')"
            ") ORDER BY l.received_on, l.seq",
            [client_id, year, month],
        )

    def create_monthly_draft(self, client_id: int, year: int, month: int) -> int:
        """A summary invoice from that month's payments, one line per payment."""
        client = self.clients.get(client_id)
        if client is None:
            raise ValidationError(tr("Choose a client."))
        payments = self.uninvoiced_payments(client_id, year, month)
        if not payments:
            raise ValidationError(tr(
                "No payment to invoice for {client} in {year}-{month}.",
                client=client["name"], year=year, month=f"{month:02d}",
            ))
        last_day = calendar.monthrange(year, month)[1]
        with self.db.transaction():
            invoice_id = self.db.next_id("invoices")
            self.db.execute(
                "INSERT INTO invoices (id, kind, status, client_id, service_start, service_end, "
                "currency, notes, created_at) VALUES (?, 'invoice', 'draft', ?, ?, ?, ?, '', ?)",
                [invoice_id, client_id, date(year, month, 1), date(year, month, last_day),
                 client["currency"], clock.now()],
            )
            self._insert_lines(invoice_id, [
                {
                    "description": p["description"],
                    "quantity": Decimal(1),
                    "unit_price": Decimal(p["amount_gross"]),
                    "ledger_seq": int(p["seq"]),
                    "payment_date": p["received_on"],
                }
                for p in payments
            ])
        return invoice_id

    def _insert_lines(self, invoice_id: int, lines: list[dict[str, Any]]) -> None:
        for position, line in enumerate(lines, start=1):
            quantity = to_decimal(line["quantity"], tr("Quantity"))
            unit_price = round_money(to_decimal(line["unit_price"], tr("Unit price")))
            description = str(line["description"]).strip()
            if not description:
                raise ValidationError(tr("Line {position} needs a description.", position=position))
            if quantity == 0:
                raise ValidationError(tr("Line {position} needs a quantity.", position=position))
            self.db.execute(
                "INSERT INTO invoice_lines (id, invoice_id, position, description, quantity, "
                "unit_price, total, ledger_seq, payment_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self.db.next_id("invoice_lines"), invoice_id, position, description, quantity,
                 unit_price, round_money(quantity * unit_price), line.get("ledger_seq"),
                 line.get("payment_date")],
            )

    def _require_draft(self, invoice_id: int) -> dict[str, Any]:
        invoice = self.get(invoice_id)
        if invoice is None:
            raise ValidationError(tr("Invoice {invoice} does not exist.", invoice=invoice_id))
        if invoice["status"] != "draft":
            raise ImmutableError(tr(
                "Invoice {number} has been issued and cannot change. Correct it with a credit note.",
                number=invoice["number"],
            ))
        return invoice

    def update_draft(self, invoice_id: int, *, service_start: date | None = None,
                     service_end: date | None = None, notes: str | None = None) -> None:
        self._require_draft(invoice_id)
        if service_start is not None:
            self.db.execute("UPDATE invoices SET service_start = ? WHERE id = ?",
                            [service_start, invoice_id])
        if service_end is not None:
            self.db.execute("UPDATE invoices SET service_end = ? WHERE id = ?",
                            [service_end, invoice_id])
        if notes is not None:
            self.db.execute("UPDATE invoices SET notes = ? WHERE id = ?", [notes, invoice_id])

    def set_lines(self, invoice_id: int, lines: list[dict[str, Any]]) -> None:
        """Replace a draft's lines, for hours and rate instead of quantity 1, say."""
        self._require_draft(invoice_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", [invoice_id])
            self._insert_lines(invoice_id, lines)

    def delete_draft(self, invoice_id: int) -> None:
        self._require_draft(invoice_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", [invoice_id])
            self.db.execute("DELETE FROM invoices WHERE id = ?", [invoice_id])

    # -- reading ------------------------------------------------------------
    def get(self, invoice_id: int) -> dict[str, Any] | None:
        return self.db.row(
            "SELECT i.*, r.seq, r.number, r.issue_date, r.total AS issued_total, r.fx_rate, "
            "r.total_eur, r.document_id, r.client_name AS issued_client_name, c.name AS client_name "
            "FROM invoices i LEFT JOIN invoice_register r ON r.invoice_id = i.id "
            "LEFT JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
            [invoice_id],
        )

    def lines(self, invoice_id: int) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY position", [invoice_id]
        )

    def list(self) -> list[dict[str, Any]]:
        """Newest first. Issued documents show what was frozen; drafts show what is there now."""
        return self.db.rows(
            "SELECT i.id, i.kind, i.status, i.service_start, i.service_end, i.currency, "
            "r.seq, r.number, r.issue_date, r.fx_rate, r.total_eur, r.document_id, "
            "coalesce(r.client_name, c.name) AS client_name, "
            "coalesce(r.total, (SELECT coalesce(sum(total), 0) FROM invoice_lines il "
            "                   WHERE il.invoice_id = i.id)) AS total, "
            "(SELECT o.number FROM invoice_register o WHERE o.invoice_id = i.credited_invoice_id) "
            "   AS credits_number, "
            "(SELECT n.number FROM invoices c2 JOIN invoice_register n ON n.invoice_id = c2.id "
            "  WHERE c2.credited_invoice_id = i.id) AS credited_by "
            "FROM invoices i LEFT JOIN invoice_register r ON r.invoice_id = i.id "
            "LEFT JOIN clients c ON c.id = i.client_id "
            "ORDER BY r.seq DESC NULLS FIRST, i.id DESC"
        )

    def register(self) -> list[dict[str, Any]]:
        return self.db.rows("SELECT * FROM invoice_register ORDER BY seq")

    def stale(self) -> list[dict[str, Any]]:
        """Issued invoices with a reversed payment on them: each needs a credit note."""
        return self.db.rows(
            "SELECT DISTINCT r.number, r.invoice_id FROM invoice_register r "
            "JOIN invoices i ON i.id = r.invoice_id "
            "JOIN invoice_lines il ON il.invoice_id = i.id "
            "JOIN ledger rev ON rev.reverses_seq = il.ledger_seq "
            "WHERE i.kind = 'invoice' AND NOT EXISTS ("
            "  SELECT 1 FROM invoices c WHERE c.credited_invoice_id = i.id AND c.status = 'issued'"
            ") ORDER BY r.number"
        )

    # -- issuing ------------------------------------------------------------
    def next_number(self, kind: str, issue_date: date, seq: int) -> str:
        return f"{NUMBER_PREFIX[kind]}-{issue_date.year}-{seq:04d}"

    def _last_issue_date(self) -> date | None:
        return self.db.scalar("SELECT issue_date FROM invoice_register ORDER BY seq DESC LIMIT 1")

    def blocking_reasons(self, invoice_id: int, issue_date: date, fx_rate: Any,
                         fx_rate_date: date | None) -> list[str]:
        """Everything that stops a final invoice, all at once rather than one per click."""
        reasons: list[str] = []
        profile = load_profile(self.db)
        invoice = self.get(invoice_id)
        client = self.clients.get(invoice["client_id"]) if invoice else None
        lines = self.lines(invoice_id)

        if not siren_is_valid(profile.siren):
            reasons.append(
                tr("No valid SIREN in Settings. Drafts are fine, but a final invoice needs one.")
                if not profile.siren.strip() else
                tr("The SIREN in Settings ('{siren}') is not valid: 9 digits, check digit.",
                   siren=profile.siren)
            )
        if not profile.legal_name.strip():
            reasons.append(tr("Your name is missing in Settings."))
        if not profile.address.strip():
            reasons.append(tr("Your address is missing in Settings."))
        if not profile.vat_mention.strip():
            reasons.append(tr("The VAT mention is empty in Settings."))
        if not profile.late_rate_text.strip():
            reasons.append(tr("The late-payment rate text is empty in Settings."))
        if client is None or not client["name"].strip():
            reasons.append(tr("The client is missing."))
        elif not (client["address"] or "").strip():
            reasons.append(tr("The address of {client} is missing.", client=client["name"]))
        if not lines:
            reasons.append(tr("The invoice has no lines."))
        elif sum(Decimal(l["total"]) for l in lines) == 0:
            reasons.append(tr("The invoice total is zero."))
        if invoice and (invoice["service_start"] is None or invoice["service_end"] is None):
            reasons.append(tr("The service dates are missing."))
        elif invoice and invoice["service_start"] > invoice["service_end"]:
            reasons.append(tr("The service period ends before it starts."))

        if issue_date > clock.today():
            reasons.append(tr("The issue date cannot be in the future."))
        last = self._last_issue_date()
        if last is not None and issue_date < last:
            reasons.append(tr(
                "Numbering must stay chronological: the last document was issued on {date}.",
                date=fmt_date(last),
            ))
        if invoice and invoice["currency"] != "EUR":
            try:
                rate = to_decimal(fx_rate, tr("Exchange rate"))
            except ValidationError:
                rate = Decimal(0)
            if rate <= 0:
                reasons.append(tr(
                    "A foreign-currency invoice must show its exchange rate: enter the ECB "
                    "reference rate for the issue date."
                ))
            if fx_rate_date is None:
                reasons.append(tr("Enter the date of the exchange rate."))
            elif fx_rate_date > issue_date:
                reasons.append(tr("The exchange rate cannot be dated after the issue date."))

        reversed_lines = [
            l["position"] for l in lines
            if l["ledger_seq"] is not None and self.db.scalar(
                "SELECT count(*) FROM ledger WHERE reverses_seq = ?", [l["ledger_seq"]]
            )
        ]
        if invoice and invoice["kind"] == "invoice" and reversed_lines:
            reasons.append(tr(
                "These lines refer to a reversed payment: {lines}.",
                lines=", ".join(str(p) for p in reversed_lines),
            ))
        return reasons

    def issue_warnings(self, invoice_id: int) -> list[str]:
        """Worth a second look, but not a reason to refuse."""
        warnings = []
        for line in self.lines(invoice_id):
            if line["ledger_seq"] is None:
                continue
            entry = self.db.row("SELECT amount_gross FROM ledger WHERE seq = ?", [line["ledger_seq"]])
            if entry and Decimal(entry["amount_gross"]) != Decimal(line["total"]):
                warnings.append(tr(
                    "Line {position} totals {total} but payment {entry} was {amount}.",
                    position=line["position"], total=line["total"], entry=line["ledger_seq"],
                    amount=entry["amount_gross"],
                ))
        return warnings

    def _snapshot(self, invoice: dict[str, Any], lines: list[dict[str, Any]], number: str,
                  issue_date: date | None, fx_rate: Decimal | None, fx_rate_date: date | None,
                  fx_source: str, profile: Profile, credits_number: str | None) -> dict[str, Any]:
        client = self.clients.get(invoice["client_id"]) or {}
        total = sum((Decimal(l["total"]) for l in lines), ZERO)
        on = issue_date or clock.today()
        is_euro = invoice["currency"] == "EUR"
        total_eur = total if is_euro else (round_money(total / fx_rate) if fx_rate else None)
        payment_dates = sorted({l["payment_date"] for l in lines if l["payment_date"]})
        return {
            "kind": invoice["kind"],
            "number": number,
            "issue_date": issue_date.isoformat() if issue_date else None,
            "service_start": invoice["service_start"].isoformat() if invoice["service_start"] else None,
            "service_end": invoice["service_end"].isoformat() if invoice["service_end"] else None,
            "seller": {
                "name": profile.display_name,
                "status": "Entrepreneur individuel",
                "address": profile.address,
                "siren": "".join(profile.siren.split()),
                "email": profile.email,
            },
            "client": {
                "name": client.get("name", ""),
                "address": client.get("address") or "",
                "country": client.get("country") or "",
                "tax_id": client.get("tax_id") or "",
                "email": client.get("email") or "",
            },
            "currency": invoice["currency"],
            "lines": [
                {
                    "description": l["description"],
                    "quantity": format(Decimal(l["quantity"]), "f"),
                    "unit_price": f"{Decimal(l['unit_price']):.2f}",
                    "total": f"{Decimal(l['total']):.2f}",
                    "payment_date": l["payment_date"].isoformat() if l["payment_date"] else None,
                }
                for l in lines
            ],
            "total": f"{total:.2f}",
            "total_eur": f"{total_eur:.2f}" if total_eur is not None else None,
            "fx": None if is_euro or not fx_rate else {
                "rate": f"{fx_rate:.6f}",
                "date": fx_rate_date.isoformat() if fx_rate_date else None,
                "source": fx_source,
            },
            "vat_mention": profile.vat_mention,
            "payment_dates": [d.isoformat() for d in payment_dates],
            "payment_terms": profile.payment_terms,
            "late_rate_text": profile.late_rate_text,
            "recovery_indemnity": format(self.figures.value("recovery_indemnity", on), "f"),
            "credits_number": credits_number,
            "reason": invoice["reason"],
            "notes": invoice["notes"] or "",
        }

    def preview(self, invoice_id: int, path: Path | str, fx_rate: Any = None,
                fx_rate_date: date | None = None) -> Path:
        """A draft PDF, marked as such, with no number. Allowed without a SIREN.

        Goes wherever the caller says: a preview is not a recorded document.
        """
        invoice = self._require_draft(invoice_id)
        rate = None
        if fx_rate not in (None, ""):
            rate = to_decimal(fx_rate, tr("Exchange rate"))
            if rate <= 0:
                rate = None
        snapshot = self._snapshot(
            invoice, self.lines(invoice_id), "BROUILLON", clock.today(), rate, fx_rate_date,
            "taux de référence BCE", load_profile(self.db), None,
        )
        path = Path(path)
        self.render(snapshot, path, draft=True)
        return path

    def issue(self, invoice_id: int, issue_date: date, fx_rate: Any = None,
              fx_rate_date: date | None = None,
              fx_source: str = "taux de référence BCE") -> str:
        """Make a draft final. Returns the number."""
        invoice = self._require_draft(invoice_id)
        reasons = self.blocking_reasons(invoice_id, issue_date, fx_rate, fx_rate_date)
        if reasons:
            raise IssueBlocked(reasons)

        profile = load_profile(self.db)
        is_euro = invoice["currency"] == "EUR"
        rate = Decimal(1) if is_euro else to_decimal(fx_rate, tr("Exchange rate"))
        lines = self.lines(invoice_id)

        credits_number = None
        if invoice["credited_invoice_id"] is not None:
            credits_number = self.db.scalar(
                "SELECT number FROM invoice_register WHERE invoice_id = ?",
                [invoice["credited_invoice_id"]],
            )

        fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=self.documents.tmp_dir())
        os.close(fd)
        tmp = Path(tmp_name)
        stored: Path | None = None
        try:
            with self.db.transaction():
                head = self.db.row(
                    "SELECT seq, entry_hash FROM invoice_register ORDER BY seq DESC LIMIT 1"
                )
                seq = int(head["seq"]) + 1 if head else 1
                prev_hash = head["entry_hash"] if head else GENESIS
                number = self.next_number(invoice["kind"], issue_date, seq)

                snapshot = self._snapshot(
                    invoice, lines, number, issue_date, None if is_euro else rate, fx_rate_date,
                    fx_source, profile, credits_number,
                )
                self.render(snapshot, tmp, draft=False)
                pdf_sha256 = file_hashes(tmp)[0]

                document_id = self.documents.add_file(
                    tmp, kind="invoice", year=issue_date.year, name=f"{number}.pdf",
                    title=("Facture d'avoir " if invoice["kind"] == "credit_note" else "Facture ") + number,
                    invoice_id=invoice_id, move=True, read_only=True,
                )
                stored = self.documents.path_of(self.documents.get(document_id))

                record = {
                    "seq": seq,
                    "number": number,
                    "invoice_id": invoice_id,
                    "kind": invoice["kind"],
                    "issue_date": issue_date,
                    "client_name": snapshot["client"]["name"],
                    "currency": invoice["currency"],
                    "total": Decimal(snapshot["total"]),
                    "fx_rate": rate,
                    "total_eur": Decimal(snapshot["total_eur"]),
                    "snapshot_json": json.dumps(snapshot, sort_keys=True, ensure_ascii=False),
                    "pdf_sha256": pdf_sha256,
                    "document_id": document_id,
                    "issued_at": clock.now(),
                }
                entry_hash = chain_hash(prev_hash, _register_payload(record))
                self.db.execute(
                    "INSERT INTO invoice_register (seq, number, invoice_id, kind, issue_date, "
                    "client_name, currency, total, fx_rate, total_eur, snapshot_json, pdf_sha256, "
                    "document_id, issued_at, prev_hash, entry_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [record["seq"], record["number"], record["invoice_id"], record["kind"],
                     record["issue_date"], record["client_name"], record["currency"],
                     record["total"], record["fx_rate"], record["total_eur"],
                     record["snapshot_json"], record["pdf_sha256"], record["document_id"],
                     record["issued_at"], prev_hash, entry_hash],
                )
                self.db.execute("UPDATE invoices SET status = 'issued' WHERE id = ?", [invoice_id])
        except BaseException:
            tmp.unlink(missing_ok=True)
            # The rollback forgets the document, so its file must go too. Left behind, the
            # number on it would be used again and the real invoice saved as FA-..._2.pdf.
            if stored is not None and stored.exists():
                stored.chmod(stat.S_IWRITE)
                stored.unlink()
            raise
        return number

    def credit_note(self, invoice_id: int, reason: str, issue_date: date) -> str:
        """Cancel an issued invoice in full. Its payments can then be invoiced again."""
        reason = reason.strip()
        if not reason:
            raise ValidationError(tr("A credit note needs a reason."))
        original = self.get(invoice_id)
        if original is None or original["status"] != "issued":
            raise ValidationError(tr("Only an issued invoice can be credited."))
        if original["kind"] != "invoice":
            raise ValidationError(tr("A credit note cannot itself be credited."))
        if self.db.scalar(
            "SELECT count(*) FROM invoices WHERE credited_invoice_id = ?", [invoice_id]
        ):
            raise ImmutableError(
                tr("Invoice {number} already has a credit note.", number=original["number"])
            )

        lines = self.lines(invoice_id)
        snapshot = json.loads(self.db.scalar(
            "SELECT snapshot_json FROM invoice_register WHERE invoice_id = ?", [invoice_id]
        ))
        fx = snapshot.get("fx")
        with self.db.transaction():
            credit_id = self.db.next_id("invoices")
            self.db.execute(
                "INSERT INTO invoices (id, kind, status, client_id, service_start, service_end, "
                "currency, notes, credited_invoice_id, reason, created_at) "
                "VALUES (?, 'credit_note', 'draft', ?, ?, ?, ?, '', ?, ?, ?)",
                [credit_id, original["client_id"], original["service_start"],
                 original["service_end"], original["currency"], invoice_id, reason, clock.now()],
            )
            self._insert_lines(credit_id, [
                {
                    "description": l["description"],
                    "quantity": -Decimal(l["quantity"]),
                    "unit_price": Decimal(l["unit_price"]),
                    "ledger_seq": l["ledger_seq"],
                    "payment_date": l["payment_date"],
                }
                for l in lines
            ])
            # Same rate as the invoice it cancels, so the euro amounts mirror exactly.
            return self.issue(
                credit_id, issue_date,
                fx_rate=fx["rate"] if fx else None,
                fx_rate_date=date.fromisoformat(fx["date"]) if fx and fx["date"] else None,
                fx_source=fx["source"] if fx else "taux de référence BCE",
            )

    # -- verification -------------------------------------------------------
    def verify(self) -> list[str]:
        """Broken numbering, changed records or changed PDFs. Empty means intact."""
        problems: list[str] = []
        prev_hash = GENESIS
        expected = 1
        last_date: date | None = None
        for row in self.register():
            seq = int(row["seq"])
            if seq != expected:
                problems.append(tr("Invoice numbering has a gap: {seq} is missing.", seq=expected))
                expected = seq
            if row["prev_hash"] != prev_hash:
                problems.append(tr("{number} does not follow the document before it.", number=row["number"]))
            if chain_hash(row["prev_hash"], _register_payload(row)) != row["entry_hash"]:
                problems.append(tr("{number} was changed after it was issued.", number=row["number"]))
            if last_date is not None and row["issue_date"] < last_date:
                problems.append(tr("{number} is dated before the document it follows.", number=row["number"]))
            doc = self.documents.get(int(row["document_id"]))
            if doc is None:
                problems.append(tr("{number} has no document on record.", number=row["number"]))
            elif doc["sha256"] != row["pdf_sha256"]:
                problems.append(tr("The document on record for {number} is not the one issued.", number=row["number"]))
            live = self.db.scalar(
                "SELECT status FROM invoices WHERE id = ?", [row["invoice_id"]]
            )
            if live != "issued":
                problems.append(tr("{number} is registered but no longer marked as issued.", number=row["number"]))
            prev_hash = row["entry_hash"]
            last_date = row["issue_date"]
            expected += 1
        return problems
