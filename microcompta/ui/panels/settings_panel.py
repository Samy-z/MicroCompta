"""Settings: identity and activity, clients, and the effective-dated figures."""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ...core import clock
from ...core.book import Book
from ...core.clients import EXCLUSION_LABEL
from ...core.ledger_policy import BASIS_LABELS, FEE_POINTER, FX_LABELS, UNCONFIRMED
from ...core.money import to_decimal
from ...core.profile import siren_is_valid
from ..models import Col
from ..widgets.table_view import DataTable
from .common import Banner, dim_label, from_qdate, guarded, heading, make_date_edit, scroll_page, to_qdate


class ClientDialog(QDialog):
    def __init__(self, client: dict[str, Any] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Client")
        self.resize(480, 0)
        client = client or {}
        form = QFormLayout(self)
        self.name = QLineEdit(client.get("name", ""))
        form.addRow("Name", self.name)
        self.address = QPlainTextEdit(client.get("address") or "")
        self.address.setFixedHeight(64)
        form.addRow("Address", self.address)
        self.country = QLineEdit(client.get("country") or "")
        form.addRow("Country", self.country)
        self.tax_id = QLineEdit(client.get("tax_id") or "")
        self.tax_id.setToolTip("Optional: the client's tax or company number, printed on invoices.")
        form.addRow("Tax ID", self.tax_id)
        self.email = QLineEdit(client.get("email") or "")
        form.addRow("Email", self.email)
        self.currency = QComboBox()
        self.currency.addItems(["USD", "EUR"])
        self.currency.setCurrentText(client.get("currency", "USD"))
        form.addRow("Currency", self.currency)
        self.taxed_in_france = QCheckBox("Taxed in France: counts towards the VAT franchise")
        self.taxed_in_france.setChecked(bool(client.get("taxed_in_france", False)))
        form.addRow("", self.taxed_in_france)
        form.addRow("", dim_label(
            f"Only turnover taxed in France counts. A non-EU business client is excluded, "
            f"{EXCLUSION_LABEL}."
        ))
        self.vat_note = QLineEdit(client.get("vat_note") or "")
        self.vat_note.setPlaceholderText("Why this flag is set this way")
        form.addRow("VAT note", self.vat_note)
        self.active = QCheckBox("Active: offered when recording a payment")
        self.active.setChecked(bool(client.get("active", True)))
        form.addRow("", self.active)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "name": self.name.text(),
            "address": self.address.toPlainText(),
            "country": self.country.text(),
            "tax_id": self.tax_id.text(),
            "email": self.email.text(),
            "currency": self.currency.currentText(),
            "taxed_in_france": self.taxed_in_france.isChecked(),
            "vat_note": self.vat_note.text(),
            "active": self.active.isChecked(),
        }


class FigureDialog(QDialog):
    """A new value from a date. Older dates keep the old value, so the past doesn't change."""

    def __init__(self, row: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(row["key"])
        self.resize(520, 0)
        form = QFormLayout(self)
        form.addRow(heading(row["label"] or row["key"], "h2"))
        form.addRow(dim_label(
            "To change a figure over time, enter a later date: earlier dates keep the old value. "
            "Using an existing date corrects that row."
        ))
        self.effective = make_date_edit(clock.today())
        form.addRow("Effective from", self.effective)
        self.value = QLineEdit(row["value"])
        form.addRow(f"Value ({row['unit']})", self.value)
        self.source = QLineEdit(row.get("source") or "")
        form.addRow("Source", self.source)
        self.note = QLineEdit(row.get("note") or "")
        form.addRow("Note", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class SettingsPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_profile_tab(), "Identity and activity")
        self.tabs.addTab(self._build_clients_tab(), "Clients")
        self.tabs.addTab(self._build_figures_tab(), "Figures")

    # -- profile ------------------------------------------------------------
    def _build_profile_tab(self) -> QWidget:
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        self.setup_banner = Banner("warn")
        outer.addWidget(self.setup_banner)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns)

        identity = QGroupBox("Identity, printed on invoices")
        form = QFormLayout(identity)
        form.setSpacing(6)
        self.legal_name = QLineEdit()
        self.legal_name.setPlaceholderText("First name and surname")
        self.legal_name.setToolTip('Invoices print this followed by "EI", and "Entrepreneur individuel".')
        form.addRow("Name", self.legal_name)
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(64)
        form.addRow("Address", self.address)
        self.siren = QLineEdit()
        self.siren.setPlaceholderText("9 digits. Leave empty until you have it")
        self.siren.textChanged.connect(self._check_siren)
        form.addRow("SIREN", self.siren)
        self.siren_note = dim_label("")
        form.addRow("", self.siren_note)
        self.email = QLineEdit()
        form.addRow("Email", self.email)
        left.addWidget(identity)

        activity = QGroupBox("Activity")
        form = QFormLayout(activity)
        form.setSpacing(6)
        self.has_start = QCheckBox("I know my start date")
        self.has_start.toggled.connect(lambda on: self.start_date.setEnabled(on))
        form.addRow("", self.has_start)
        self.start_date = make_date_edit(clock.today())
        form.addRow("Start date", self.start_date)
        self.activity = QComboBox()
        self.activity.addItem("BNC, non-regulated (SSI)", "bnc")
        self.activity.addItem("BIC, services", "bic")
        form.addRow("Activity", self.activity)
        self.frequency = QComboBox()
        self.frequency.addItem("Monthly", "monthly")
        self.frequency.addItem("Quarterly (on request to URSSAF)", "quarterly")
        form.addRow("Declarations", self.frequency)
        self.acre = QCheckBox("ACRE: 75% of the normal rate, until the end of the 3rd civil "
                              "quarter after the start")
        form.addRow("", self.acre)
        self.vl = QCheckBox("Versement libératoire")
        form.addRow("", self.vl)
        left.addWidget(activity)
        left.addStretch(1)

        turnover = QGroupBox(f"Turnover: {UNCONFIRMED}")
        form = QFormLayout(turnover)
        form.setSpacing(6)
        self.basis = QComboBox()
        for key, label in BASIS_LABELS.items():
            self.basis.addItem(label, key)
        form.addRow("Fees", self.basis)
        self.fx_policy = QComboBox()
        for key, label in FX_LABELS.items():
            self.fx_policy.addItem(label, key)
        form.addRow("USD rate", self.fx_policy)
        form.addRow("", dim_label(
            f"{FEE_POINTER} The USD rate has no official rule yet: the ECB rule on economie.gouv.fr "
            "covers the rate printed on an invoice, not turnover."
        ))
        form.addRow("", dim_label(
            "Each entry stores its gross, rate, fee and net separately, so changing these "
            "recomputes every year without touching an entry. Declarations already filed stay as "
            "filed."
        ))
        right.addWidget(turnover)

        wording = QGroupBox("Invoice wording")
        form = QFormLayout(wording)
        form.setSpacing(6)
        self.vat_mention = QLineEdit()
        self.vat_mention.setToolTip("F23208 says the art. 293 B reference is tolerated until 2027-12-31: "
                                    "see Deadlines.")
        form.addRow("VAT mention", self.vat_mention)
        self.late_rate = QPlainTextEdit()
        self.late_rate.setFixedHeight(50)
        form.addRow("Late-payment rate", self.late_rate)
        self.payment_terms = QLineEdit()
        form.addRow("Payment terms", self.payment_terms)
        right.addWidget(wording)

        behaviour = QGroupBox("Reminders")
        form = QFormLayout(behaviour)
        form.setSpacing(6)
        self.reminder_days = QLineEdit()
        self.reminder_days.setToolTip("Days before a deadline, separated by commas.")
        form.addRow("Remind before (days)", self.reminder_days)
        self.keep_in_tray = QCheckBox("Keep running in the tray when the window closes, so "
                                      "reminders still fire")
        form.addRow("", self.keep_in_tray)
        right.addWidget(behaviour)
        right.addStretch(1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setMinimumWidth(120)
        self.save_button.clicked.connect(lambda _c=False: self.save_profile())
        save_row.addWidget(self.save_button)
        outer.addLayout(save_row)
        return scroll_page(inner)

    def _check_siren(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.siren_note.setText("Drafts are fine without one. A final invoice needs it.")
        elif siren_is_valid(text):
            self.siren_note.setText("Valid format.")
        else:
            self.siren_note.setText("Not valid: 9 digits with a correct check digit.")

    def load_profile(self) -> None:
        p = self.book.profile()
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
            "" if p.is_set_up else
            "Enter your details here, then add your client under Clients. Everything stays on "
            "this computer and in your own Drive backup."
        )

    def save_profile(self) -> None:
        p = self.book.profile()
        p.legal_name = self.legal_name.text().strip()
        p.address = self.address.toPlainText().strip()
        p.siren = "".join(self.siren.text().split())
        p.email = self.email.text().strip()
        p.start_date = from_qdate(self.start_date.date()) if self.has_start.isChecked() else None
        p.activity = self.activity.currentData()
        p.declaration_frequency = self.frequency.currentData()
        p.acre_enabled = self.acre.isChecked()
        p.vl_enabled = self.vl.isChecked()
        p.turnover_basis = self.basis.currentData()
        p.fx_policy = self.fx_policy.currentData()
        p.vat_mention = self.vat_mention.text().strip()
        p.late_rate_text = self.late_rate.toPlainText().strip()
        p.payment_terms = self.payment_terms.text().strip()
        p.reminder_days = self.reminder_days.text().strip()
        p.keep_in_tray = self.keep_in_tray.isChecked()
        self.book.save_profile(p)
        self.status.emit("Settings saved.")
        self.changed.emit()

    # -- clients ------------------------------------------------------------
    def _build_clients_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        self.clients_table = DataTable([
            Col("name", "Name", width=220),
            Col("country", "Country", width=120),
            Col("currency", "Currency", width=70),
            Col("vat_flag", "VAT franchise", width=250),
            Col("tax_id", "Tax ID", width=130),
            Col("active", "Active", "bool", 60),
            Col("address", "Address", width=320),
        ], key="id")
        self.clients_table.add_button("Add client…", self.add_client, primary=True)
        self.clients_table.add_button("Edit…", self.edit_client)
        self.clients_table.row_activated.connect(lambda _row: self.edit_client())
        lay.addWidget(self.clients_table, 1)
        lay.addWidget(dim_label(
            "Editing a client doesn't change issued invoices or ledger entries: each keeps the "
            "details it was recorded with."
        ))
        return page

    def _load_clients(self) -> None:
        rows = []
        for client in self.book.clients.list():
            row = dict(client)
            row["vat_flag"] = (
                "Counts: taxed in France" if client["taxed_in_france"]
                else f"Excluded: {EXCLUSION_LABEL}"
            )
            rows.append(row)
        self.clients_table.set_rows(rows)

    def add_client(self) -> None:
        dialog = ClientDialog(parent=self)
        if dialog.exec() == QDialog.Accepted and guarded(
            self, "Client not saved", lambda: self.book.clients.add(**dialog.values())
        ):
            self.changed.emit()

    def edit_client(self) -> None:
        row = self.clients_table.current_row()
        if row is None:
            return
        dialog = ClientDialog(row, self)
        if dialog.exec() == QDialog.Accepted and guarded(
            self, "Client not saved",
            lambda: self.book.clients.update(row["id"], **dialog.values()) or True,
        ):
            self.changed.emit()

    # -- figures ------------------------------------------------------------
    def _build_figures_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        self.figures_table = DataTable([
            Col("label", "Figure", width=360),
            Col("shown", "Value", width=90),
            Col("effective_from", "Effective from", "date", 100),
            Col("in_force", "In force today", "bool", 90),
            Col("note", "Note", width=280),
            Col("source", "Source", width=420),
            Col("key", "Key", width=170),
        ], key="row_key")
        self.figures_table.add_button("New value…", self.edit_figure, primary=True)
        self.figures_table.row_activated.connect(lambda _row: self.edit_figure())
        lay.addWidget(self.figures_table, 1)
        lay.addWidget(dim_label(
            "Every limit, rate and fixed date the app uses is here and nowhere in the code. Sources "
            "were checked on 2026-11-04. Re-check them yourself: this is a reminder tool, not tax advice."
        ))
        return page

    @staticmethod
    def _show_figure(row: dict[str, Any]) -> str:
        if row["unit"] == "rate":
            return f"{to_decimal(row['value']) * 100:.1f}%"
        if row["unit"] == "eur":
            return f"€{to_decimal(row['value']):,.2f}".replace(".00", "")
        return row["value"]

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
            self, "Figure not saved",
            lambda: self.book.figures.upsert(
                row["key"], from_qdate(dialog.effective.date()), dialog.value.text(),
                dialog.source.text(), dialog.note.text(),
            ) or True,
        ):
            self.status.emit(f"{row['key']} updated.")
            self.changed.emit()

    # -- reload -------------------------------------------------------------
    def reload(self) -> None:
        self.load_profile()
        self._load_clients()
        self._load_figures()


__all__ = ["SettingsPanel", "ClientDialog", "FigureDialog", "QLabel"]
