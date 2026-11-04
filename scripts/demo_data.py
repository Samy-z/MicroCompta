"""Fake records for the smoke tests and screenshots. Nothing here is real.

The identity, client and references are invented, and the amounts are round on purpose.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

FAKE_TODAY = date(2026, 11, 4)
FAKE_SIREN = "123456782"  # passes the check digit; fake


def populate(book: Any, *, with_siren: bool = True) -> dict[str, Any]:
    from microcompta.core.profile import Profile

    profile = Profile(
        legal_name="Camille Exemple",
        address="12 rue de l'Exemple\n00000 Exempleville",
        siren=FAKE_SIREN if with_siren else "",
        email="camille@example.invalid",
        start_date=date(2026, 7, 6),
        activity="bnc",
        declaration_frequency="monthly",
        acre_enabled=True,
    )
    book.save_profile(profile)

    client = book.clients.add(
        name="Acme Annotation LLC",
        address="1 Example Street\nSpringfield, EX 00000",
        country="United States",
        tax_id="00-0000000",
        currency="USD",
        taxed_in_france=False,
        vat_note="Non-EU business client",
    )

    # Weekly payments, 6 July to 30 October.
    amounts = [720, 840, 900, 780, 960, 1020, 840, 1080, 960, 900, 1140, 1020, 1200, 1080, 960, 1140, 1020]
    rates = ["1.0842", "1.0817", "1.0795", "1.0861", "1.0834", "1.0779", "1.0806", "1.0823", "1.0851"]
    day = date(2026, 7, 10)
    first_seq = None
    for i, gross in enumerate(amounts):
        rate = rates[i % len(rates)]
        fee = round(gross * 0.029 + 0.30, 2)
        net = round((gross - fee) / float(rate) * 0.995, 2)
        seq = book.ledger.record_payment(
            received_on=day, client_id=client, description=f"Annotation work, week {day.isocalendar()[1]}",
            amount_gross=str(gross), fx_rate=rate, fee_amount=str(fee), fee_currency="USD",
            net_credited=str(net), payment_method="Stripe", provider_ref=f"po_fake_{1000 + i}",
        )
        first_seq = first_seq or seq
        day += timedelta(days=7)

    # A mistake and its correction, so the ledger shows how it works.
    wrong = book.ledger.record_payment(
        received_on=date(2026, 9, 18), client_id=client, description="Annotation work, recorded twice",
        amount_gross="1020", fx_rate="1.0779", fee_amount="29.88", net_credited="914.08",
        payment_method="Stripe", provider_ref="po_fake_dup",
    )
    book.ledger.reverse(wrong, "Recorded twice")

    # July and August issued; September still a draft.
    ids = {}
    if with_siren:
        for month, issued, rate in ((7, date(2026, 8, 3), "1.0831"), (8, date(2026, 9, 1), "1.0806")):
            invoice_id = book.invoices.create_monthly_draft(client, 2026, month)
            book.invoices.issue(invoice_id, issued, fx_rate=rate, fx_rate_date=issued)
            ids[month] = invoice_id
    ids[9] = book.invoices.create_monthly_draft(client, 2026, 9)

    book.deadlines.set_done("acre:request")
    return {"client": client, "invoices": ids, "first_seq": first_seq}
