"""The French invoice PDF. Rendered only from the frozen snapshot, never from live data.

Foreign-currency presentation follows economie.gouv.fr ("Comment facturer dans une
monnaie étrangère ?", written 2025-09-05, read 2026-11-04): the amount in the currency,
its euro counter-value, the rate applied, with the ECB rate of the day as reference.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .money import fmt_amount_fr, fmt_date_fr, fmt_quantity_fr, fmt_rate_fr

INK = colors.HexColor("#1b2230")
MUTED = colors.HexColor("#5b6472")
ACCENT = colors.HexColor("#2d5c96")
RULE = colors.HexColor("#c9d0da")
BAND = colors.HexColor("#f2f5f9")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.2, leading=10.8, textColor=MUTED)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11.5)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=TA_RIGHT)
HEAD = ParagraphStyle("head", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
HEAD_R = ParagraphStyle("headr", parent=HEAD, alignment=TA_RIGHT)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=20, leading=24,
                       textColor=ACCENT)
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold", fontSize=8,
                       leading=10, textColor=MUTED)
STRONG = ParagraphStyle("strong", parent=BODY, fontName="Helvetica-Bold")
STRONG_R = ParagraphStyle("strongr", parent=STRONG, alignment=TA_RIGHT)
BODY_R = ParagraphStyle("bodyr", parent=BODY, alignment=TA_RIGHT)


def _p(text: Any, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), style)


def _period(snapshot: dict[str, Any]) -> str:
    start, end = snapshot["service_start"], snapshot["service_end"]
    if start and end and start == end:
        return fmt_date_fr(start)
    if start and end:
        return f"du {fmt_date_fr(start)} au {fmt_date_fr(end)}"
    return ""


def _party_block(label: str, lines: list[str]) -> list[Any]:
    return [_p(label, LABEL)] + [_p(line) for line in lines if line]


def render_invoice_pdf(snapshot: dict[str, Any], path: Path | str, draft: bool = False) -> None:
    currency = snapshot["currency"]
    is_credit = snapshot["kind"] == "credit_note"
    doc_title = "AVOIR" if is_credit else "FACTURE"
    seller = snapshot["seller"]
    client = snapshot["client"]

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        footer = f"{seller['name']} - Entrepreneur individuel"
        if seller["siren"]:
            footer += f" - SIREN {seller['siren']}"
        canvas.drawString(18 * mm, 10 * mm, footer)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        if draft:
            canvas.setFont("Helvetica-Bold", 56)
            canvas.setFillColor(colors.Color(0.75, 0.2, 0.2, alpha=0.16))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(38)
            canvas.drawCentredString(0, 0, "BROUILLON")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"{doc_title.capitalize()} {snapshot['number']}",
        author=seller["name"] or "MicroCompta",
    )
    width = A4[0] - 36 * mm
    story: list[Any] = []

    # -- heading ------------------------------------------------------------
    number = "Document non valable - brouillon" if draft else f"n° {snapshot['number']}"
    facts = [
        _p(number, STRONG_R),
        _p(f"Date d'émission : {fmt_date_fr(snapshot['issue_date'])}", BODY_R),
        _p(f"Date de la prestation : {_period(snapshot)}", BODY_R),
    ]
    heading = Table([[_p(doc_title, TITLE), facts]], colWidths=[width * 0.4, width * 0.6])
    heading.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [heading, Spacer(1, 7 * mm)]

    # -- parties ------------------------------------------------------------
    seller_lines = [seller["name"], seller["status"], seller["address"],
                    f"SIREN : {seller['siren']}" if seller["siren"] else "SIREN : à venir",
                    seller["email"]]
    client_lines = [client["name"], client["address"], client["country"],
                    f"Identifiant fiscal : {client['tax_id']}" if client["tax_id"] else "",
                    client["email"]]
    parties = Table(
        [[_party_block("ÉMETTEUR", seller_lines), _party_block("CLIENT", client_lines)]],
        colWidths=[width / 2, width / 2],
    )
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, colors.white),
    ]))
    story += [parties, Spacer(1, 5 * mm)]

    if is_credit and snapshot["credits_number"]:
        story += [
            _p(f"Avoir annulant la facture n° {snapshot['credits_number']}.", STRONG),
            _p(f"Motif : {snapshot['reason']}"),
            Spacer(1, 4 * mm),
        ]

    # -- lines --------------------------------------------------------------
    rows: list[list[Any]] = [[
        _p("Désignation", HEAD),
        _p("Date de paiement", HEAD),
        _p("Quantité", HEAD_R),
        _p(f"Prix unitaire HT ({currency})", HEAD_R),
        _p(f"Total HT ({currency})", HEAD_R),
    ]]
    for line in snapshot["lines"]:
        rows.append([
            _p(line["description"], CELL),
            _p(fmt_date_fr(line["payment_date"]), CELL),
            _p(fmt_quantity_fr(Decimal(line["quantity"])), CELL_R),
            _p(fmt_amount_fr(Decimal(line["unit_price"])), CELL_R),
            _p(fmt_amount_fr(Decimal(line["total"])), CELL_R),
        ])
    table = Table(
        rows, repeatRows=1,
        colWidths=[width * 0.40, width * 0.15, width * 0.11, width * 0.18, width * 0.16],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Spacer(1, 4 * mm)]

    # -- totals -------------------------------------------------------------
    total = Decimal(snapshot["total"])
    totals: list[list[Any]] = [
        [_p(f"Total HT ({currency})"), _p(fmt_amount_fr(total, currency), BODY_R)],
        [_p("TVA"), _p(fmt_amount_fr(Decimal(0), currency), BODY_R)],
        [_p(f"Total de l'avoir ({currency})" if is_credit else f"Total à payer ({currency})", STRONG),
         _p(fmt_amount_fr(total, currency), STRONG_R)],
    ]
    fx = snapshot.get("fx")
    if currency != "EUR":
        euros = (
            fmt_amount_fr(Decimal(snapshot["total_eur"]), "EUR")
            if snapshot.get("total_eur") else "à calculer à l'émission"
        )
        totals.append([_p("Contre-valeur en euros", STRONG), _p(euros, STRONG_R)])
    totals_table = Table(totals, colWidths=[width * 0.27, width * 0.23], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 2), (-1, 2), 0.7, INK),
        ("BACKGROUND", (0, 2), (-1, -1), BAND),
    ]))
    story += [totals_table, Spacer(1, 3 * mm)]

    if currency != "EUR":
        if fx:
            rate_line = (
                f"Taux de change appliqué : 1 EUR = {fmt_rate_fr(Decimal(fx['rate']))} {currency} "
                f"({fx['source']}"
                + (f" du {fmt_date_fr(fx['date'])}" if fx.get("date") else "")
                + ")."
            )
        else:
            rate_line = "Taux de change : à renseigner à l'émission (taux de référence BCE du jour)."
        story.append(_p(rate_line))

    story += [_p(snapshot["vat_mention"], STRONG), Spacer(1, 5 * mm)]

    # -- payment and legal mentions ----------------------------------------
    payment_dates = ", ".join(fmt_date_fr(d) for d in snapshot["payment_dates"])
    if payment_dates:
        label = "Date de paiement" if len(snapshot["payment_dates"]) == 1 else "Dates de paiement"
        story.append(_p(f"{label} : {payment_dates}"))
    if snapshot["payment_terms"] and not is_credit:
        story.append(_p(f"Conditions de règlement : {snapshot['payment_terms']}"))
    if snapshot["notes"]:
        story.append(_p(snapshot["notes"]))
    indemnity = fmt_amount_fr(Decimal(snapshot["recovery_indemnity"]), "EUR")
    story.append(Spacer(1, 4 * mm))
    if not is_credit:  # nothing is due on a credit note, so nothing can be late
        story += [
            _p(snapshot["late_rate_text"], SMALL),
            _p(f"Indemnité forfaitaire pour frais de recouvrement en cas de retard de paiement : "
               f"{indemnity}.", SMALL),
        ]

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
