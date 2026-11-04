"""Clients. Editable: issued invoices and ledger entries keep their own copy of the name."""

from __future__ import annotations

from typing import Any

from . import clock
from .db import Database
from .errors import ValidationError

# Shown wherever the flag is off. The exclusion is an inference, not a confirmed rule.
EXCLUSION_LABEL = "probably; SIE to confirm"

_FIELDS = ("name", "address", "country", "tax_id", "email", "currency",
           "taxed_in_france", "vat_note", "active")


class Clients:
    def __init__(self, db: Database):
        self.db = db

    def add(self, *, name: str, address: str = "", country: str = "", tax_id: str = "",
            email: str = "", currency: str = "USD", taxed_in_france: bool = False,
            vat_note: str = "", active: bool = True) -> int:
        name = name.strip()
        if not name:
            raise ValidationError("A client needs a name.")
        client_id = self.db.next_id("clients")
        self.db.execute(
            "INSERT INTO clients (id, name, address, country, tax_id, email, currency, "
            "taxed_in_france, vat_note, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [client_id, name, address, country, tax_id, email, currency.upper(),
             taxed_in_france, vat_note, active, clock.now()],
        )
        return client_id

    def update(self, client_id: int, **changes: Any) -> None:
        unknown = set(changes) - set(_FIELDS)
        if unknown:
            raise ValidationError(f"Unknown client field(s): {', '.join(sorted(unknown))}")
        if "name" in changes and not str(changes["name"]).strip():
            raise ValidationError("A client needs a name.")
        for key, value in changes.items():
            self.db.execute(f"UPDATE clients SET {key} = ? WHERE id = ?", [value, client_id])

    def get(self, client_id: int) -> dict[str, Any] | None:
        return self.db.row("SELECT * FROM clients WHERE id = ?", [client_id])

    def list(self, active_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE active" if active_only else ""
        return self.db.rows(f"SELECT * FROM clients {where} ORDER BY name")
