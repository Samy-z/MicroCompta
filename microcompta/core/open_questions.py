"""What the official sources read so far don't settle, and who can answer it.

Shown in the app so an assumption can't quietly pass for a rule. Checked 2026-11-04.
"""

from __future__ import annotations

OPEN_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": "USD rate for turnover",
        "who": "URSSAF",
        "status": "unconfirmed, URSSAF to answer",
        "detail": "No official rule found for the rate on the date received. The ECB rule on "
                  "economie.gouv.fr is about the rate printed on an invoice.",
    },
    {
        "topic": "Turnover before or after provider fees",
        "who": "URSSAF",
        "status": "unconfirmed, URSSAF to answer",
        "detail": "F23257 says no commission or fee is deducted from turnover, so the default "
                  "is gross. It doesn't name Stripe or PayPal.",
    },
    {
        "topic": "Non-EU business client in the VAT franchise",
        "who": "SIE",
        "status": "probably excluded; SIE to confirm",
        "detail": "The reference turnover is what is taxed in France (BOFiP s.180). A service to "
                  "a non-EU business client probably isn't, which is an inference.",
    },
    {
        "topic": "Invoice mention for a non-EU client",
        "who": "SIE",
        "status": "open",
        "detail": "Whether anything is needed beyond the art. 293 B mention.",
    },
    {
        "topic": "Versement libératoire with no French reference income",
        "who": "SIE",
        "status": "open",
        "detail": "The impots.gouv.fr page doesn't address people with no French RFR.",
    },
    {
        "topic": "ACRE and the versement libératoire part",
        "who": "URSSAF",
        "status": "assumption",
        "detail": "The app reduces only the contribution part, not the tax part, when both apply.",
    },
    {
        "topic": "Formation professionnelle (CFP)",
        "who": "URSSAF",
        "status": "open",
        "detail": "F36232 lists it among what the flat rate covers; some secondary sources add "
                  "0.1-0.2%. The rates in Figures assume nothing extra.",
    },
    {
        "topic": "A prorated first year as a year over the ceiling",
        "who": "URSSAF or SIE",
        "status": "open",
        "detail": "F23267 doesn't say whether it counts towards the two consecutive years.",
    },
]
