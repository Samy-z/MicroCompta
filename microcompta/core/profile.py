"""The owner's identity and choices. Entered at first launch, stored locally."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from typing import Any

from ..i18n import DEFAULT_LANGUAGE
from .db import Database
from .ledger_policy import TurnoverPolicy

DEFAULT_VAT_MENTION = "TVA non applicable, art. 293 B du CGI"
DEFAULT_LATE_RATE = (
    "En cas de retard de paiement, pénalités au taux de 3 fois le taux d'intérêt légal."
)
DEFAULT_PAYMENT_TERMS = "Paiement à réception, sans escompte."


def siren_is_valid(siren: str) -> bool:
    """Nine digits passing the Luhn check. All zeros passes Luhn but is not a SIREN."""
    digits = "".join(siren.split())
    if len(digits) != 9 or not digits.isdigit() or set(digits) == {"0"}:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass
class Profile:
    language: str = DEFAULT_LANGUAGE

    # Identity (printed on invoices)
    legal_name: str = ""
    address: str = ""
    siren: str = ""
    email: str = ""

    # Activity
    start_date: date | None = None
    activity: str = "bnc"              # bnc | bic
    declaration_frequency: str = "monthly"  # monthly | quarterly
    acre_enabled: bool = False
    vl_enabled: bool = False

    # Unconfirmed choices: URSSAF to answer. Both can change without touching a record.
    turnover_basis: str = "gross"      # gross | net_of_fees
    fx_policy: str = "entry_rate"      # entry_rate | provider_effective

    # Invoice wording
    vat_mention: str = DEFAULT_VAT_MENTION
    late_rate_text: str = DEFAULT_LATE_RATE
    payment_terms: str = DEFAULT_PAYMENT_TERMS

    # App behaviour
    reminder_days: str = "14,7,3,1"
    keep_in_tray: bool = True
    dock_collapsed: bool = False

    @property
    def display_name(self) -> str:
        """The name with "EI" that every invoice must carry."""
        return f"{self.legal_name.strip()} EI" if self.legal_name.strip() else ""

    @property
    def policy(self) -> TurnoverPolicy:
        return TurnoverPolicy(basis=self.turnover_basis, fx=self.fx_policy)

    @property
    def is_set_up(self) -> bool:
        return bool(self.legal_name.strip() and self.address.strip() and self.start_date)

    def reminder_thresholds(self) -> list[int]:
        found = []
        for part in self.reminder_days.split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
        return sorted(set(found), reverse=True) or [14, 7, 3, 1]


_BOOLS = {f.name for f in fields(Profile) if f.type in ("bool", bool)}
_DATES = {f.name for f in fields(Profile) if "date" in str(f.type)}


def load_profile(db: Database) -> Profile:
    stored = {r["key"]: r["value"] for r in db.rows("SELECT key, value FROM settings")}
    values: dict[str, Any] = {}
    for f in fields(Profile):
        if f.name not in stored:
            continue
        raw = stored[f.name]
        if f.name in _BOOLS:
            values[f.name] = raw == "1"
        elif f.name in _DATES:
            values[f.name] = date.fromisoformat(raw) if raw else None
        else:
            values[f.name] = raw
    return Profile(**values)


def save_profile(db: Database, profile: Profile) -> None:
    with db.transaction():
        for f in fields(Profile):
            value = getattr(profile, f.name)
            if f.name in _BOOLS:
                text = "1" if value else "0"
            elif f.name in _DATES:
                text = value.isoformat() if value else ""
            else:
                text = str(value)
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                [f.name, text],
            )
