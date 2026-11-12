"""The navigation rail on the left, and the pages it switches between.

PageStack answers the same calls as a QTabWidget (addTab, tabText, setCurrentWidget...), so
the rest of the app moves between pages as it did between tabs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import icons
from ..models import wrap_tip
from ..theme import ACCENT, LEVEL_COLOURS, ON_STATUS, TEXT, TEXT_3

ICON_SIZE = 22
MIN_WIDTH = 76
LABEL_WIDTH = 64      # past this, a label goes on two lines


class NavButton(QToolButton):
    """An icon over its label. Selected, it gets a tinted background and a small accent bar."""

    def __init__(self, label: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("navItem")
        self._label = label
        self.ensurePolished()      # the style sheet sets the font the label is measured in
        self.setCheckable(True)
        self.setAutoExclusive(False)     # the rail's button group does that
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIcon(icons.icon(icon_name, TEXT_3, ACCENT, TEXT, ICON_SIZE))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setText(self._fold(label))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._badge = ""
        self._badge_level = "bad"

    def _fold(self, label: str) -> str:
        """"Revue annuelle" fits the rail as "Revue" over "annuelle". Split at the space
        that leaves the shorter longest line."""
        metrics = self.fontMetrics()
        if metrics.horizontalAdvance(label) <= LABEL_WIDTH or " " not in label:
            return label
        words = label.split(" ")
        splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
        top, bottom = min(splits, key=lambda s: max(metrics.horizontalAdvance(s[0]),
                                                    metrics.horizontalAdvance(s[1])))
        return f"{top}\n{bottom}"

    def changeEvent(self, event: Any) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, "_label"):
            folded = self._fold(self._label)
            if folded != self.text():
                self.setText(folded)

    @property
    def badge(self) -> str:
        return self._badge

    def set_badge(self, text: str, level: str = "bad") -> None:
        self._badge, self._badge_level = text, level
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(QRectF(0, self.height() / 2 - 9, 3, 18), 1.5, 1.5)
        if self._badge:
            font = QFont(self.font())
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            width = max(16.0, painter.fontMetrics().horizontalAdvance(self._badge) + 8.0)
            rect = QRectF(self.width() / 2 + 3, 3, width, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(LEVEL_COLOURS.get(self._badge_level, LEVEL_COLOURS["bad"])))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor(ON_STATUS))
            painter.drawText(rect, Qt.AlignCenter, self._badge)
        painter.end()


class NavRail(QWidget):
    selected = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("navRail")
        self.buttons: list[NavButton] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 10, 6, 10)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)

    def add(self, label: str, icon_name: str) -> NavButton:
        button = NavButton(label, icon_name, self)
        index = len(self.buttons)
        self.group.addButton(button, index)
        button.clicked.connect(lambda _checked=False, i=index: self.selected.emit(i))
        self._layout.insertWidget(index, button)
        self.buttons.append(button)
        self._fit()
        return button

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit()

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def _fit(self) -> None:
        """As wide as the longest label, so no label is cut in either language."""
        widest = max((b.sizeHint().width() for b in self.buttons), default=0)
        margins = self._layout.contentsMargins()
        self.setFixedWidth(max(widest + 8, MIN_WIDTH) + margins.left() + margins.right())


class PageStack(QStackedWidget):
    """The pages. The rail beside it is how you move between them."""

    def __init__(self, rail: NavRail, parent: QWidget | None = None):
        super().__init__(parent)
        self.rail = rail
        self._labels: list[str] = []
        self._notes: list[str] = []
        self._tips: list[str] = []
        rail.selected.connect(self.setCurrentIndex)
        self.currentChanged.connect(rail.set_current)

    # -- the calls of a QTabWidget ----------------------------------------------------
    def addTab(self, widget: QWidget, label: str, icon_name: str = "limits") -> int:  # noqa: N802
        index = self.addWidget(widget)
        self._labels.append(label)
        self._notes.append("")
        self._tips.append("")
        self.rail.add(label, icon_name)
        if index == self.currentIndex():
            self.rail.set_current(index)
        return index

    def tabText(self, index: int) -> str:  # noqa: N802
        note = self._notes[index]
        return f"{self._labels[index]}  {note}" if note else self._labels[index]

    def tabToolTip(self, index: int) -> str:  # noqa: N802
        return self._tips[index]

    def setTabToolTip(self, index: int, tip: str) -> None:  # noqa: N802
        self._tips[index] = tip
        self._show(index)

    # -- what the rail shows beside a label --------------------------------------------
    def set_note(self, index: int, note: str = "", count: int = 0, level: str = "bad") -> None:
        """A short note such as "(2 overdue)": a badge on the rail, and in the label's text."""
        self._notes[index] = note
        self.rail.buttons[index].set_badge(str(count) if count else "", level)
        self._show(index)

    def _show(self, index: int) -> None:
        button = self.rail.buttons[index]
        text = self.tabText(index)
        tip = self._tips[index]
        button.setToolTip(wrap_tip(f"{text}\n{tip}" if tip else text))
        button.setAccessibleName(text)
        button.setAccessibleDescription(tip)


__all__ = ["NavButton", "NavRail", "PageStack"]
