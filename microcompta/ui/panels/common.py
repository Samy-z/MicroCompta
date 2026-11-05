"""Small shared presentation widgets and helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDateEdit, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLayout,
    QMessageBox, QScrollArea, QSizePolicy, QToolTip, QVBoxLayout, QWidget,
)

from ...core.errors import IssueBlocked, MicroComptaError
from ...i18n import date_input_format, tr
from ..models import wrap_tip
from ..theme import FG, FG_DIM, LEVEL_COLOURS


def bubble(widget: QWidget, text: str, name: str = "") -> QWidget:
    """The info bubble for a widget, and the same words for a screen reader."""
    widget.setToolTip(wrap_tip(text))
    widget.setAccessibleDescription(text)
    if name:
        widget.setAccessibleName(name)
    return widget


def form_row(form: QFormLayout, label_text: str, field: QWidget | QLayout, tip: str) -> QLabel:
    """A labelled field whose label and field both carry the bubble."""
    label = QLabel(label_text)
    bubble(label, tip)
    if isinstance(field, QLayout):
        widgets = [field.itemAt(i).widget() for i in range(field.count())]
        widgets = [w for w in widgets if w is not None]
        for widget in widgets:
            bubble(widget, tip, label_text)
        if widgets:
            label.setBuddy(widgets[0])
    else:
        bubble(field, tip, label_text)
        label.setBuddy(field)
    form.addRow(label, field)
    return label


class _BubbleOnFocus:
    """Tab onto it and the bubble shows, so a number is reachable without a mouse."""

    def focusInEvent(self, event: Any) -> None:  # noqa: N802
        super().focusInEvent(event)
        if self.toolTip():
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)


class StatCard(_BubbleOnFocus, QFrame):
    """One headline number with a caption underneath."""

    def __init__(self, label: str, tip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(112)
        self.setFocusPolicy(Qt.TabFocus)
        self._label = label
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        self.caption = QLabel(label)
        self.caption.setObjectName("metricLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)
        bubble(self, tip, label)

    def set_tip(self, text: str) -> None:
        bubble(self, text)

    def set_text(self, text: str, colour: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {colour or FG};")
        self.setAccessibleName(f"{self._label}: {text}")


class StatRow(QScrollArea):
    """A horizontal strip of StatCards addressed by key.

    Scrolls sideways rather than sizing itself: a plain row would push its width into the
    window's minimum size, wider than a 1536px screen.
    """

    def __init__(self, specs: Iterable[tuple[str, str, str]], parent: QWidget | None = None):
        """specs: (key, label, bubble text)"""
        super().__init__(parent)
        self.setObjectName("statRow")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)

        inner = QWidget()
        inner.setObjectName("statRowInner")
        lay = QHBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self.cards: dict[str, StatCard] = {}
        for key, label, tip in specs:
            card = StatCard(label, tip)
            self.cards[key] = card
            lay.addWidget(card)
        lay.addStretch(1)

        self.setWidget(inner)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(
            inner.sizeHint().height() + self.horizontalScrollBar().sizeHint().height()
        )

    def set(self, key: str, text: str, colour: str | None = None) -> None:
        self.cards[key].set_text(text, colour)


class Chip(QLabel):
    """A small rounded status label."""

    def __init__(self, text: str = "", level: str = "info", tip: str = "",
                 parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_level(level)
        if tip:
            bubble(self, tip)

    def set_level(self, level: str) -> None:
        colour = LEVEL_COLOURS.get(level, FG_DIM)
        self.setStyleSheet(
            f"color: {colour}; border: 1px solid {colour}; border-radius: 9px;"
            "padding: 1px 9px; background: transparent; font-size: 11px;"
        )


class Banner(QFrame):
    """A full-width message with a coloured edge. Hidden when it has nothing to say."""

    def __init__(self, level: str = "info", text: str = "", tip: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self.edge = QFrame()
        self.edge.setFixedWidth(3)
        lay.addWidget(self.edge)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.label, 1)
        self.set_level(level)
        if tip:
            bubble(self, tip)
        self.setVisible(bool(text))

    def set_level(self, level: str) -> None:
        self.edge.setStyleSheet(f"background: {LEVEL_COLOURS.get(level, FG_DIM)}; border: none;")

    def show_text(self, text: str, level: str | None = None) -> None:
        if level:
            self.set_level(level)
        self.label.setText(text)
        self.setVisible(bool(text))


def button_box(standard: Any, accept: Callable[[], Any], reject: Callable[[], Any]) -> QDialogButtonBox:
    """Standard dialog buttons, with their bubbles."""
    buttons = QDialogButtonBox(standard)
    for which, tip in (
        (QDialogButtonBox.Save, tr("Keeps what you entered.")),
        (QDialogButtonBox.Ok, tr("Confirms this.")),
        (QDialogButtonBox.Cancel, tr("Leaves without changing anything.")),
        (QDialogButtonBox.Close, tr("Closes this window.")),
    ):
        button = buttons.button(which)
        if button is not None:
            bubble(button, tip)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(reject)
    return buttons


def heading(text: str, tip: str = "", object_name: str = "h1") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    if tip:
        bubble(label, tip)
    return label


def dim_label(text: str = "", wrap: bool = True, tip: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(wrap)
    if tip:
        bubble(label, tip)
    return label


def card_frame() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def scroll_page(content: QWidget) -> QScrollArea:
    """A vertically scrolling page, so nothing is clipped on a small screen."""
    area = QScrollArea()
    area.setObjectName("page")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    content.setObjectName("pageInner")
    area.setWidget(content)
    return area


def make_date_edit(value: date | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat(date_input_format())
    calendar = QCalendarWidget()
    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    edit.setCalendarWidget(calendar)
    edit.setDate(to_qdate(value or date.today()))
    return edit


def to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def year_combo(years: Iterable[int], current: int) -> QComboBox:
    combo = QComboBox()
    combo.setMinimumWidth(80)
    bubble(combo, tr("The year these figures are for."), tr("Year"))
    fill_years(combo, years, current)
    return combo


def fill_years(combo: QComboBox, years: Iterable[int], current: int) -> None:
    combo.blockSignals(True)
    combo.clear()
    for year in sorted(set(years) | {current}, reverse=True):
        combo.addItem(str(year), year)
    combo.setCurrentIndex(combo.findData(current))
    combo.blockSignals(False)


def run_export(panel: Any, label: str, action: Callable[[], int], ask: bool) -> int | None:
    """Run an export for a panel with a book and status and changed signals, then say where it went."""
    doc_id = guarded(panel, tr("Export failed"), action)
    if doc_id is None:
        return None
    doc = panel.book.documents.get(doc_id)
    path = panel.book.documents.path_of(doc)
    panel.status.emit(tr("{kind} export saved and queued for Drive: {path}", kind=label, path=doc["rel_path"]))
    panel.changed.emit()
    if ask:
        box = QMessageBox(panel)
        box.setWindowTitle(tr("Export saved"))
        box.setText(tr("Saved to:\n{path}\n\nAlso queued for Google Drive.", path=path))
        open_button = box.addButton(tr("Open folder"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    return doc_id


def guarded(parent: QWidget, title: str, action: Callable[[], Any]) -> Any:
    """Run an action; show a refused one as a message. Returns None if refused."""
    try:
        return action()
    except IssueBlocked as exc:
        QMessageBox.warning(parent, title, "\n\n".join(f"• {r}" for r in exc.reasons))
    except MicroComptaError as exc:
        QMessageBox.warning(parent, title, str(exc))
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, title, str(exc))
    return None
