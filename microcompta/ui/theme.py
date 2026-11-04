"""Dark theme: the same tokens and rules as PolyClusters, plus what this app adds."""

from __future__ import annotations

from ..config import ASSETS_DIR
from ..i18n import N_


def _asset_url(name: str) -> str:
    """Qt stylesheet url() wants forward slashes, even on Windows."""
    return (ASSETS_DIR / name).as_posix()


ARROW_UP = _asset_url("arrow_up.svg")
ARROW_DOWN = _asset_url("arrow_down.svg")
ARROW_UP_DIM = _asset_url("arrow_up_dim.svg")
ARROW_DOWN_DIM = _asset_url("arrow_down_dim.svg")
GEAR = _asset_url("gear.svg")
GEAR_HOVER = _asset_url("gear_hover.svg")

BG = "#14161c"
BG_ALT = "#1a1d25"
BG_RAISED = "#20242e"
BORDER = "#2c313d"
FG = "#d7dce5"
FG_DIM = "#8b93a3"
ACCENT = "#4f9cf9"
ACCENT_DIM = "#2d5c96"
GOOD = "#3fb950"
BAD = "#f05d5d"
WARN = "#e3b341"

LEVEL_COLOURS = {
    "ok": GOOD,
    "near": WARN,
    "warn": WARN,
    "over": BAD,
    "info": ACCENT,
    "bad": BAD,
}

# Statuses are stored as these words. Marked here so they get translated when shown.
STATUS_COLOURS = {
    N_("uploaded"): GOOD,
    N_("done"): GOOD,
    N_("issued"): GOOD,
    N_("pending"): WARN,
    N_("due soon"): WARN,
    N_("draft"): WARN,
    N_("failed"): BAD,
    N_("overdue"): BAD,
    N_("upcoming"): FG_DIM,
    N_("no date yet"): FG_DIM,
    N_("passed"): FG_DIM,
}

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {FG};
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {BG}; }}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {FG_DIM};
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 1px;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus,
QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:read-only {{ color: {FG_DIM}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url({ARROW_DOWN});
    width: 9px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}

QCalendarWidget QWidget {{ alternate-background-color: {BG_RAISED}; }}
QCalendarWidget QAbstractItemView {{
    background: {BG_ALT};
    selection-background-color: {ACCENT_DIM};
    selection-color: #ffffff;
}}
QCalendarWidget QToolButton {{ background: {BG_RAISED}; color: {FG}; padding: 3px 6px; }}
QCalendarWidget QToolButton:hover {{ background: {ACCENT_DIM}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {BG_RAISED}; }}

QPushButton {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background: #2a3040; border-color: {ACCENT_DIM}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: {FG_DIM}; background: {BG_ALT}; }}
QPushButton#primary {{
    background: {ACCENT_DIM};
    border-color: {ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT}; color: #0b0d12; }}
QPushButton#primary:disabled {{ background: {BG_ALT}; border-color: {BORDER}; color: {FG_DIM}; }}
QPushButton#danger:hover {{ background: {BAD}; color: #0b0d12; }}

QHeaderView::section {{
    background: {BG_RAISED};
    color: {FG_DIM};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 5px 6px;
    font-weight: 600;
    font-size: 11px;
}}
QHeaderView::section:hover {{ color: {FG}; }}

QTableView, QTableWidget {{
    background: {BG_ALT};
    alternate-background-color: #171a21;
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 4px;
    selection-background-color: {ACCENT_DIM};
    selection-color: #ffffff;
}}
QTableView::item {{ padding: 2px 4px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {FG_DIM};
    padding: 7px 14px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {FG}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {FG}; }}

QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3a4152; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4c5468; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3a4152; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QCheckBox {{ background: transparent; spacing: 7px; }}
QCheckBox::indicator {{
    width: 13px; height: 13px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_ALT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QStatusBar {{ background: {BG_RAISED}; border-top: 1px solid {BORDER}; color: {FG_DIM}; }}
QStatusBar QLabel {{ background: transparent; color: {FG_DIM}; }}
QToolTip {{
    background: {BG_RAISED};
    color: {FG};
    border: 1px solid {ACCENT_DIM};
    padding: 6px;
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 12px;
}}
QToolBar#brandBar {{
    background: {BG_RAISED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
    spacing: 0px;
}}
QToolBar#brandBar::separator {{ width: 0; height: 0; }}
/* Labels inside the toolbar otherwise paint their own panel background. */
QToolBar#brandBar QLabel {{ background: transparent; }}
QLabel#brandLogo {{ background: transparent; }}
QWidget#brandSpacer {{ background: transparent; }}

QWidget#dockTitle {{
    background: {BG_RAISED};
    border-bottom: 1px solid {BORDER};
}}
QLabel#dockTitleText {{
    background: transparent;
    color: {FG_DIM};
    font-weight: 600;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 1px;
}}
QPushButton#dockCollapse {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 3px;
    color: {FG_DIM};
    padding: 0;
    font-size: 11px;
}}
QPushButton#dockCollapse:hover {{ color: {FG}; border-color: {ACCENT}; background: {BG_ALT}; }}
QPushButton#dockCollapse:pressed {{ background: {ACCENT_DIM}; color: #ffffff; }}

QToolBar#controlsStripBar {{
    background: {BG_RAISED};
    border: none;
    padding: 0;
    spacing: 0;
}}
QPushButton#brandHelp {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 16px;
    margin-right: 10px;
    color: {FG_DIM};
}}
QPushButton#brandHelp:hover {{ color: {FG}; border-color: {ACCENT}; background: {BG_ALT}; }}
QPushButton#brandHelp:pressed {{ background: {ACCENT_DIM}; color: #ffffff; }}

QPushButton#brandGear {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
    margin-right: 6px;
    image: url({GEAR});
}}
QPushButton#brandGear:hover {{
    border-color: {ACCENT};
    background: {BG_ALT};
    image: url({GEAR_HOVER});
}}
QPushButton#brandGear:focus {{ border-color: {ACCENT}; }}
QPushButton#brandGear:pressed {{ background: {ACCENT_DIM}; }}

QLabel#h1 {{ font-size: 15px; font-weight: 700; }}
QLabel#h2 {{ font-size: 13px; font-weight: 700; background: transparent; }}
QLabel#dim {{ color: {FG_DIM}; }}
QLabel#metricValue {{ font-size: 18px; font-weight: 700; }}
QLabel#metricLabel {{ color: {FG_DIM}; font-size: 10px; text-transform: uppercase;
                      letter-spacing: 0.5px; }}
QFrame#card {{
    background: {BG_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
/* Labels inside a card sit on the card, not on a darker patch of the window. */
QFrame#card:focus {{ border: 1px solid {ACCENT}; }}
QFrame#card QLabel, QFrame#card QCheckBox {{ background: transparent; }}
QFrame#card QWidget#threshold {{ background: transparent; }}
QScrollArea#statRow, QWidget#statRowInner {{ background: transparent; border: none; }}
QScrollArea#page, QWidget#pageInner {{ background: {BG}; border: none; }}

QFrame#banner {{ border-radius: 5px; background: {BG_RAISED}; border: 1px solid {BORDER}; }}
QFrame#banner QLabel {{ background: transparent; }}
"""
