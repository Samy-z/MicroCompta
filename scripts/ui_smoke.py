"""Headless UI check: build the window on fake data, drive it, save screenshots.

Uses a temporary data directory, so it never touches real records.

Run:  .venv/Scripts/python.exe scripts/ui_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_tmp = tempfile.mkdtemp(prefix="microcompta-smoke-")
os.environ["MICROCOMPTA_DATA_DIR"] = _tmp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolTip  # noqa: E402

import demo_data  # noqa: E402
from microcompta.core import clock  # noqa: E402
from microcompta.core.book import Book  # noqa: E402
from microcompta.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "screenshots"
WIDTH, HEIGHT = 1536, 824  # the machine's 1536 x 864 logical screen, less the taskbar


def grab(widget, name: str) -> None:
    SHOTS.mkdir(exist_ok=True)
    path = SHOTS / f"{name}.png"
    widget.grab().save(str(path))
    print(f"  saved {path.relative_to(ROOT)}")


def capture(win, app, folder: str = "") -> None:
    prefix = f"{folder}/" if folder else ""
    if folder:
        (SHOTS / folder).mkdir(parents=True, exist_ok=True)
    for name, panel in (
        ("01_limits", win.dashboard_panel),
        ("02_payments", win.ledger_panel),
        ("02b_expenses", win.purchases_panel),
        ("02c_clients", win.clients_panel),
        ("03_invoices", win.invoices_panel),
        ("04_deadlines", win.deadlines_panel),
        ("05_annual", win.annual_panel),
        ("06_backup", win.backup_panel),
    ):
        win.tabs.setCurrentWidget(panel)
        if panel is win.invoices_panel:
            panel.table.select_first()
        app.processEvents()
        grab(win, prefix + name)

    win.tabs.setCurrentWidget(win.dashboard_panel)
    for index, name in enumerate(("07_settings_identity", "08_settings_figures")):
        win.open_settings(index)
        app.processEvents()
        grab(win.settings_dialog, prefix + name)
    win.settings_dialog.done(0)
    app.processEvents()


def main() -> int:
    clock.today = lambda: demo_data.FAKE_TODAY  # type: ignore[assignment]
    app = QApplication(sys.argv)
    book = Book()
    demo_data.populate(book)
    book.snapshots.run()

    win = MainWindow(book)
    win.resize(WIDTH, HEIGHT)
    win.show()
    app.processEvents()

    def shoot() -> None:
        print("Capturing panels, in French (the default)...")
        capture(win, app)

        win.tabs.setCurrentWidget(win.dashboard_panel)
        win.collapse_dock()
        app.processEvents()
        grab(win, "10_dock_collapsed")
        win.expand_dock()
        app.processEvents()

        card = win.dashboard_panel.stats.cards["projection"]
        QToolTip.showText(card.mapToGlobal(card.rect().bottomLeft()), card.toolTip(), card)
        app.processEvents()
        tips = [w for w in app.topLevelWidgets() if w.objectName() == "qtooltip_label" and w.isVisible()]
        if tips:
            grab(tips[0], "11_bubble")
        QToolTip.hideText()

        print("Switching to English, live...")
        win.open_settings(0)
        panel = win.settings_panel
        panel.language.setCurrentIndex(panel.language.findData("en"))
        panel.save_profile()
        app.processEvents()
        win.settings_dialog.done(0)
        app.processEvents()
        capture(win, app, "en")

        problems = book.verify()
        print("  integrity:", "intact" if not problems else problems)
        print("  queue:", book.queue.counts())
        print("\nUI smoke test passed." if not problems else "\nUI smoke test FAILED.")
        win.quit_app()

    QTimer.singleShot(700, shoot)
    code = app.exec()
    shutil.rmtree(_tmp, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
