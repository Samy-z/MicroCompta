"""Hash chain over the insert-only tables.

DuckDB rejects CREATE TRIGGER, so the database cannot itself refuse an UPDATE. The
app's own write path has no way to change a record, and this chain means that a
change made any other way (a direct SQL session, a restored file) is detected the
next time the records are verified, rather than going unnoticed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

GENESIS = "0" * 64


def _default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unhashable value of type {type(value).__name__}")


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default,
                      ensure_ascii=False)


def chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prev_hash}\n{canonical(payload)}".encode("utf-8")).hexdigest()
