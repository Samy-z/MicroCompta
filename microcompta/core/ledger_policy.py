"""How a recorded payment counts as turnover.

Both choices are open questions, and each is a setting because records cannot
change: every entry stores its gross, rate, fee and net separately, so the count can
be recomputed either way without touching an entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from .money import round_money

UNCONFIRMED = "unconfirmed, URSSAF to answer"

BASIS_LABELS = {
    "gross": "Gross, before provider fees",
    "net_of_fees": "Net of provider fees",
}
FX_LABELS = {
    "entry_rate": "Rate recorded on each entry (ECB reference by default)",
    "provider_effective": "Rate the provider actually applied, derived from net credited",
}
# The official text is about commissions and fees in general, not Stripe or PayPal.
FEE_POINTER = (
    "Service-public F23257 says no commission or fee is deducted from turnover "
    "(« aucune charge ne doit être déduite du chiffre d'affaires (commissions, frais etc.) »), "
    "which is why gross is the default."
)


@dataclass(frozen=True)
class TurnoverPolicy:
    basis: str = "gross"
    fx: str = "entry_rate"

    def describe(self) -> str:
        return f"{BASIS_LABELS.get(self.basis, self.basis)} · {FX_LABELS.get(self.fx, self.fx)}"


def effective_eur(entry: Mapping[str, Any], policy: TurnoverPolicy) -> tuple[Decimal, Decimal]:
    """(gross, fee) in euros for this entry under the policy's rate choice."""
    gross_eur = Decimal(entry["eur_gross"])
    fee_eur = Decimal(entry["fee_eur"])
    if policy.fx != "provider_effective":
        return gross_eur, fee_eur
    if entry["net_currency"] != "EUR" or entry["currency"] == "EUR":
        return gross_eur, fee_eur  # no euro amount from the provider to derive a rate from

    net = Decimal(entry["net_credited"])
    if entry["fee_currency"] == "EUR":
        fee = Decimal(entry["fee_amount"])
    else:
        net_in_currency = Decimal(entry["amount_gross"]) - Decimal(entry["fee_amount"])
        if net_in_currency == 0:
            return gross_eur, fee_eur
        fee = round_money(Decimal(entry["fee_amount"]) * net / net_in_currency)
    return net + fee, fee


def counted_eur(entry: Mapping[str, Any], policy: TurnoverPolicy) -> Decimal:
    """What this entry adds to turnover, in euros."""
    gross, fee = effective_eur(entry, policy)
    return gross - fee if policy.basis == "net_of_fees" else gross
