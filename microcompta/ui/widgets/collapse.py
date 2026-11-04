"""The collapsed form of the left panel, and the dock's title bar."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ...i18n import tr
from ..models import wrap_tip
from ..theme import ACCENT, BG_ALT, BG_RAISED, BORDER, FG, FG_DIM

STRIP_WIDTH = 30


class CollapsedStrip(QWidget):
    """A narrow vertical band with rotated text, clicked to reopen the panel.

    Painted by hand: Qt has no rotated-text label.
    """

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._hover = False
        self.setFixedWidth(STRIP_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(wrap_tip(tr("Show the form for recording a payment (Ctrl+B).")))
        self.setAccessibleName(text)
        self.setAttribute(Qt.WA_Hover, True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(STRIP_WIDTH, 260)

    def enterEvent(self, event: Any) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(BG_ALT if self._hover else BG_RAISED))

        painter.setPen(QPen(QColor(ACCENT if self._hover else BORDER), 1))
        edge = self.width() - 1
        painter.drawLine(edge, 0, edge, self.height())

        painter.setPen(QPen(QColor(ACCENT if self._hover else FG_DIM), 1.6))
        cx, cy = self.width() / 2, 14
        painter.drawLine(cx - 2.5, cy - 3, cx + 2.5, cy)
        painter.drawLine(cx + 2.5, cy, cx - 2.5, cy + 3)

        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF(), 8.0))
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        painter.setFont(font)
        painter.setPen(QColor(FG if self._hover else FG_DIM))
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        painter.rotate(-90)
        painter.drawText(
            QRect(-self.height() // 2, -self.width() // 2, self.height(), self.width()),
            Qt.AlignCenter,
            self._text,
        )
        painter.end()


class DockTitleBar(QWidget):
    """Title strip for the left dock, carrying the collapse button."""

    collapse_requested = Signal()

    def __init__(self, title: str, tip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dockTitle")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 4, 4)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setObjectName("dockTitleText")
        label.setToolTip(wrap_tip(tip))
        layout.addWidget(label)
        layout.addStretch(1)

        button = QPushButton("‹‹")
        button.setObjectName("dockCollapse")
        button.setToolTip(wrap_tip(tr("Collapse this panel to give the tables more room (Ctrl+B).")))
        button.setAccessibleName(tr("Collapse this panel"))
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(26, 20)
        button.clicked.connect(self.collapse_requested.emit)
        layout.addWidget(button)
        self.button = button
