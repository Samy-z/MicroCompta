"""Line icons drawn for this app on a 24-unit grid, rendered at any size and in any colour.

Kept as code rather than files so one icon can be drawn in the colour of each state.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SHAPES = {
    # A gauge: how close turnover is to each limit.
    "limits": '<path d="M3.8 17.2a8.2 8.2 0 0 1 16.4 0"/><path d="M12 17.2l4.2-5.1"/>'
              '<circle cx="12" cy="17.2" r="1.4"/><path d="M6.4 12.6l1 .8M12 8.7v1.4M17.6 12.6l-1 .8"/>',
    # Money coming in: an arrow down into a tray.
    "payments": '<path d="M12 3.8v10.2"/><path d="M7.9 10l4.1 4.1 4.1-4.1"/>'
                '<path d="M4.2 14.8v2.9a2.3 2.3 0 0 0 2.3 2.3h11a2.3 2.3 0 0 0 2.3-2.3v-2.9"/>',
    # Money going out: an arrow up out of the tray.
    "expenses": '<path d="M12 14V3.8"/><path d="M7.9 7.9 12 3.8l4.1 4.1"/>'
                '<path d="M4.2 14.8v2.9a2.3 2.3 0 0 0 2.3 2.3h11a2.3 2.3 0 0 0 2.3-2.3v-2.9"/>',
    # Two people.
    "clients": '<circle cx="9.2" cy="8.4" r="3.3"/><path d="M3.4 19.6a5.8 5.8 0 0 1 11.6 0"/>'
               '<path d="M15.3 5.3a3.3 3.3 0 0 1 0 6.2"/><path d="M17.6 14.3a5.8 5.8 0 0 1 3 5.3"/>',
    # A page with a folded corner.
    "invoices": '<path d="M13.6 3.6H7a1.6 1.6 0 0 0-1.6 1.6v13.6A1.6 1.6 0 0 0 7 20.4h10a1.6 1.6 0 0 0 1.6-1.6V8.6z"/>'
                '<path d="M13.6 3.6v5h5"/><path d="M8.8 12.6h6.4M8.8 16.2h4.4"/>',
    # A calendar.
    "deadlines": '<rect x="3.8" y="5.4" width="16.4" height="14.8" rx="2.4"/><path d="M3.8 10h16.4"/>'
                 '<path d="M8.2 3.4v3.8M15.8 3.4v3.8"/><path d="M7.8 13.6h.01M12 13.6h.01M16.2 13.6h.01M7.8 16.8h.01M12 16.8h.01"/>',
    # A checklist.
    "annual": '<path d="M10.4 6.6h9.8M10.4 12h9.8M10.4 17.4h9.8"/>'
              '<path d="M3.8 6.6l1.5 1.5 2.6-2.8M3.8 12l1.5 1.5 2.6-2.8M3.8 17.4l1.5 1.5 2.6-2.8"/>',
    # A cloud with an arrow going up.
    "backup": '<path d="M7.2 18.6H6.8a4 4 0 0 1-.4-8 5.8 5.8 0 0 1 11.3 1.2h.2a3.4 3.4 0 0 1 0 6.8h-.6"/>'
              '<path d="M12 12.4v7.8"/><path d="M9.1 15.2 12 12.3l2.9 2.9"/>',
}

NAMES = tuple(_SHAPES)


def svg(name: str, colour: str, stroke: float = 1.8) -> bytes:
    body = _SHAPES[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{colour}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


def pixmap(name: str, colour: str, size: int) -> QPixmap:
    """Drawn for the screen's pixel ratio, so it stays sharp at 125 % or 150 %."""
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    image = QPixmap(QSize(round(size * ratio), round(size * ratio)))
    image.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, colour)))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def icon(name: str, off: str, on: str, hover: str, size: int = 22) -> QIcon:
    """off when not selected, on when selected, hover under the mouse."""
    result = QIcon()
    result.addPixmap(pixmap(name, off, size), QIcon.Normal, QIcon.Off)
    result.addPixmap(pixmap(name, on, size), QIcon.Normal, QIcon.On)
    result.addPixmap(pixmap(name, hover, size), QIcon.Active, QIcon.Off)
    result.addPixmap(pixmap(name, on, size), QIcon.Active, QIcon.On)
    return result


__all__ = ["NAMES", "icon", "pixmap", "svg"]
