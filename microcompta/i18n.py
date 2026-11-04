"""Translations and language-aware formats. No Qt here, because core uses it too.

English is the source language: the text in the code is the key, and it is also what
shows if a translation is missing. Each other language is one file,
``data/i18n/<code>.json``. Adding a file is all it takes to offer another language in
Settings. ``tests/test_i18n.py`` fails if a string in the code has no translation.

Stored values stay as stable English keys (a payment method, a status). They are
translated when shown, so changing language can't change a record or break a hash chain.

Invoices and the livre des recettes are always in French, whatever the app's language:
they are French legal records. See core/invoice_pdf.py and core/exports.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from .config import PACKAGE_DATA_DIR

SOURCE_LANGUAGE = "en"
DEFAULT_LANGUAGE = "fr"

_CATALOG_DIR = PACKAGE_DATA_DIR / "i18n"
NBSP = " "

_current = DEFAULT_LANGUAGE


def N_(text: str) -> str:
    """Mark text for translation where it is defined, for ``tr()`` to translate when shown."""
    return text


MONTHS = (N_("Jan"), N_("Feb"), N_("Mar"), N_("Apr"), N_("May"), N_("Jun"), N_("Jul"),
          N_("Aug"), N_("Sep"), N_("Oct"), N_("Nov"), N_("Dec"))


def _french_typography(text: str) -> str:
    """French keeps a space before : ; ? ! and %, which must not start a wrapped line."""
    for mark in (" :", " ;", " ?", " !", " %", " »"):
        text = text.replace(mark, NBSP + mark[1:])
    return text.replace("« ", "«" + NBSP)


@lru_cache(maxsize=None)
def _messages(language: str) -> dict[str, str]:
    path = _CATALOG_DIR / f"{language}.json"
    if not path.is_file():
        return {}
    messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
    if language == "fr":
        return {key: _french_typography(value) for key, value in messages.items()}
    return messages


def available_languages() -> dict[str, str]:
    """Code to the language's own name, for the Settings list."""
    found = {SOURCE_LANGUAGE: "English"}
    for path in sorted(_CATALOG_DIR.glob("*.json")):
        found[path.stem] = json.loads(path.read_text(encoding="utf-8"))["language_name"]
    return found


def set_language(code: str) -> None:
    global _current
    _current = code if code in available_languages() else SOURCE_LANGUAGE


def current_language() -> str:
    return _current


def translate(text: str, language: str) -> str:
    """One string in one language, whatever the current one is."""
    if language == SOURCE_LANGUAGE:
        return text
    return _messages(language).get(text, text)


def tr(text: str, **values: Any) -> str:
    result = translate(text, _current)
    return result.format(**values) if values else result


def month_name(month: int) -> str:
    return tr(MONTHS[month - 1])


# -- numbers and dates, in the current language ---------------------------------
_FRENCH_STYLE = ("fr",)


def _is_french_style() -> bool:
    return _current in _FRENCH_STYLE


def fmt_number(value: Any, decimals: int = 2) -> str:
    """1,234.56 or 1 234,56"""
    text = f"{Decimal(value):,.{decimals}f}"
    if _is_french_style():
        return text.replace(",", NBSP).replace(".", ",")
    return text


_SYMBOLS = {"EUR": "€", "USD": "$"}


def fmt_money(value: Any, currency: str = "EUR", decimals: int = 2) -> str:
    """€1,234.56 and -$12.00, or 1 234,56 € and -12,00 $"""
    if value is None:
        return "—"
    amount = Decimal(value)
    sign = "-" if amount < 0 else ""
    body = fmt_number(abs(amount), decimals)
    symbol = _SYMBOLS.get(currency, currency)
    if _is_french_style():
        return f"{sign}{body}{NBSP}{symbol}"
    separator = "" if currency in _SYMBOLS else " "
    return f"{sign}{symbol}{separator}{body}"


def fmt_percent(fraction: Any, decimals: int = 1) -> str:
    """0.256 as 25.6% or 25,6 %"""
    text = fmt_number(Decimal(fraction) * 100, decimals)
    return f"{text}{NBSP}%" if _is_french_style() else f"{text}%"


def fmt_rate(value: Any) -> str:
    """An exchange rate with trailing zeros trimmed: 1.0823 or 1,0823"""
    text = f"{Decimal(value):.6f}".rstrip("0")
    text = text + "0" if text.endswith(".") else text
    return text.replace(".", ",") if _is_french_style() else text


def fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d/%m/%Y") if _is_french_style() else value.strftime("%Y-%m-%d")


def fmt_datetime(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if _is_french_style() else value.strftime("%Y-%m-%d %H:%M")


def date_input_format() -> str:
    """The display format for a date field."""
    return "dd/MM/yyyy" if _is_french_style() else "yyyy-MM-dd"
