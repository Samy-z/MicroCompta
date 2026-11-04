"""The language layer: nothing untranslated, nothing stored in a language, documents stay French."""

from __future__ import annotations

import ast
import csv
import json
import string
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from pypdf import PdfReader

from conftest import pay
from microcompta import config, i18n
from microcompta.core.errors import ValidationError
from microcompta.core.profile import Profile

ROOT = config.ROOT_DIR
PACKAGE = ROOT / "microcompta"
CATALOG = json.loads((PACKAGE / "data" / "i18n" / "fr.json").read_text(encoding="utf-8"))["messages"]


def _python_files(folder: Path = PACKAGE) -> list[Path]:
    return sorted(folder.rglob("*.py"))


def _marked_strings() -> dict[str, str]:
    """Every string in a tr() or N_() call, with where it came from."""
    found: dict[str, str] = {}
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("tr", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
    seed = json.loads((PACKAGE / "data" / "figures_seed.json").read_text(encoding="utf-8"))["figures"]
    for row in seed:
        for field in ("label", "source", "note"):
            text = row.get(field) or ""
            if text and not text.startswith("http"):
                found.setdefault(text, "figures_seed.json")
    return found


def _placeholders(text: str) -> list[str]:
    return sorted({name for _, name, _, _ in string.Formatter().parse(text) if name})


# -- the catalogue is complete and consistent ----------------------------------
def test_every_string_in_the_code_has_a_french_translation():
    missing = {text: where for text, where in _marked_strings().items() if text not in CATALOG}
    assert not missing, f"{len(missing)} untranslated, first: {list(missing.items())[:5]}"


def test_the_catalogue_has_no_leftover_strings():
    leftover = set(CATALOG) - set(_marked_strings())
    assert not leftover, f"No longer in the code: {sorted(leftover)[:5]}"


def test_placeholders_match_their_source():
    wrong = {k: v for k, v in CATALOG.items() if _placeholders(k) != _placeholders(v)}
    assert not wrong, list(wrong.items())[:3]


def test_no_translation_is_empty():
    assert not [k for k, v in CATALOG.items() if not v.strip()]


def test_every_translation_can_be_formatted():
    for key, value in CATALOG.items():
        names = _placeholders(key)
        assert value.format(**{n: "x" for n in names}), key


def test_a_tr_call_never_builds_its_text():
    """An f-string as the key can't match the catalogue, so it would silently stay in English."""
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" and node.args:
                assert not isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)), f"{path.name}:{node.lineno}"


_TEXT_CALLS = {
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle", "setTitle", "setTabText",
    "setTabToolTip", "setAccessibleName", "setAccessibleDescription", "QLabel", "QPushButton",
    "QCheckBox", "QGroupBox", "QAction", "addItem", "add_button", "heading", "dim_label", "bubble",
    "Chip", "show_text", "emit", "set_status", "notify", "form_row", "showMessage",
    "CollapsedStrip", "DockTitleBar", "setItemText",
}
# Brand and currency codes, and the style keys that select a colour or a heading size.
_ALLOWED_LITERALS = {"MicroCompta", "‹‹", "#", "USD", "EUR", "CFE", "ACRE",
                     "h1", "h2", "ok", "near", "warn", "over", "bad", "info"}


def _ui_literals() -> list[str]:
    found = []
    for path in _python_files(PACKAGE / "ui"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name not in _TEXT_CALLS:
                continue
            # addItem's second argument is the stored value, not what is shown.
            shown = node.args[:1] if name == "addItem" else node.args
            for arg in shown:
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and any(c.isalpha() for c in arg.value) and arg.value not in _ALLOWED_LITERALS):
                    found.append(f"{path.name}:{node.lineno} {arg.value[:50]!r}")
    return found


def test_the_ui_shows_no_text_that_skips_translation():
    assert not _ui_literals()


# -- language choice -----------------------------------------------------------
def test_french_is_the_default_and_english_stays_available():
    assert i18n.DEFAULT_LANGUAGE == "fr"
    assert Profile().language == "fr"
    assert i18n.available_languages() == {"en": "English", "fr": "Français"}


def test_a_new_profile_on_disk_starts_in_french(book):
    assert book.profile().language == "fr"


def test_the_choice_is_saved(book):
    profile = book.profile()
    profile.language = "en"
    book.save_profile(profile)
    assert book.profile().language == "en"


def test_english_is_the_source_text_untouched():
    i18n.set_language("en")
    assert i18n.tr("Limits") == "Limits"
    assert i18n.tr("Entry {seq} does not exist.", seq=3) == "Entry 3 does not exist."


def test_french_translates_and_formats():
    i18n.set_language("fr")
    assert i18n.tr("Limits") == "Plafonds"
    assert i18n.tr("Entry {seq} does not exist.", seq=3) == "L'écriture 3 n'existe pas."


def test_text_with_no_translation_falls_back_to_itself():
    i18n.set_language("fr")
    assert i18n.tr("A note the owner typed") == "A note the owner typed"


def test_an_unknown_language_falls_back_to_english():
    i18n.set_language("xx")
    assert i18n.current_language() == "en"


def test_adding_a_file_is_all_it_takes_to_offer_a_language(tmp_path, monkeypatch):
    (tmp_path / "de.json").write_text(json.dumps(
        {"language_name": "Deutsch", "messages": {"Limits": "Grenzen"}}
    ), encoding="utf-8")
    monkeypatch.setattr(i18n, "_CATALOG_DIR", tmp_path)
    i18n._messages.cache_clear()
    try:
        assert i18n.available_languages()["de"] == "Deutsch"
        i18n.set_language("de")
        assert i18n.tr("Limits") == "Grenzen"
    finally:
        i18n.set_language("en")
        i18n._messages.cache_clear()


# -- formats -------------------------------------------------------------------
def nbsp(text: str) -> str:
    return text.replace(" ", " ")


@pytest.mark.parametrize("language, expected", [
    ("en", ("€1,234.56", "-$12.00", "25.6%", "1.0823", "2027-03-05")),
    ("fr", ("1 234,56 €", "-12,00 $", "25,6 %", "1,0823", "05/03/2027")),
])
def test_numbers_and_dates_follow_the_language(language, expected):
    i18n.set_language(language)
    shown = (i18n.fmt_money(D("1234.56")), i18n.fmt_money(D("-12"), "USD"), i18n.fmt_percent(D("0.256")),
             i18n.fmt_rate(D("1.082300")), i18n.fmt_date(date(2027, 3, 5)))
    assert tuple(nbsp(s) for s in shown) == expected


def test_french_keeps_its_spaces_together():
    i18n.set_language("fr")
    assert " :" in i18n.tr("Turnover declaration: {period}", period="x")


def test_french_amounts_can_be_typed_back_in(book, client_id):
    i18n.set_language("fr")
    seq = book.ledger.record_payment(
        received_on=date(2027, 3, 5), client_id=client_id, description="Travail",
        amount_gross="1 000,50", fx_rate="1,25", net_credited="770,00", payment_method="Stripe",
    )
    assert book.ledger.get(seq)["amount_gross"] == D("1000.50")


# -- core messages -------------------------------------------------------------
def test_refusals_come_in_the_current_language(book, client_id):
    i18n.set_language("fr")
    with pytest.raises(ValidationError, match="doit être positif"):
        pay(book, client_id, date(2027, 3, 5), gross="0", net="1")


def test_limit_cards_and_deadlines_are_translated(book, identity, client_id, pinned_today):
    identity.start_date = date(2027, 3, 1)
    book.save_profile(identity)
    i18n.set_language("fr")
    card = book.limits.report(2027).ceiling
    assert card.title == "Plafond micro"
    assert "Sous le plafond" in card.headline
    assert "70 087" in card.details[0]
    titles = [i["title"] for i in book.deadlines.items()]
    assert any(t.startswith("Déclaration de chiffre d'affaires") for t in titles)
    labels = [p.label for p in book.limits.report(2027).periods]
    assert labels[0] == "mars 2027"


# -- records don't depend on the language --------------------------------------
def test_stored_values_stay_as_keys_whatever_the_language(book, client_id):
    i18n.set_language("fr")
    seq = book.ledger.record_payment(
        received_on=date(2027, 3, 5), client_id=client_id, description="Travail",
        amount_gross="1000", fx_rate="1.25", net_credited="770", payment_method="Bank transfer",
    )
    assert book.ledger.get(seq)["payment_method"] == "Bank transfer"
    assert book.ledger.get(seq)["fx_source"] == "ECB reference"


def test_the_hash_chain_doesnt_notice_a_language_change(book, identity, client_id):
    book.save_profile(identity)
    i18n.set_language("fr")
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = book.invoices.create_monthly_draft(client_id, 2027, 3)
    book.invoices.issue(invoice_id, date(2027, 4, 1), fx_rate="1.08", fx_rate_date=date(2027, 4, 1))
    assert book.verify() == []
    i18n.set_language("en")
    pay(book, client_id, date(2027, 3, 6))
    assert book.verify() == []


def test_the_turnover_doesnt_notice_a_language_change(book, identity, client_id):
    identity.start_date = date(2026, 11, 2)
    book.save_profile(identity)
    pay(book, client_id, date(2027, 3, 5), "1000", "1.25")
    i18n.set_language("en")
    english = book.limits.turnover(2027)
    i18n.set_language("fr")
    assert book.limits.turnover(2027) == english


# -- legal documents are French in both languages -----------------------------
def _pdf_text(path: Path) -> str:
    return " ".join(
        " ".join(page.extract_text() for page in PdfReader(str(path)).pages).replace(" ", " ").split()
    )


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_invoice_is_in_french_whatever_the_app_language(book, identity, client_id, language):
    book.save_profile(identity)
    i18n.set_language(language)
    pay(book, client_id, date(2027, 3, 5))
    invoice_id = book.invoices.create_monthly_draft(client_id, 2027, 3)
    book.invoices.issue(invoice_id, date(2027, 4, 1), fx_rate="1.0823", fx_rate_date=date(2027, 4, 1))
    doc = book.documents.get(int(book.invoices.get(invoice_id)["document_id"]))
    text = _pdf_text(book.documents.path_of(doc))
    for mention in ("FACTURE", "Date d'émission : 01/04/2027", "Contre-valeur en euros",
                    "taux de référence BCE", "TVA non applicable, art. 293 B du CGI"):
        assert mention in text, mention
    assert "Issue date" not in text


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_ledger_exports_are_in_french_whatever_the_app_language(book, identity, client_id, language):
    book.save_profile(identity)
    i18n.set_language(language)
    book.ledger.record_payment(
        received_on=date(2027, 3, 5), client_id=client_id, description="Travail",
        amount_gross="1000", fx_rate="1.25", net_credited="770", payment_method="Bank transfer",
    )
    path = book.documents.path_of(book.documents.get(book.exports.ledger_csv(2027)))
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    assert rows[0][2] == "Date d'encaissement"
    record = dict(zip(rows[0], rows[1]))
    assert record["Mode de règlement"] == "Virement bancaire"
    assert record["Source du taux"] == "Référence BCE"
    pdf = book.documents.path_of(book.documents.get(book.exports.ledger_pdf(2027)))
    assert "Livre des recettes 2027" in _pdf_text(pdf)
    assert "Virement bancaire" in _pdf_text(pdf)
