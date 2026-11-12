"""Reading payments from Stripe, against a fake Stripe: no network, fake keys, fake data."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal as D
from typing import Any

import pytest
import requests

from microcompta.imports.stripe import (
    StripeError, StripeKeyError, StripePayment, StripeReading, StripeSource, check_key, forget_key,
    key_hint, load_key, save_key,
)

KEY = "rk_test_FAKEKEY0123456789abcdef"
# Fakes in live mode, built in two parts so no line of this file looks like a real key to a
# secret scanner.
LIVE_RESTRICTED = "rk_" + "live_FAKEKEY0123456789abcdef"
LIVE_SECRET = "sk_" + "live_FAKEKEY0123456789abcdef"


def _ts(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time().replace(hour=12)).timestamp())


def charge_txn(txn: str, charge: str, day: date, *, amount: int, currency: str, settled_amount: int,
               fee: int, net: int, settled: str = "eur", exchange_rate: float | None = None,
               name: str = "Acme Annotation LLC", email: str = "billing@example.invalid",
               description: str = "Annotation, semaine 44", refunded: bool = False,
               kind: str = "charge") -> dict[str, Any]:
    return {
        "id": txn, "object": "balance_transaction", "type": kind, "created": _ts(day),
        "currency": settled, "amount": settled_amount, "fee": fee, "net": net, "exchange_rate": exchange_rate,
        "source": {
            "id": charge, "object": "charge", "amount": amount, "currency": currency, "created": _ts(day),
            "description": description, "billing_details": {"name": name, "email": email},
            "customer": {"id": "cus_fake", "name": name, "email": email},
            "refunded": refunded, "amount_refunded": amount if refunded else 0,
        },
    }


USD = charge_txn("txn_usd", "ch_usd", date(2026, 10, 30), amount=102000, currency="usd",
                 settled_amount=94244, fee=2761, net=91483, exchange_rate=0.923972)
EUR = charge_txn("txn_eur", "ch_eur", date(2026, 10, 2), amount=50000, currency="eur",
                 settled_amount=50000, fee=165, net=49835)
JPY = charge_txn("txn_jpy", "ch_jpy", date(2026, 10, 15), amount=15000, currency="jpy",
                 settled_amount=9000, fee=300, net=8700, exchange_rate=0.006)
REFUND = {"id": "txn_ref", "type": "refund", "created": _ts(date(2026, 10, 20)), "currency": "eur",
          "amount": -5000, "fee": 0, "net": -5000, "source": "re_fake"}
PAYOUT = {"id": "txn_po", "type": "payout", "created": _ts(date(2026, 10, 21)), "currency": "eur",
          "amount": -90000, "fee": 0, "net": -90000, "source": "po_fake"}


class FakeResponse:
    def __init__(self, status: int, payload: Any):
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, *responses: Any):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append((method, url, kwargs))
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def page(*items: dict[str, Any], more: bool = False) -> FakeResponse:
    return FakeResponse(200, {"object": "list", "data": list(items), "has_more": more})


# -- the key ------------------------------------------------------------------
@pytest.mark.parametrize("key", [KEY, LIVE_RESTRICTED, f"  {KEY}\n"])
def test_a_restricted_key_is_accepted(key):
    assert check_key(key) == key.strip()


def test_a_secret_key_is_refused_for_having_full_access():
    with pytest.raises(StripeKeyError, match="secret key"):
        check_key(LIVE_SECRET)


@pytest.mark.parametrize("key", ["", "pk_live_FAKEKEY0123456789", "rk_live_short", "hello"])
def test_anything_else_is_refused(key):
    with pytest.raises(StripeKeyError):
        check_key(key)


def test_the_key_is_saved_read_and_forgotten(tmp_path):
    path = tmp_path / "secrets" / "stripe_key.txt"
    assert load_key(path) is None
    save_key(path, KEY)
    assert load_key(path) == KEY
    forget_key(path)
    assert not path.exists() and load_key(path) is None


def test_a_refused_key_is_never_written(tmp_path):
    path = tmp_path / "stripe_key.txt"
    with pytest.raises(StripeKeyError):
        save_key(path, LIVE_SECRET)
    assert not path.exists()


def test_the_hint_shows_too_little_to_use_the_key():
    hint = key_hint(KEY)
    assert hint.startswith("rk_test_") and hint.endswith(KEY[-4:])
    assert len(hint.replace("…", "")) < 16


def test_the_log_never_holds_a_stripe_key(caplog):
    from microcompta.__main__ import _Redact
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "key %s and %s", (KEY, LIVE_SECRET), None)
    assert _Redact().filter(record)
    assert "FAKEKEY" not in record.getMessage()


# -- the guards ---------------------------------------------------------------
@pytest.mark.parametrize("method, url", [
    ("POST", "https://api.stripe.com/v1/balance_transactions"),
    ("DELETE", "https://api.stripe.com/v1/customers/cus_fake"),
    ("GET", "http://api.stripe.com/v1/balance_transactions"),
    ("GET", "https://api.stripe.com.evil.example/v1/balance_transactions"),
    ("GET", "https://www.googleapis.com/drive/v3/files"),
])
def test_only_reading_from_api_stripe_com_over_https_is_allowed(method, url):
    with pytest.raises(StripeError):
        StripeSource._guard(method, url)


def test_a_request_is_a_get_with_the_key_as_basic_auth_and_no_redirects():
    session = FakeSession(page(USD))
    StripeSource(KEY, session).read(date(2026, 10, 1))
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "https://api.stripe.com/v1/balance_transactions")
    assert kwargs["auth"] == (KEY, "")
    assert kwargs["allow_redirects"] is False and kwargs["timeout"]
    assert kwargs["params"]["created[gte]"] == int(datetime(2026, 10, 1).timestamp())
    assert "data.source" in kwargs["params"]["expand[]"]


# -- reading ------------------------------------------------------------------
def test_a_usd_payment_settled_in_euros():
    reading = StripeSource(KEY, FakeSession(page(USD))).read(date(2026, 10, 1))
    payment = reading.payments[0]
    assert payment == StripePayment(
        id="ch_usd", paid_on=date(2026, 10, 30), amount=D("1020"), currency="USD",
        fee=D("27.61"), fee_currency="EUR", net=D("914.83"), net_currency="EUR",
        provider_rate=(D(1) / D("0.923972")).quantize(D("0.000001")),
        description="Annotation, semaine 44", customer_name="Acme Annotation LLC",
        customer_email="billing@example.invalid",
    )


def test_a_euro_payment_has_no_stripe_rate():
    payment = StripeSource(KEY, FakeSession(page(EUR))).read(date(2026, 10, 1)).payments[0]
    assert (payment.amount, payment.currency, payment.provider_rate) == (D("500"), "EUR", None)


def test_a_zero_decimal_currency_is_counted_in_whole_units():
    payment = StripeSource(KEY, FakeSession(page(JPY))).read(date(2026, 10, 1)).payments[0]
    assert (payment.amount, payment.currency, payment.net) == (D("15000"), "JPY", D("87"))


def test_refunds_are_counted_payouts_ignored_and_payments_come_oldest_first():
    reading = StripeSource(KEY, FakeSession(page(USD, REFUND, PAYOUT, EUR, JPY))).read(date(2026, 10, 1))
    assert [p.id for p in reading.payments] == ["ch_eur", "ch_jpy", "ch_usd"]
    assert reading.refunds == 1


def test_a_refunded_charge_is_flagged():
    refunded = charge_txn("txn_r", "ch_r", date(2026, 10, 5), amount=1000, currency="eur",
                          settled_amount=1000, fee=10, net=990, refunded=True)
    assert StripeSource(KEY, FakeSession(page(refunded))).read(date(2026, 10, 1)).payments[0].refunded


def test_every_page_is_read():
    session = FakeSession(page(USD, more=True), page(EUR))
    reading = StripeSource(KEY, session).read(date(2026, 10, 1))
    assert len(reading.payments) == 2
    assert session.calls[1][2]["params"]["starting_after"] == "txn_usd"


def test_a_refused_key_says_so_without_repeating_it():
    session = FakeSession(FakeResponse(401, {"error": {"message": f"Invalid API Key provided: {KEY}"}}))
    with pytest.raises(StripeKeyError) as caught:
        StripeSource(KEY, session).read(date(2026, 10, 1))
    assert "FAKEKEY" not in str(caught.value)
    assert "Invalid API Key" in str(caught.value)


def test_a_missing_permission_is_shown():
    session = FakeSession(FakeResponse(403, {"error": {"message": "The provided key does not have the required permissions."}}))
    with pytest.raises(StripeKeyError, match="required permissions"):
        StripeSource(KEY, session).read(date(2026, 10, 1))


def test_no_connection_names_the_error_type_only():
    session = FakeSession(requests.ConnectionError("https://api.stripe.com/v1/... secret details"))
    with pytest.raises(StripeError) as caught:
        StripeSource(KEY, session).read(date(2026, 10, 1))
    assert "ConnectionError" in str(caught.value) and "api.stripe.com" not in str(caught.value)


def test_a_server_error_is_reported():
    with pytest.raises(StripeError, match="500"):
        StripeSource(KEY, FakeSession(FakeResponse(500, ValueError("not json")))).read(date(2026, 10, 1))


def test_a_secret_key_cannot_even_build_a_source():
    with pytest.raises(StripeKeyError):
        StripeSource("sk_test_FAKEKEY0123456789abcdef", FakeSession())


# -- what is left to record ---------------------------------------------------------
def _reading(*items: dict[str, Any]) -> StripeReading:
    return StripeSource(KEY, FakeSession(page(*items))).read(date(2026, 1, 1))


def _record(book: Any, client_id: int, ref: str) -> int:
    return book.ledger.record_payment(
        received_on=date(2026, 10, 30), client_id=client_id, description="Annotation", amount_gross="1020",
        fx_rate="1.0823", net_credited="914.83", payment_method="Stripe", fee_amount="27.61",
        fee_currency="EUR", provider_ref=ref,
    )


@pytest.fixture
def acme(book):
    return book.clients.add(name="Acme Annotation LLC", currency="USD", email="billing@example.invalid")


def test_a_recorded_payment_drops_out_and_comes_back_if_reversed(book, acme):
    reading = _reading(USD, EUR)
    assert [p.id for p in book.stripe.pending(reading)] == ["ch_eur", "ch_usd"]
    seq = _record(book, acme, "ch_usd")
    assert [p.id for p in book.stripe.pending(reading)] == ["ch_eur"]
    book.ledger.reverse(seq, "Wrong rate")
    assert [p.id for p in book.stripe.pending(reading)] == ["ch_eur", "ch_usd"]


def test_an_ignored_payment_stays_ignored(book, acme):
    reading = _reading(USD, EUR)
    book.stripe.dismiss("ch_eur")
    book.stripe.dismiss("ch_eur")          # twice is fine
    assert [p.id for p in book.stripe.pending(reading)] == ["ch_usd"]


def test_the_client_is_found_by_name_then_email_then_alone(book, acme):
    other = book.clients.add(name="Beta Studio", currency="EUR", email="pay@beta.example.invalid")
    by_name = _reading(charge_txn("t1", "c1", date(2026, 10, 1), amount=100, currency="usd", settled_amount=92,
                                  fee=1, net=91, name="ACME ANNOTATION LLC", email=""))
    assert book.stripe.match_client(by_name.payments[0]) == acme
    by_email = _reading(charge_txn("t2", "c2", date(2026, 10, 1), amount=100, currency="eur", settled_amount=100,
                                   fee=1, net=99, name="", email="PAY@beta.example.invalid"))
    assert book.stripe.match_client(by_email.payments[0]) == other
    nobody = _reading(charge_txn("t3", "c3", date(2026, 10, 1), amount=100, currency="eur", settled_amount=100,
                                 fee=1, net=99, name="Someone Else", email="x@example.invalid"))
    assert book.stripe.match_client(nobody.payments[0]) is None
    book.clients.update(other, active=False)
    assert book.stripe.match_client(nobody.payments[0]) == acme   # the only active client
