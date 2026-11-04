"""Decimal helpers. Money never passes through a float."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ..i18n import fmt_money, tr  # noqa: F401 - fmt_money is re-exported for core and ui
from .errors import ValidationError

CENT = Decimal("0.01")
EURO = Decimal("1")
ZERO = Decimal("0.00")
NBSP = " "

_SYMBOLS = {"EUR": "€", "USD": "$"}


def to_decimal(value: Any, field: str | None = None) -> Decimal:
    """Parse what a person types: 1234.56, 1234,56, 1,234.56, 1 234,56."""
    field = field or tr("Amount")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        raise ValidationError(tr("{field}: not a number", field=field))
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        text = str(value if value is not None else "").strip()
        for space in (" ", NBSP, " "):
            text = text.replace(space, "")
        if not text:
            raise ValidationError(tr("{field}: empty", field=field))
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValidationError(
                tr("{field}: '{value}' is not a number", field=field, value=value)
            ) from exc
    if not result.is_finite():
        raise ValidationError(tr("{field}: not a finite number", field=field))
    return result


def round_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_euro(value: Decimal) -> Decimal:
    return Decimal(value).quantize(EURO, rounding=ROUND_HALF_UP)


def fmt_amount_fr(value: Decimal, currency: str | None = None) -> str:
    """French document form: 1 234,56 USD."""
    d = Decimal(value)
    body = f"{abs(d):,.2f}".replace(",", NBSP).replace(".", ",")
    sign = "-" if d < 0 else ""
    text = f"{sign}{body}"
    if currency:
        text += NBSP + _SYMBOLS.get(currency, currency) if currency == "EUR" else NBSP + currency
    return text


def fmt_rate_fr(value: Decimal) -> str:
    """An exchange rate with trailing zeros trimmed: 1,0823."""
    text = f"{Decimal(value):.6f}".rstrip("0")
    if text.endswith("."):
        text += "00"
    elif len(text.partition(".")[2]) < 2:
        text += "0"
    return text.replace(".", ",")


def fmt_quantity_fr(value: Decimal) -> str:
    text = f"{Decimal(value):.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def fmt_date_fr(value: date | str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d/%m/%Y")
