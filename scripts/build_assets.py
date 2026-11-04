"""Generate the logo strip and the Windows icon. An original mark, drawn with QPainter.

Produces, in assets/:

  MicroCompta_logo_icon.png          - square mark, 512px
  MicroCompta_logo_display_dark.png  - mark and wordmark for the dark brand strip
  MicroCompta.ico                    - multi-resolution Windows icon (needs Pillow)

Run:  .venv/Scripts/python.exe scripts/build_assets.py
"""

from __future__ import annotations

import os
import sys
from math import cos, pi, sin
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
)

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def gear_svg(colour: str, teeth: int = 8) -> str:
    """An eight-toothed gear with a hole, as one even-odd path."""
    outer, root, hole, centre = 11.0, 8.2, 3.4, 12.0
    # Each tooth is four corners: up the left flank, across the top, down the right flank.
    tooth_half, flank_half = 0.26 * pi / teeth * 2, 0.40 * pi / teeth * 2
    points = []
    for i in range(teeth):
        angle = 2 * pi * i / teeth
        for radius, offset in ((root, -flank_half), (outer, -tooth_half),
                               (outer, tooth_half), (root, flank_half)):
            points.append((centre + radius * cos(angle + offset), centre + radius * sin(angle + offset)))
    body = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"
    circle = (f"M{centre + hole} {centre} A{hole} {hole} 0 1 0 {centre - hole} {centre} "
              f"A{hole} {hole} 0 1 0 {centre + hole} {centre} Z")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">\n'
        f'  <path fill-rule="evenodd" fill="{colour}" stroke="{colour}" stroke-width="0.8" '
        f'stroke-linejoin="round" d="{body} {circle}"/>\n</svg>\n'
    )


def draw_mark(painter: QPainter, x: float, y: float, side: float) -> None:
    """A ledger page with three rising bars. Stays readable at 16px."""
    s = side / 100.0
    painter.save()
    painter.translate(x, y)
    painter.scale(s, s)

    page = QPainterPath()
    page.addRoundedRect(QRectF(4, 4, 92, 92), 20, 20)
    fill = QLinearGradient(QPointF(0, 0), QPointF(100, 100))
    fill.setColorAt(0.0, QColor("#2d5c96"))
    fill.setColorAt(1.0, QColor("#17305a"))
    painter.fillPath(page, fill)
    painter.setPen(QPen(QColor("#4f9cf9"), 2.6))
    painter.drawPath(page)

    painter.setPen(Qt.NoPen)
    bars = [(22, 54, 34, "#4f9cf9"), (43, 40, 48, "#5ad1c9"), (64, 22, 66, "#3fb950")]
    for left, top, height, colour in bars:
        painter.setBrush(QColor(colour))
        painter.drawRoundedRect(QRectF(left, top, 15, height), 3.5, 3.5)

    painter.setPen(QPen(QColor("#d7dce5"), 3.2, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(17, 91 - 3), QPointF(83, 91 - 3))
    painter.restore()


def build_icon() -> QImage:
    image = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    draw_mark(painter, 0, 0, 512)
    painter.end()
    return image


def build_display() -> QImage:
    """Twice the strip's 68px height, so it stays sharp on a scaled display."""
    height = 136
    font = QFont("Segoe UI", 1)
    font.setPixelSize(76)
    font.setWeight(QFont.DemiBold)
    font.setLetterSpacing(QFont.PercentageSpacing, 98)

    probe = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(probe)
    painter.setFont(font)
    fm = painter.fontMetrics()
    first, second = "Micro", "Compta"
    first_w = fm.horizontalAdvance(first)
    second_w = fm.horizontalAdvance(second)
    ascent, descent = fm.ascent(), fm.descent()
    painter.end()

    mark = 112
    gap = 24
    width = mark + gap + first_w + second_w + 12
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    draw_mark(painter, 0, (height - mark) / 2, mark)

    painter.setFont(font)
    baseline = (height + ascent - descent) / 2
    painter.setPen(QColor("#f2f5fa"))
    painter.drawText(QPointF(mark + gap, baseline), first)

    gradient = QLinearGradient(QPointF(mark + gap + first_w, 0), QPointF(width, 0))
    gradient.setColorAt(0.0, QColor("#4f9cf9"))
    gradient.setColorAt(1.0, QColor("#5ad1c9"))
    painter.setPen(QPen(gradient, 1))
    painter.drawText(QPointF(mark + gap + first_w, baseline), second)
    painter.end()
    return image


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - fonts need a running GUI application
    ASSETS.mkdir(exist_ok=True)
    icon_path = ASSETS / "MicroCompta_logo_icon.png"
    display_path = ASSETS / "MicroCompta_logo_display_dark.png"
    build_icon().save(str(icon_path))
    build_display().save(str(display_path))
    (ASSETS / "gear.svg").write_text(gear_svg("#8b93a3"), encoding="utf-8", newline="\n")
    (ASSETS / "gear_hover.svg").write_text(gear_svg("#d7dce5"), encoding="utf-8", newline="\n")
    print("  gear.svg, gear_hover.svg")
    print(f"  {icon_path.name}")
    print(f"  {display_path.name}")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed, so the .ico was not built "
              "(pip install -r requirements-dev.txt).")
        return 1
    Image.open(icon_path).convert("RGBA").save(
        ASSETS / "MicroCompta.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES]
    )
    print("  MicroCompta.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
