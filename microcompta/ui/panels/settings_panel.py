"""Settings: identity and activity, and the effective-dated figures.

Opened from the gear icon at the top right, in a dialog of its own.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.ledger_policy import BASIS_LABELS, FEE_POINTER, FX_LABELS, UNCONFIRMED
from ...core.profile import Profile, siren_is_valid
from ...i18n import available_languages, current_language, fmt_date, fmt_money, fmt_percent, tr
from ..models import Col, wrap_tip
from ..widgets.table_view import DataTable
from .common import (
    Banner, bubble, button_box, dim_label, form_row, from_qdate, guarded, heading, make_date_edit,
    scroll_page, to_qdate,
)


def _unit_tip(unit: str) -> str:
    return {
        "eur": tr("An amount in euros."),
        "rate": tr("A fraction: 0.256 means 25.6%."),
        "days": tr("A number of days."),
        "date": tr("A date written YYYY-MM-DD."),
        "md": tr("A month and day written MM-DD."),
    }.get(unit, "")


class FigureDialog(QDialog):
    """A new value from a date. Older dates keep the old value, so the past doesn't change."""

    def __init__(self, row: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(row["key"])
        self.resize(540, 0)
        form = QFormLayout(self)
        title = tr(row["label"]) if row["label"] else row["key"]
        form.addRow(heading(title, tr("The figure you are changing."), "h2"))
        form.addRow(dim_label(
            tr("To change a figure over time, enter a later date: earlier dates keep the old "
               "value. Using an existing date corrects that row."),
            tip=tr("This way, past years keep the rates and limits that applied to them."),
        ))
        self.effective = make_date_edit(clock.today())
        form_row(form, tr("Effective from"), self.effective, tr("The first day this value applies."))
        self.value = QLineEdit(row["value"])
        form_row(form, tr("Value"), self.value, _unit_tip(row["unit"]) or tr("The new value."))
        self.source = QLineEdit(row.get("source") or "")
        form_row(form, tr("Source"), self.source, tr("Where this figure comes from, so it can be re-checked."))
        self.note = QLineEdit(row.get("note") or "")
        form_row(form, tr("Note"), self.note, tr("Your own note."))
        form.addRow(button_box(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self.accept, self.reject))


class SettingsPanel(QWidget):
    changed = Signal()
    status = Signal(str)
    language_changed = Signal()

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        for index, (page, title, tip) in enumerate((
            (self._build_profile_tab(), tr("Identity and activity"),
             tr("Who you are, how your activity is declared, and how the app behaves.")),
            (self._build_figures_tab(), tr("Figures"),
             tr("Every limit, rate and fixed date the app uses, with its source.")),
        )):
            self.tabs.addTab(page, title)
            self.tabs.setTabToolTip(index, wrap_tip(tip))

    # -- profile ------------------------------------------------------------
    def _build_profile_tab(self) -> QWidget:
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        self.setup_banner = Banner("warn", tip=tr("Invoices, limits and deadlines all need these details."))
        outer.addWidget(self.setup_banner)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns)

        identity = QGroupBox(tr("Identity, printed on invoices"))
        bubble(identity, tr("Stored only on this computer and in your own Drive backup."))
        form = QFormLayout(identity)
        form.setSpacing(6)
        self.legal_name = QLineEdit()
        self.legal_name.setPlaceholderText(tr("First name and surname"))
        form_row(form, tr("Name"), self.legal_name, tr(
            'Invoices print this followed by "EI", and "Entrepreneur individuel".'
        ))
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(64)
        form_row(form, tr("Address"), self.address, tr("Printed on invoices. A final invoice needs it."))
        self.siren = QLineEdit()
        self.siren.setPlaceholderText(tr("9 digits. Leave empty until you have it"))
        self.siren.textChanged.connect(self._check_siren)
        form_row(form, tr("SIREN"), self.siren, tr(
            "Your 9-digit business number. Drafts work without it, but a final invoice is refused."
        ))
        self.siren_note = dim_label("", tip=tr("Checks the format and the check digit, not the register."))
        form.addRow("", self.siren_note)
        self.email = QLineEdit()
        form_row(form, tr("Email"), self.email, tr("Optional, printed on invoices."))
        left.addWidget(identity)

        activity = QGroupBox(tr("Activity"))
        bubble(activity, tr("Decides your rates, your limits and your deadlines."))
        form = QFormLayout(activity)
        form.setSpacing(6)
        self.has_start = QCheckBox(tr("I know my start date"))
        bubble(self.has_start, tr("Leave unticked until your business is registered."))
        self.has_start.toggled.connect(lambda on: self.start_date.setEnabled(on))
        form.addRow("", self.has_start)
        self.start_date = make_date_edit(clock.today())
        form_row(form, tr("Start date"), self.start_date, tr(
            "The first day of activity. First-year limits are prorated from it, and the deadlines "
            "are worked out from it."
        ))
        self.activity = QComboBox()
        self.activity.addItem(tr("BNC, non-regulated (SSI)"), "bnc")
        self.activity.addItem(tr("BIC, services"), "bic")
        form_row(form, tr("Activity"), self.activity, tr(
            "Decides the contribution rate and the tax allowance."
        ))
        self.frequency = QComboBox()
        self.frequency.addItem(tr("Monthly"), "monthly")
        self.frequency.addItem(tr("Quarterly (on request to URSSAF)"), "quarterly")
        form_row(form, tr("Declarations"), self.frequency, tr(
            "How often you declare turnover. Monthly unless you asked URSSAF for quarterly, within "
            "the month after your start."
        ))
        self.acre = QCheckBox(tr("ACRE: 75% of the normal rate, until the end of the 3rd civil "
                                 "quarter after the start"))
        bubble(self.acre, tr("Tick if you were granted ACRE. It adds the request deadline and lowers the rate."))
        form.addRow("", self.acre)
        self.vl = QCheckBox(tr("Versement libératoire"))
        bubble(self.vl, tr("Tick if you opted to pay income tax with your contributions. It raises what to set aside."))
        form.addRow("", self.vl)
        left.addWidget(activity)
        left.addStretch(1)

        app = QGroupBox(tr("App"))
        bubble(app, tr("How the app itself behaves."))
        form = QFormLayout(app)
        form.setSpacing(6)
        self.language = QComboBox()
        for code, name in available_languages().items():
            self.language.addItem(name, code)
        form_row(form, tr("Language"), self.language, tr(
            "The language of the app. Invoices and the livre des recettes stay in French either way: "
            "they are French legal records."
        ))
        self.reminder_days = QLineEdit()
        form_row(form, tr("Remind before (days)"), self.reminder_days, tr(
            "How many days before a deadline to remind you, separated by commas."
        ))
        self.keep_in_tray = QCheckBox(tr("Keep running in the tray when the window closes, so "
                                         "reminders still fire"))
        bubble(self.keep_in_tray, tr("Reminders only fire while the app runs. Quit from the tray icon's menu."))
        form.addRow("", self.keep_in_tray)
        right.addWidget(app)

        turnover = QGroupBox(tr("Turnover: {label}", label=tr(UNCONFIRMED)))
        bubble(turnover, tr("The official sources read so far don't settle these two choices."))
        form = QFormLayout(turnover)
        form.setSpacing(6)
        self.basis = QComboBox()
        for key, label in BASIS_LABELS.items():
            self.basis.addItem(tr(label), key)
        form_row(form, tr("Fees"), self.basis, tr(FEE_POINTER))
        self.fx_policy = QComboBox()
        for key, label in FX_LABELS.items():
            self.fx_policy.addItem(tr(label), key)
        form_row(form, tr("USD rate"), self.fx_policy, tr(
            "No official rule yet: the ECB rule on economie.gouv.fr covers the rate printed on an "
            "invoice, not turnover."
        ))
        form.addRow("", dim_label(
            tr("{pointer} The USD rate has no official rule yet: the ECB rule on economie.gouv.fr "
               "covers the rate printed on an invoice, not turnover.", pointer=tr(FEE_POINTER)),
            tip=tr("Pages F23257 on service-public and \"Comment facturer dans une monnaie étrangère ?\" "
                   "on economie.gouv.fr."),
        ))
        form.addRow("", dim_label(
            tr("Each entry stores its gross, rate, fee and net separately, so changing these "
               "recomputes every year without touching an entry. Declarations already filed stay "
               "as filed."),
            tip=tr("If URSSAF answers differently, change the setting here."),
        ))
        right.addWidget(turnover)

        wording = QGroupBox(tr("Invoice wording"))
        bubble(wording, tr("Printed on invoices in French, as you write it here."))
        form = QFormLayout(wording)
        form.setSpacing(6)
        self.vat_mention = QLineEdit()
        form_row(form, tr("VAT mention"), self.vat_mention, tr(
            "Required on every invoice. F23208 says the art. 293 B reference is tolerated until "
            "2027-12-31: see Deadlines."
        ))
        self.late_rate = QPlainTextEdit()
        self.late_rate.setFixedHeight(50)
        form_row(form, tr("Late-payment rate"), self.late_rate, tr("Required on every invoice."))
        self.payment_terms = QLineEdit()
        form_row(form, tr("Payment terms"), self.payment_terms, tr("Printed on invoices."))
        right.addWidget(wording)
        right.addStretch(1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.saved_label = dim_label("", wrap=False, tip=tr("Whether your last changes were saved."))
        save_row.addWidget(self.saved_label)
        self.save_button = QPushButton(tr("Save"))
        self.save_button.setObjectName("primary")
        self.save_button.setMinimumWidth(120)
        bubble(self.save_button, tr("Saves this page. Changing the language applies straight away."))
        self.save_button.clicked.connect(lambda _c=False: self.save_profile())
        save_row.addWidget(self.save_button)
        outer.addLayout(save_row)
        return scroll_page(inner)

    def _check_siren(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.siren_note.setText(tr("Drafts are fine without one. A final invoice needs it."))
        elif siren_is_valid(text):
            self.siren_note.setText(tr("Valid format."))
        else:
            self.siren_note.setText(tr("Not valid: 9 digits with a correct check digit."))

    def load_profile(self) -> None:
        p = self.book.profile()
        self.language.setCurrentIndex(max(0, self.language.findData(p.language)))
        self.legal_name.setText(p.legal_name)
        self.address.setPlainText(p.address)
        self.siren.setText(p.siren)
        self._check_siren(p.siren)
        self.email.setText(p.email)
        self.has_start.setChecked(p.start_date is not None)
        self.start_date.setEnabled(p.start_date is not None)
        self.start_date.setDate(to_qdate(p.start_date or clock.today()))
        self.activity.setCurrentIndex(self.activity.findData(p.activity))
        self.frequency.setCurrentIndex(self.frequency.findData(p.declaration_frequency))
        self.acre.setChecked(p.acre_enabled)
        self.vl.setChecked(p.vl_enabled)
        self.basis.setCurrentIndex(self.basis.findData(p.turnover_basis))
        self.fx_policy.setCurrentIndex(self.fx_policy.findData(p.fx_policy))
        self.vat_mention.setText(p.vat_mention)
        self.late_rate.setPlainText(p.late_rate_text)
        self.payment_terms.setText(p.payment_terms)
        self.reminder_days.setText(p.reminder_days)
        self.keep_in_tray.setChecked(p.keep_in_tray)
        self.setup_banner.show_text(
            "" if p.is_set_up else tr(
                "Enter your details here, then add your client on the Clients tab. Everything stays on "
                "this computer and in your own Drive backup."
            )
        )
        self.saved_label.setText("")

    def _profile_from_fields(self) -> Profile:
        return replace(
            self.book.profile(),
            language=self.language.currentData(),
            legal_name=self.legal_name.text().strip(),
            address=self.address.toPlainText().strip(),
            siren="".join(self.siren.text().split()),
            email=self.email.text().strip(),
            start_date=from_qdate(self.start_date.date()) if self.has_start.isChecked() else None,
            activity=self.activity.currentData(),
            declaration_frequency=self.frequency.currentData(),
            acre_enabled=self.acre.isChecked(),
            vl_enabled=self.vl.isChecked(),
            turnover_basis=self.basis.currentData(),
            fx_policy=self.fx_policy.currentData(),
            vat_mention=self.vat_mention.text().strip(),
            late_rate_text=self.late_rate.toPlainText().strip(),
            payment_terms=self.payment_terms.text().strip(),
            reminder_days=self.reminder_days.text().strip(),
            keep_in_tray=self.keep_in_tray.isChecked(),
        )

    def has_unsaved_changes(self) -> bool:
        return self._profile_from_fields() != self.book.profile()

    def save_profile(self) -> None:
        profile = self._profile_from_fields()
        self.book.save_profile(profile)
        self.load_profile()   # shows values as stored, and clears the first-run banner
        self.saved_label.setText(tr("Saved."))
        self.status.emit(tr("Settings saved."))
        self.changed.emit()
        if profile.language != current_language():
            self.language_changed.emit()

    # -- figures ------------------------------------------------------------
    def _build_figures_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        self.figures_table = DataTable([
            Col("label_shown", tr("Figure"), width=360, tip=tr("What this figure is used for.")),
            Col("shown", tr("Value"), width=90, tip=tr("The value from its effective date.")),
            Col("effective_from", tr("Effective from"), "date", 150, tip=tr("The first day this value applies.")),
            Col("in_force", tr("In force today"), "bool", 152, tip=tr("Whether this is the value that applies today.")),
            Col("note_shown", tr("Note"), width=280, tip=tr("Anything worth knowing about this figure.")),
            Col("source_shown", tr("Source"), width=420, tip=tr("Where it comes from, so it can be re-checked.")),
            Col("key", tr("Key"), width=170, tip=tr("The name the code uses for this figure.")),
        ], key="row_key")
        self.figures_table.add_button(tr("New value…"), self.edit_figure, primary=True, tip=tr(
            "Adds a value from a chosen date for the selected figure. Earlier dates keep the old one."
        ))
        self.figures_table.row_activated.connect(lambda _row: self.edit_figure())
        lay.addWidget(self.figures_table, 1)
        lay.addWidget(dim_label(
            tr("Every limit, rate and fixed date the app uses is here and nowhere in the code. Sources "
               "were checked on 2026-11-04. Re-check them yourself: this is a reminder tool, not tax "
               "advice."),
            tip=tr("A yearly reminder in Deadlines asks you to look again."),
        ))
        return page

    @staticmethod
    def _show_figure(row: dict[str, Any]) -> str:
        unit, value = row["unit"], row["value"]
        if unit == "rate":
            return fmt_percent(value)
        if unit == "eur":
            amount = Decimal(value)
            return fmt_money(amount, decimals=0 if amount == amount.to_integral() else 2)
        if unit == "date":
            return fmt_date(date.fromisoformat(value))
        return value

    def _load_figures(self) -> None:
        today: date = clock.today()
        rows = self.book.figures.rows()
        in_force: dict[str, Any] = {}
        for row in rows:
            if row["effective_from"] <= today:
                in_force[row["key"]] = row["effective_from"]
        shown = []
        for row in rows:
            row = dict(row)
            row["label_shown"] = tr(row["label"]) if row["label"] else row["key"]
            row["note_shown"] = tr(row["note"]) if row["note"] else ""
            row["source_shown"] = tr(row["source"]) if row["source"] else ""
            row["shown"] = self._show_figure(row)
            row["in_force"] = in_force.get(row["key"]) == row["effective_from"]
            row["row_key"] = f"{row['key']}|{row['effective_from']}"
            row["_dim"] = not row["in_force"]
            shown.append(row)
        self.figures_table.set_rows(shown)

    def edit_figure(self) -> None:
        row = self.figures_table.current_row()
        if row is None:
            return
        dialog = FigureDialog(row, self)
        if dialog.exec() == QDialog.Accepted and guarded(
            self, tr("Figure not saved"),
            lambda: self.book.figures.upsert(
                row["key"], from_qdate(dialog.effective.date()), dialog.value.text(),
                dialog.source.text(), dialog.note.text(),
            ) or True,
        ):
            self.status.emit(tr("{key} updated.", key=row["key"]))
            self._load_figures()
            self.changed.emit()

    # -- reload -------------------------------------------------------------
    def reload(self) -> None:
        self.load_profile()
        self._load_figures()


class SettingsDialog(QDialog):
    """What the gear icon opens. Modal, so the rest of the app reloads once it is done."""

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Settings"))
        self.setModal(True)
        self.panel = SettingsPanel(book, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(self.panel, 1)
        buttons = button_box(QDialogButtonBox.Close, self.accept, self.reject)
        buttons.setContentsMargins(0, 0, 10, 0)
        layout.addWidget(buttons)

    def _ask_about_unsaved(self) -> Any:
        return QMessageBox.question(
            self, tr("Save your changes?"),
            tr("You changed something on the Identity and activity page without saving it."),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save,
        )

    def reject(self) -> None:
        """Esc, the Close button and the window's X all come through here."""
        if self.panel.has_unsaved_changes():
            answer = self._ask_about_unsaved()
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Save:
                self.panel.save_profile()
        super().reject()


__all__ = ["FigureDialog", "SettingsDialog", "SettingsPanel"]
