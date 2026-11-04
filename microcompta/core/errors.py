"""Errors the UI turns into plain messages."""

from __future__ import annotations

from datetime import date


class MicroComptaError(Exception):
    """Base class: anything here is a message for the user, not a crash."""


class ValidationError(MicroComptaError):
    """Input that cannot be recorded as given."""


class ImmutableError(MicroComptaError):
    """An attempt to change a record that can only be corrected by a new one."""


class IssueBlocked(MicroComptaError):
    """A final invoice is missing something the law requires."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


class MissingFigure(MicroComptaError):
    """No effective-dated value covers this date."""

    def __init__(self, key: str, on: date):
        super().__init__(
            f"No value for '{key}' on {on.isoformat()}. "
            "Add one under Settings > Figures."
        )
        self.key = key
        self.on = on
