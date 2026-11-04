"""Effective-dated figures: every limit and rate lives here, not in code."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config import FIGURES_SEED
from ..i18n import tr
from . import clock
from .db import Database
from .errors import MissingFigure, ValidationError
from .money import to_decimal

_MD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class Figures:
    def __init__(self, db: Database, seed_path: Path = FIGURES_SEED):
        self.db = db
        self.seed_path = seed_path
        self.seed()

    def seed(self) -> None:
        """Insert seed rows that are missing. Never overwrites an edit."""
        rows = json.loads(self.seed_path.read_text(encoding="utf-8"))["figures"]
        with self.db.transaction():
            for r in rows:
                exists = self.db.scalar(
                    "SELECT count(*) FROM figures WHERE key = ? AND effective_from = ?",
                    [r["key"], r["effective_from"]],
                )
                if not exists:
                    self.db.execute(
                        "INSERT INTO figures (key, effective_from, value, unit, label, source, note) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [r["key"], r["effective_from"], r["value"], r["unit"],
                         r["label"], r["source"], r["note"]],
                    )

    # -- reads --------------------------------------------------------------
    def _row(self, key: str, on: date) -> dict[str, Any]:
        row = self.db.row(
            "SELECT * FROM figures WHERE key = ? AND effective_from <= ? "
            "ORDER BY effective_from DESC LIMIT 1",
            [key, on],
        )
        if row is None:
            raise MissingFigure(key, on)
        return row

    def value(self, key: str, on: date) -> Decimal:
        return Decimal(self._row(key, on)["value"])

    def date_value(self, key: str, on: date) -> date:
        return date.fromisoformat(self._row(key, on)["value"])

    def month_day(self, key: str, year: int) -> date:
        """A yearly date such as 12-15, as it stood in that year."""
        month, day = self._row(key, date(year, 12, 31))["value"].split("-")
        return date(year, int(month), int(day))

    def rows(self) -> list[dict[str, Any]]:
        return self.db.rows("SELECT * FROM figures ORDER BY key, effective_from")

    # -- writes -------------------------------------------------------------
    def upsert(self, key: str, effective_from: date, value: str, source: str = "",
               note: str = "") -> None:
        known = self.db.row(
            "SELECT unit, label FROM figures WHERE key = ? ORDER BY effective_from DESC LIMIT 1",
            [key],
        )
        if known is None:
            raise ValidationError(tr("Unknown figure '{key}'.", key=key))
        value = self._validated(known["unit"], value)
        self.db.execute(
            "INSERT INTO figures (key, effective_from, value, unit, label, source, note, edited_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (key, effective_from) DO UPDATE SET value = excluded.value, "
            "source = excluded.source, note = excluded.note, edited_at = excluded.edited_at",
            [key, effective_from, value, known["unit"], known["label"], source, note, clock.now()],
        )

    @staticmethod
    def _validated(unit: str, value: str) -> str:
        text = str(value).strip()
        if unit in ("eur", "rate", "days"):
            number = to_decimal(text, tr("Value"))
            if number < 0:
                raise ValidationError(tr("A figure cannot be negative."))
            return format(number, "f")
        if unit == "date":
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError as exc:
                raise ValidationError(tr("Use a date in the form YYYY-MM-DD.")) from exc
        if unit == "md":
            if not _MD_RE.match(text):
                raise ValidationError(tr("Use a month and day in the form MM-DD."))
            return text
        raise ValidationError(tr("Unknown unit '{unit}'.", unit=unit))
