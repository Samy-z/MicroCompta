"""Small shared presentation widgets and helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.errors import IssueBlocked, MicroComptaError
from ..theme import FG, FG_DIM, LEVEL_COLOURS


class StatCard(QFrame):
    """One headline number with a caption underneath."""

    def __init__(self, label: str, tip: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(112)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        self.caption = QLabel(label)
        self.caption.setObjectName("metricLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)
        if tip:
            self.setToolTip(tip)

    def set_text(self, text: str, colour: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {colour or FG};")


class StatRow(QScrollArea):
    """A horizontal strip of StatCards addressed by key.

    Scrolls sideways rather than sizing itself: a plain row would push its width into the
    window's minimum size, wider than a 1536px screen.
    """

    def __init__(self, specs: Iterable[tuple[str, str, str]], parent: QWidget | None = None):
        """specs: (key, label, tooltip)"""
        super().__init__(parent)
        self.setObjectName("statRow")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

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

    def __init__(self, text: str = "", level: str = "info", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_level(level)

    def set_level(self, level: str) -> None:
        colour = LEVEL_COLOURS.get(level, FG_DIM)
        self.setStyleSheet(
            f"color: {colour}; border: 1px solid {colour}; border-radius: 9px;"
            "padding: 1px 9px; background: transparent; font-size: 11px;"
        )


class Banner(QFrame):
    """A full-width message with a coloured edge. Hidden when it has nothing to say."""

    def __init__(self, level: str = "info", text: str = "", parent: QWidget | None = None):
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
        self.setVisible(bool(text))

    def set_level(self, level: str) -> None:
        self.edge.setStyleSheet(f"background: {LEVEL_COLOURS.get(level, FG_DIM)}; border: none;")

    def show_text(self, text: str, level: str | None = None) -> None:
        if level:
            self.set_level(level)
        self.label.setText(text)
        self.setVisible(bool(text))


def heading(text: str, object_name: str = "h1") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def dim_label(text: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(wrap)
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
    edit.setDisplayFormat("yyyy-MM-dd")
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
    fill_years(combo, years, current)
    return combo


def fill_years(combo: QComboBox, years: Iterable[int], current: int) -> None:
    combo.blockSignals(True)
    combo.clear()
    for year in sorted(set(years) | {current}, reverse=True):
        combo.addItem(str(year), year)
    combo.setCurrentIndex(combo.findData(current))
    combo.blockSignals(False)


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
