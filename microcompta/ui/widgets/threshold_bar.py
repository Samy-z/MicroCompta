"""How full a limit is: the amount so far, the run-rate, and the limit itself."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import BG, BORDER, FG, FG_DIM, LEVEL_COLOURS


class ThresholdBar(QWidget):
    """The right end of the track is a little past the limit, so being over it shows."""

    HEADROOM = 1.12

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("threshold")
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._value = Decimal(0)
        self._limit = Decimal(0)
        self._projection: Decimal | None = None
        self._ticks: list[Decimal] = []
        self._level = "ok"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(240, 22)

    def set_values(self, value: Decimal, limit: Decimal, projection: Decimal | None = None,
                   ticks: list[Decimal] | None = None, level: str = "ok") -> None:
        self._value = Decimal(value)
        self._limit = Decimal(limit)
        self._projection = Decimal(projection) if projection is not None else None
        self._ticks = list(ticks or [])
        self._level = level
        self.update()

    def _scale(self) -> float:
        top = max(self._limit * Decimal(str(self.HEADROOM)), self._value,
                  self._projection or Decimal(0), Decimal(1))
        return float(top)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = self._scale()
        width = self.width() - 2
        y, height = 6.0, 10.0
        track = QRectF(1, y, width, height)

        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor(BG))
        painter.drawRoundedRect(track, 4, 4)
        painter.setPen(Qt.NoPen)

        colour = QColor(LEVEL_COLOURS.get(self._level, FG_DIM))
        value_w = max(0.0, width * max(float(self._value), 0.0) / scale)
        if self._projection is not None and self._projection > self._value:
            faint = QColor(colour)
            faint.setAlpha(55)
            painter.setBrush(faint)
            painter.drawRoundedRect(QRectF(1, y, width * float(self._projection) / scale, height), 4, 4)
        if value_w > 0:
            painter.setBrush(colour)
            painter.drawRoundedRect(QRectF(1, y, max(value_w, 3.0), height), 4, 4)

        for tick in self._ticks:
            x = 1 + width * float(tick) / scale
            painter.setPen(QPen(QColor(FG_DIM), 1.2))
            painter.drawLine(int(x), 3, int(x), 19)
        if self._limit > 0:
            x = 1 + width * float(self._limit) / scale
            painter.setPen(QPen(QColor(FG), 2))
            painter.drawLine(int(x), 1, int(x), 21)
        painter.end()
