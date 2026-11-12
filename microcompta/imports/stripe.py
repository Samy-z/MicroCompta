"""Payments read from Stripe, to fill the payment form. Nothing is ever written to Stripe.

Two guards are enforced here rather than trusted to callers: the verb is GET only, and the
host is api.stripe.com over HTTPS only. A secret key (sk_...) is refused: a restricted key
(rk_...) with read access is all this needs, and all it should be given.

Each payment is read from its balance transaction, which carries what Stripe kept and what
reached the Stripe balance, with the charge expanded for the amount the client paid.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from ..core import clock
from ..core.clients import Clients
from ..core.db import Database
from ..core.errors import MicroComptaError
from ..i18n import tr

log = logging.getLogger(__name__)

API = "https://api.stripe.com/v1"
HOST = "api.stripe.com"
# Currencies Stripe counts in whole units rather than in hundredths.
ZERO_DECIMAL = frozenset({"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf",
                          "ugx", "vnd", "vuv", "xaf", "xof", "xpf"})
PAYMENT_TYPES = frozenset({"charge", "payment"})
REFUND_TYPES = frozenset({"refund", "payment_refund", "payment_failure_refund"})
_RESTRICTED_KEY = re.compile(r"rk_(live|test)_[A-Za-z0-9]{10,}")
_ANY_KEY = re.compile(r"\b[rs]k_(live|test)_[A-Za-z0-9*]+")


class StripeError(MicroComptaError):
    """Stripe couldn't be read. The message is safe to show: it never holds the key."""


class StripeKeyError(StripeError):
    """The key is malformed, too powerful, or refused by Stripe."""


# -- the key ------------------------------------------------------------------
def check_key(key: str) -> str:
    key = (key or "").strip()
    if key.startswith(("sk_live_", "sk_test_")):
        raise StripeKeyError(tr(
            "This is a secret key, with full access to your Stripe account. Create a restricted "
            "key with read access only."
        ))
    if not _RESTRICTED_KEY.fullmatch(key):
        raise StripeKeyError(tr("A Stripe restricted key starts with rk_live_ or rk_test_."))
    return key


def load_key(path: Path) -> str | None:
    try:
        return check_key(path.read_text(encoding="utf-8"))
    except (OSError, StripeKeyError):
        return None


def save_key(path: Path, key: str) -> None:
    key = check_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")


def forget_key(path: Path) -> None:
    path.unlink(missing_ok=True)


def key_hint(key: str) -> str:
    """Enough to recognise a key, not enough to use it."""
    return f"{key[:8]}…{key[-4:]}"


# -- what is read -------------------------------------------------------------
@dataclass(frozen=True)
class StripePayment:
    id: str                       # the charge, kept as the entry's reference
    paid_on: date                 # the day the client paid
    amount: Decimal               # what the client paid, in their currency
    currency: str
    fee: Decimal                  # what Stripe kept
    fee_currency: str
    net: Decimal                  # what reached the Stripe balance
    net_currency: str
    provider_rate: Decimal | None  # units of the client's currency for 1 EUR, as Stripe converted
    description: str
    customer_name: str
    customer_email: str
    refunded: bool = False


@dataclass
class StripeReading:
    payments: list[StripePayment] = field(default_factory=list)
    refunds: int = 0


def _units(minor: Any, currency: str) -> Decimal:
    value = Decimal(int(minor or 0))
    return value if currency.lower() in ZERO_DECIMAL else value / 100


def _payment(item: dict[str, Any]) -> StripePayment:
    charge = item["source"]
    currency = str(charge.get("currency") or item.get("currency") or "eur").upper()
    settled = str(item.get("currency") or "eur").upper()
    customer = charge.get("customer") if isinstance(charge.get("customer"), dict) else {}
    billing = charge.get("billing_details") or {}
    rate = None
    exchange = item.get("exchange_rate")
    if exchange and settled == "EUR" and currency != "EUR":
        rate = (Decimal(1) / Decimal(str(exchange))).quantize(Decimal("0.000001"))
    return StripePayment(
        id=str(charge.get("id") or item["id"]),
        paid_on=datetime.fromtimestamp(int(charge.get("created") or item["created"])).date(),
        amount=_units(charge.get("amount", item.get("amount")), currency),
        currency=currency,
        fee=_units(item.get("fee"), settled),
        fee_currency=settled,
        net=_units(item.get("net"), settled),
        net_currency=settled,
        provider_rate=rate,
        description=str(charge.get("description") or "").strip(),
        customer_name=str(customer.get("name") or billing.get("name") or "").strip(),
        customer_email=str(customer.get("email") or billing.get("email") or charge.get("receipt_email") or "").strip(),
        refunded=bool(charge.get("refunded") or charge.get("amount_refunded")),
    )


def _message(response: Any) -> str:
    try:
        text = str((response.json().get("error") or {}).get("message") or "")
    except (ValueError, AttributeError):
        text = ""
    return _ANY_KEY.sub("[key]", text)[:200] or f"HTTP {response.status_code}"


# -- reading --------------------------------------------------------------------
class StripeSource:
    TIMEOUT = (15, 60)
    PAGE = 100

    def __init__(self, key: str, session: Any = None):
        self._key = check_key(key)
        self.session = session or requests.Session()

    @staticmethod
    def _guard(method: str, url: str) -> None:
        if method.upper() != "GET":
            raise StripeError(tr("Only reading from Stripe is allowed."))
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "").lower() != HOST:
            raise StripeError(tr("Only api.stripe.com over HTTPS is allowed."))

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{API}/{path}"
        self._guard("GET", url)
        try:
            response = self.session.request("GET", url, params=params, auth=(self._key, ""),
                                            timeout=self.TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            # The type only: the message of a connection error can carry the URL.
            raise StripeError(tr("No connection to Stripe ({error}).", error=type(exc).__name__)) from None
        if response.status_code in (401, 403):
            raise StripeKeyError(tr("Stripe refused the key: {reason}", reason=_message(response)))
        if response.status_code != 200:
            raise StripeError(tr("Stripe answered {status}: {reason}",
                                 status=response.status_code, reason=_message(response)))
        return response.json()

    def read(self, since: date) -> StripeReading:
        """Payments since that day, oldest first. Refunds are counted, not read."""
        reading = StripeReading()
        params: dict[str, Any] = {
            "limit": self.PAGE,
            "created[gte]": int(datetime.combine(since, datetime.min.time()).timestamp()),
            "expand[]": ["data.source", "data.source.customer"],
        }
        while True:
            page = self._get("balance_transactions", params)
            data = page.get("data") or []
            for item in data:
                kind = item.get("type")
                if kind in PAYMENT_TYPES and isinstance(item.get("source"), dict):
                    reading.payments.append(_payment(item))
                elif kind in REFUND_TYPES:
                    reading.refunds += 1
            if not page.get("has_more") or not data:
                break
            params = dict(params, starting_after=data[-1]["id"])
        reading.payments.sort(key=lambda p: (p.paid_on, p.id))
        return reading


# -- what is left to record ---------------------------------------------------------
class StripeInbox:
    """Payments not in the ledger yet and not set aside. The ledger is the memory: a payment
    recorded with its Stripe reference drops out, and comes back if that entry is reversed."""

    def __init__(self, db: Database, clients: Clients):
        self.db = db
        self.clients = clients

    def _recorded(self) -> set[str]:
        rows = self.db.rows(
            "SELECT provider_ref FROM ledger l WHERE kind = 'payment' AND provider_ref <> '' "
            "AND NOT EXISTS (SELECT 1 FROM ledger r WHERE r.reverses_seq = l.seq)"
        )
        return {r["provider_ref"] for r in rows}

    def _dismissed(self) -> set[str]:
        return {r["id"] for r in self.db.rows("SELECT id FROM stripe_dismissed")}

    def pending(self, reading: StripeReading) -> list[StripePayment]:
        skip = self._recorded() | self._dismissed()
        return [p for p in reading.payments if p.id not in skip]

    def dismiss(self, payment_id: str) -> None:
        if payment_id not in self._dismissed():
            self.db.execute("INSERT INTO stripe_dismissed (id, dismissed_at) VALUES (?, ?)",
                            [payment_id, clock.now()])

    def match_client(self, payment: StripePayment) -> int | None:
        """By name, then by email, then the only active client if there is just one."""
        active = self.clients.list(active_only=True)
        name = payment.customer_name.casefold()
        email = payment.customer_email.casefold()
        for client in active:
            if name and client["name"].casefold() == name:
                return client["id"]
        for client in active:
            if email and (client.get("email") or "").casefold() == email:
                return client["id"]
        return active[0]["id"] if len(active) == 1 else None


__all__ = ["StripeError", "StripeInbox", "StripeKeyError", "StripePayment", "StripeReading",
           "StripeSource", "check_key", "forget_key", "key_hint", "load_key", "save_key"]
