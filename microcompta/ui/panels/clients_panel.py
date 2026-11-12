"""Clients: the tab, and the window that adds or edits one.

The payment form offers the same window beside its list of clients.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from ...core.book import Book
from ...core.clients import EXCLUSION_LABEL
from ...i18n import tr
from ..models import Col
from ..widgets.table_view import DataTable
from .common import FittedDialog, bubble, button_box, dim_label, form_row, guarded, heading


class ClientDialog(FittedDialog):
    def __init__(self, client: dict[str, Any] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Client"))
        self.resize(500, 0)
        client = client or {}
        form = QFormLayout(self)
        self.name = QLineEdit(client.get("name", ""))
        form_row(form, tr("Name"), self.name, tr("The client's legal name, printed on invoices."))
        self.address = QPlainTextEdit(client.get("address") or "")
        self.address.setFixedHeight(64)
        form_row(form, tr("Address"), self.address, tr("Printed on invoices. A final invoice needs it."))
        self.country = QLineEdit(client.get("country") or "")
        form_row(form, tr("Country"), self.country, tr("Printed on invoices."))
        self.tax_id = QLineEdit(client.get("tax_id") or "")
        form_row(form, tr("Tax ID"), self.tax_id, tr(
            "Optional: the client's tax or company number, printed on invoices."
        ))
        self.email = QLineEdit(client.get("email") or "")
        form_row(form, tr("Email"), self.email, tr("Optional, printed on invoices."))
        self.currency = QComboBox()
        self.currency.addItems(["USD", "EUR"])
        self.currency.setCurrentText(client.get("currency", "USD"))
        form_row(form, tr("Currency"), self.currency, tr(
            "What this client pays in. Payments and invoices use it. A euro client needs no exchange rate."
        ))
        self.taxed_in_france = QCheckBox(tr("Taxed in France: counts towards the VAT franchise"))
        self.taxed_in_france.setChecked(bool(client.get("taxed_in_france", False)))
        exclusion = tr(
            "Only turnover taxed in France counts. A non-EU business client is excluded, {label}.",
            label=tr(EXCLUSION_LABEL),
        )
        bubble(self.taxed_in_france, exclusion)
        form.addRow("", self.taxed_in_france)
        form.addRow("", dim_label(exclusion, tip=tr("BOFiP BOI-TVA-DECLA-40-10-10, section 180.")))
        self.vat_note = QLineEdit(client.get("vat_note") or "")
        self.vat_note.setPlaceholderText(tr("Why this flag is set this way"))
        form_row(form, tr("VAT note"), self.vat_note, tr("Your own note, not printed anywhere."))
        self.active = QCheckBox(tr("Active: offered when recording a payment"))
        self.active.setChecked(bool(client.get("active", True)))
        bubble(self.active, tr("Untick for a former client. Their records stay."))
        form.addRow("", self.active)
        form.addRow(button_box(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self.accept, self.reject))

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


def ask_for_new_client(book: Book, parent: QWidget) -> dict[str, Any] | None:
    """Open the client window and save the result. Returns the new client, or None if there is none."""
    dialog = ClientDialog(parent=parent)
    if dialog.exec() != QDialog.Accepted:
        return None
    client_id = guarded(parent, tr("Client not saved"), lambda: book.clients.add(**dialog.values()))
    return None if client_id is None else book.clients.get(client_id)


class ClientsPanel(QWidget):
    changed = Signal()
    status = Signal(str)

    def __init__(self, book: Book, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(7)
        layout.addWidget(heading(tr("Clients"), tr("Who you invoice.")))
        self.table = DataTable([
            Col("name", tr("Name"), width=220, tip=tr("The client's legal name.")),
            Col("country", tr("Country"), width=120, tip=tr("Printed on invoices.")),
            Col("currency", tr("Currency"), width=70, tip=tr("What this client pays in.")),
            Col("vat_flag", tr("VAT franchise"), width=250, tip=tr(
                "Whether this client's turnover counts towards the VAT franchise."
            )),
            Col("tax_id", tr("Tax ID"), width=130, tip=tr("The client's tax or company number.")),
            Col("active", tr("Active"), "bool", 60, tip=tr("Whether the client is offered when recording a payment.")),
            Col("address", tr("Address"), width=320, tip=tr("Printed on invoices.")),
        ], key="id")
        self.table.add_button(tr("Add client…"), self.add_client, primary=True, tip=tr("Adds someone to invoice."))
        self.table.add_button(tr("Edit…"), self.edit_client, tip=tr(
            "Changes the selected client. Issued invoices and ledger entries keep what they were recorded with."
        ))
        self.table.row_activated.connect(lambda _row: self.edit_client())
        layout.addWidget(self.table, 1)
        layout.addWidget(dim_label(
            tr("Editing a client doesn't change issued invoices or ledger entries: each keeps the "
               "details it was recorded with."),
            tip=tr("A record stays true to the day it was made."),
        ))

    def reload(self) -> None:
        rows = []
        for client in self.book.clients.list():
            row = dict(client)
            row["vat_flag"] = (
                tr("Counts: taxed in France") if client["taxed_in_france"]
                else tr("Excluded: {label}", label=tr(EXCLUSION_LABEL))
            )
            rows.append(row)
        self.table.set_rows(rows)

    def add_client(self) -> None:
        client = ask_for_new_client(self.book, self)
        if client is not None:
            self.status.emit(tr("Client {name} added.", name=client["name"]))
            self.changed.emit()

    def edit_client(self) -> None:
        row = self.table.current_row()
        if row is None:
            return
        dialog = ClientDialog(row, self)
        if dialog.exec() == QDialog.Accepted and guarded(
            self, tr("Client not saved"),
            lambda: self.book.clients.update(row["id"], **dialog.values()) or True,
        ):
            self.changed.emit()


__all__ = ["ClientDialog", "ClientsPanel", "ask_for_new_client"]
