"""The one place the app asks what day it is, so tests can pin it."""

from __future__ import annotations

from datetime import date, datetime, timezone


def today() -> date:
    return date.today()


def now() -> datetime:
    """Naive UTC, to the second. Stored timestamps are always in this form."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
