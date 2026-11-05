"""What the official sources read so far don't settle, and who can answer it.

Shown in the app so an assumption can't quietly pass for a rule. Checked 2026-11-04.
"""

from __future__ import annotations

from ..i18n import N_

OPEN_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": N_("USD rate for turnover"),
        "who": "URSSAF",
        "status": N_("unconfirmed, URSSAF to answer"),
        "detail": N_("No official rule found for the rate on the date received. The ECB rule on "
                     "economie.gouv.fr is about the rate printed on an invoice."),
    },
    {
        "topic": N_("Turnover before or after provider fees"),
        "who": "URSSAF",
        "status": N_("unconfirmed, URSSAF to answer"),
        "detail": N_("F23257 says no commission or fee is deducted from turnover, so the default "
                     "is gross. It doesn't name Stripe or PayPal."),
    },
    {
        "topic": N_("Non-EU business client in the VAT franchise"),
        "who": "SIE",
        "status": N_("probably excluded; SIE to confirm"),
        "detail": N_("The reference turnover is what is taxed in France (BOFiP s.180). A service to "
                     "a non-EU business client probably isn't, which is an inference."),
    },
    {
        "topic": N_("Invoice mention for a non-EU client"),
        "who": "SIE",
        "status": N_("open"),
        "detail": N_("Whether anything is needed beyond the art. 293 B mention."),
    },
    {
        "topic": N_("Versement libératoire with no French reference income"),
        "who": "SIE",
        "status": N_("open"),
        "detail": N_("The impots.gouv.fr page doesn't address people with no French RFR."),
    },
    {
        "topic": N_("ACRE and the versement libératoire part"),
        "who": "URSSAF",
        "status": N_("assumption"),
        "detail": N_("The app reduces only the contribution part, not the tax part, when both apply."),
    },
    {
        "topic": N_("Formation professionnelle (CFP)"),
        "who": "URSSAF",
        "status": N_("open"),
        "detail": N_("F36232 lists it among what the flat rate covers; some secondary sources add "
                     "0.1-0.2%. The rates in Figures assume nothing extra."),
    },
    {
        "topic": N_("A subscription bought from a foreign business"),
        "who": "SIE",
        "status": N_("open"),
        "detail": N_("impots.gouv.fr says that buying a service from a business in another EU state "
                     "takes an EU VAT number and self-assessing the VAT, whatever the amount. It "
                     "doesn't cover a non-EU supplier, or a supplier that already charges French VAT."),
    },
    {
        "topic": N_("Deadline to opt for a real regime (BNC)"),
        "who": "SIE",
        "status": N_("sources differ; SIE to confirm"),
        "detail": N_("BOFiP s.140 and the DGFiP leaflet of March 2026 allow it until the 2035 return "
                     "for the year concerned is due, the following spring. F23267 says the year before."),
    },
    {
        "topic": N_("A prorated first year as a year over the ceiling"),
        "who": N_("URSSAF or SIE"),
        "status": N_("open"),
        "detail": N_("F23267 doesn't say whether it counts towards the two consecutive years."),
    },
]
