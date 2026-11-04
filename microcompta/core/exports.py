"""Exports of the records, in French. Every export is a recorded document, so it goes
through Documents and is queued for Drive like an invoice."""

from __future__ import annotations

import csv
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..i18n import translate
from . import clock
from .ledger_policy import TurnoverPolicy, counted_eur
from .money import ZERO, fmt_amount_fr, fmt_date_fr, fmt_rate_fr

BASIS_FR = {"gross": "brut, avant frais du prestataire", "net_of_fees": "net des frais du prestataire"}
FX_FR = {
    "entry_rate": "taux inscrit sur chaque écriture",
    "provider_effective": "taux effectif du prestataire, déduit du net crédité",
}
TO_CONFIRM_FR = "à confirmer auprès de l'URSSAF"

LEDGER_HEADER = [
    "N° écriture", "Type", "Date d'encaissement", "Client (origine)", "Objet", "Devise",
    "Montant brut", "Taux (devise pour 1 EUR)", "Source du taux", "Brut EUR", "Frais",
    "Devise des frais", "Frais EUR", "Net crédité", "Devise du net", "Mode de règlement",
    "Référence prestataire", "Facture liée", "Écriture annulée", "Motif",
    "Retenu pour le chiffre d'affaires (EUR)",
]


def _csv_amount(value: Any) -> str:
    return f"{Decimal(value):.2f}".replace(".", ",")


def _csv_rate(value: Any) -> str:
    return f"{Decimal(value):.6f}".replace(".", ",")


class Exports:
    def __init__(self, book: Any):
        self.book = book

    def _temp(self, suffix: str) -> Path:
        fd, name = tempfile.mkstemp(suffix=suffix, dir=self.book.documents.tmp_dir())
        os.close(fd)
        return Path(name)

    @staticmethod
    def _stamp() -> str:
        return clock.now().strftime("%Y%m%d-%H%M%S")

    # -- ledger CSV ---------------------------------------------------------
    def _ledger_rows(self, year: int | None, policy: TurnoverPolicy) -> list[list[str]]:
        ledger = self.book.ledger
        years = [year] if year is not None else sorted(ledger.years())
        out: list[list[str]] = []
        for y in years:
            for e in ledger.entries(y):
                out.append([
                    str(e["seq"]),
                    "Paiement" if e["kind"] == "payment" else "Annulation",
                    e["received_on"].isoformat(),
                    e["client_name"],
                    e["description"],
                    e["currency"],
                    _csv_amount(e["amount_gross"]),
                    _csv_rate(e["fx_rate"]),
                    translate(e["fx_source"], "fr"),
                    _csv_amount(e["eur_gross"]),
                    _csv_amount(e["fee_amount"]),
                    e["fee_currency"],
                    _csv_amount(e["fee_eur"]),
                    _csv_amount(e["net_credited"]),
                    e["net_currency"],
                    translate(e["payment_method"], "fr"),
                    e["provider_ref"] or "",
                    e["linked_invoice"],
                    "" if e["reverses_seq"] is None else str(e["reverses_seq"]),
                    e["reason"] or "",
                    _csv_amount(counted_eur(e, policy)),
                ])
            for q in ledger.quarter_totals(y, policy):
                out.append(self._total_row(f"Total {q['label']}", q))
            yearly = {
                "eur_gross": sum((q["eur_gross"] for q in ledger.quarter_totals(y, policy)), ZERO),
                "fee_eur": sum((q["fee_eur"] for q in ledger.quarter_totals(y, policy)), ZERO),
                "counted": sum((q["counted"] for q in ledger.quarter_totals(y, policy)), ZERO),
            }
            out.append(self._total_row(f"Total {y}", yearly))
        return out

    @staticmethod
    def _total_row(label: str, totals: dict[str, Any]) -> list[str]:
        row = [""] * len(LEDGER_HEADER)
        row[1] = label
        row[9] = _csv_amount(totals["eur_gross"])
        row[12] = _csv_amount(totals["fee_eur"])
        row[20] = _csv_amount(totals["counted"])
        return row

    def ledger_csv(self, year: int | None = None) -> int:
        policy = self.book.profile().policy
        tmp = self._temp(".csv")
        try:
            # Semicolons and decimal commas, and a BOM: what French Excel opens cleanly.
            with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(LEDGER_HEADER)
                writer.writerows(self._ledger_rows(year, policy))
            scope = str(year) if year is not None else "complet"
            return self.book.documents.add_file(
                tmp, kind="export", year=year or clock.today().year,
                name=f"livre_recettes_{scope}_{self._stamp()}.csv",
                title=f"Livre des recettes {scope} (CSV)", move=True,
            )
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def invoices_csv(self) -> int:
        tmp = self._temp(".csv")
        try:
            with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(["Numéro", "Type", "Date d'émission", "Client", "Devise", "Total",
                                 "Taux (devise pour 1 EUR)", "Contre-valeur EUR", "SHA-256 du PDF"])
                for r in self.book.invoices.register():
                    writer.writerow([
                        r["number"], "Facture" if r["kind"] == "invoice" else "Avoir",
                        r["issue_date"].isoformat(), r["client_name"], r["currency"],
                        _csv_amount(r["total"]), _csv_rate(r["fx_rate"]),
                        _csv_amount(r["total_eur"]), r["pdf_sha256"],
                    ])
            return self.book.documents.add_file(
                tmp, kind="export", year=clock.today().year,
                name=f"registre_factures_{self._stamp()}.csv",
                title="Registre des factures (CSV)", move=True,
            )
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # -- ledger PDF ---------------------------------------------------------
    def ledger_pdf(self, year: int) -> int:
        tmp = self._temp(".pdf")
        try:
            self._render_ledger_pdf(year, tmp)
            return self.book.documents.add_file(
                tmp, kind="export", year=year,
                name=f"livre_recettes_{year}_{self._stamp()}.pdf",
                title=f"Livre des recettes {year} (PDF)", move=True,
            )
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _render_ledger_pdf(self, year: int, path: Path) -> None:
        profile = self.book.profile()
        policy = profile.policy
        ledger = self.book.ledger
        accent = colors.HexColor("#2d5c96")
        band = colors.HexColor("#eef2f7")
        rule = colors.HexColor("#c9d0da")
        muted = colors.HexColor("#5b6472")

        body = ParagraphStyle("b", fontName="Helvetica", fontSize=7.6, leading=9.4)
        right = ParagraphStyle("r", parent=body, alignment=TA_RIGHT)
        bold = ParagraphStyle("bo", parent=body, fontName="Helvetica-Bold")
        bold_r = ParagraphStyle("bor", parent=bold, alignment=TA_RIGHT)
        head = ParagraphStyle("h", parent=bold, textColor=colors.white)
        head_r = ParagraphStyle("hr", parent=head, alignment=TA_RIGHT)
        title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=accent)
        note = ParagraphStyle("n", fontName="Helvetica", fontSize=8, leading=10.5, textColor=muted)

        def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
            return Paragraph(escape(str(text if text is not None else "")), style)

        columns = ["N°", "Encaissé le", "Client (origine)", "Objet", "Brut", "Taux", "Brut EUR",
                   "Frais EUR", "Net crédité", "Mode", "Référence", "Facture"]
        numeric = {"Brut", "Taux", "Brut EUR", "Frais EUR", "Net crédité"}
        rows: list[list[Any]] = [[p(c, head_r if c in numeric else head) for c in columns]]
        marks: list[int] = []
        entries = ledger.entries(year)
        for q in ledger.quarter_totals(year, policy):
            in_quarter = [e for e in entries if (e["received_on"].month - 1) // 3 + 1 == q["quarter"]]
            for e in in_quarter:
                what = e["description"]
                if e["kind"] == "reversal":
                    what = f"Annulation de l'écriture {e['reverses_seq']} : {e['reason']}"
                rows.append([
                    p(e["seq"]), p(fmt_date_fr(e["received_on"])), p(e["client_name"]), p(what),
                    p(fmt_amount_fr(e["amount_gross"], e["currency"]), right),
                    p(fmt_rate_fr(e["fx_rate"]), right),
                    p(fmt_amount_fr(e["eur_gross"]), right),
                    p(fmt_amount_fr(e["fee_eur"]), right),
                    p(fmt_amount_fr(e["net_credited"], e["net_currency"]), right),
                    p(translate(e["payment_method"], "fr")), p(e["provider_ref"]),
                    Paragraph(escape(e["linked_invoice"]).replace(", ", "<br/>"), body),
                ])
            marks.append(len(rows))
            rows.append([
                p(""), p(""), p(f"Total {q['label']}", bold), p(""), p(""), p(""),
                p(fmt_amount_fr(q["eur_gross"]), bold_r), p(fmt_amount_fr(q["fee_eur"]), bold_r),
                p(fmt_amount_fr(q["net_eur"], "EUR"), bold_r), p(""), p(""), p(""),
            ])
        quarters = ledger.quarter_totals(year, policy)
        counted = sum((q["counted"] for q in quarters), ZERO)
        marks.append(len(rows))
        rows.append([
            p(""), p(""), p(f"Total {year}", bold), p(""), p(""), p(""),
            p(fmt_amount_fr(sum((q["eur_gross"] for q in quarters), ZERO)), bold_r),
            p(fmt_amount_fr(sum((q["fee_eur"] for q in quarters), ZERO)), bold_r),
            p(fmt_amount_fr(sum((q["net_eur"] for q in quarters), ZERO), "EUR"), bold_r),
            p(""), p(""), p(""),
        ])

        page = landscape(A4)
        width = page[0] - 24 * mm
        widths = [0.03, 0.065, 0.12, 0.195, 0.085, 0.05, 0.07, 0.06, 0.08, 0.05, 0.095, 0.10]
        table = Table(rows, repeatRows=1, colWidths=[width * w for w in widths])
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, rule),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for row in marks:
            style.append(("BACKGROUND", (0, row), (-1, row), band))
        table.setStyle(TableStyle(style))

        seller = profile.display_name or "Identité à renseigner"
        if profile.siren.strip():
            seller += f" - SIREN {profile.siren.strip()}"

        def footer(canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(muted)
            canvas.drawString(12 * mm, 8 * mm, f"Livre des recettes {year} - {seller}")
            canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {doc.page}")
            canvas.restoreState()

        doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
                                topMargin=12 * mm, bottomMargin=14 * mm,
                                title=f"Livre des recettes {year}", author=seller)
        doc.build(
            [
                p(f"Livre des recettes {year}", title),
                p(seller, note),
                Spacer(1, 3 * mm),
                table,
                Spacer(1, 4 * mm),
                p(f"Chiffre d'affaires retenu pour {year} : {fmt_amount_fr(counted, 'EUR')}, "
                  f"encaissements à la date de réception.", bold),
                p(f"Base : {BASIS_FR.get(policy.basis, policy.basis)} ; "
                  f"{FX_FR.get(policy.fx, policy.fx)}. Choix {TO_CONFIRM_FR}.", note),
                p("Les écritures ne sont jamais modifiées : une correction est une écriture "
                  "d'annulation motivée.", note),
            ],
            onFirstPage=footer, onLaterPages=footer,
        )
