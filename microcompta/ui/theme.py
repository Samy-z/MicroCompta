"""The look of the app, built from tokens: every colour, radius and type size is named by its role.

Dark, in deep greys with a hint of blue rather than black, with one accent for what matters
most. tests/test_theme.py checks the text colours against WCAG 2.2 contrast on every surface,
so a change here can't quietly make something hard to read.
"""

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
CHECK = _asset_url("check.svg")

# -- surfaces, darkest first ----------------------------------------------------
SURFACE_0 = "#0d1016"      # the window and the pages
SURFACE_1 = "#141820"      # chrome (top bar, navigation), cards, panels
SURFACE_2 = "#1b2029"      # fields, buttons, table headers
SURFACE_3 = "#242a35"      # hover
LINE = "#272e3a"           # hairlines between things
LINE_STRONG = "#343c4b"    # edges that must be seen: fields, buttons
LINE_HOVER = "#46506a"

# -- text -------------------------------------------------------------------------
TEXT = "#e9ecf2"           # what you read
TEXT_2 = "#b1b8c6"         # secondary: labels, values that support a headline
TEXT_3 = "#8f98a8"         # tertiary: captions, hints, explanations

# -- one accent ---------------------------------------------------------------------
ACCENT = "#79b0ff"         # as text, icons and the focus ring
ACCENT_FILL = "#2f6fdf"    # the primary button: white text on it is 4.7:1
ACCENT_FILL_HOVER = "#2a63c9"
ON_ACCENT = "#ffffff"

# -- meaning ----------------------------------------------------------------------
GOOD = "#4cc276"
WARN = "#e8b84a"
BAD = "#f47272"
ON_STATUS = SURFACE_0      # text on a solid status colour, such as a badge

# -- shape and type ---------------------------------------------------------------
RADIUS_CONTROL = 8
RADIUS_CARD = 12
FONT_TEXT = '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif'
FONT_DISPLAY = '"Segoe UI Variable Display Semibold", "Segoe UI Semibold", "Inter", sans-serif'
FONT_SIZE = 12


def mix(colour: str, base: str, alpha: float) -> str:
    """colour laid over base at this opacity, as a plain hex colour."""
    top = [int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    under = [int(base.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(t * alpha + u * (1 - alpha)):02x}" for t, u in zip(top, under))


def soft(colour: str, base: str = SURFACE_1) -> str:
    """The tinted background that goes with a status or accent colour."""
    return mix(colour, base, 0.16)


SELECTION = mix(ACCENT, SURFACE_2, 0.18)

# Older names, still used by the widgets that paint by hand and by the table model.
BG = SURFACE_0
BG_ALT = SURFACE_2
BG_RAISED = SURFACE_1
BORDER = LINE_STRONG
FG = TEXT
FG_DIM = TEXT_3
ACCENT_DIM = ACCENT_FILL

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
/* Only windows, cards and fields paint a background. Everything else lets the surface
   underneath show, so a label never sits on a darker patch of its own. */
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {FONT_TEXT};
    font-size: {FONT_SIZE}px;
}}
QMainWindow, QDialog, QMessageBox {{ background: {SURFACE_0}; }}
QMainWindow::separator {{ background: {LINE}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {ACCENT}; }}

QToolTip {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {LINE_STRONG};
    border-radius: 8px;
    padding: 7px 9px;
    font-family: {FONT_TEXT};
    font-size: 12px;
}}

/* -- type -------------------------------------------------------------------------- */
QLabel#h1 {{ font-family: {FONT_DISPLAY}; font-size: 22px; color: {TEXT}; }}
QLabel#h2 {{ font-family: {FONT_DISPLAY}; font-size: 15px; color: {TEXT}; }}
QLabel#dim {{ color: {TEXT_3}; }}
QLabel#eyebrow {{
    color: {TEXT_3}; font-size: 11px; font-weight: 600; letter-spacing: 0.6px;
    text-transform: uppercase;
}}

/* -- containers ---------------------------------------------------------------------- */
QGroupBox {{
    background: {SURFACE_1};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
    margin-top: 20px;
    padding: 8px 8px 6px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 6px;
    padding: 0 2px 4px 2px;
    color: {TEXT_3};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}
QFrame#card, QFrame#tile {{
    background: {SURFACE_1};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#card:focus, QFrame#tile:focus, QFrame#subMetric:focus {{ border: 1px solid {ACCENT}; }}
QFrame#subMetric {{ border: 1px solid transparent; border-radius: 8px; }}
QFrame#banner {{ border-radius: 10px; background: {SURFACE_1}; border: 1px solid {LINE}; }}
QScrollArea#statRow, QWidget#statRowInner, QScrollArea#page, QWidget#pageInner {{ border: none; }}
QAbstractScrollArea {{ border: none; }}

/* -- numbers ------------------------------------------------------------------------- */
QLabel#metricValue {{ font-family: {FONT_DISPLAY}; font-size: 19px; }}
QLabel#metricLabel {{
    color: {TEXT_3}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
    text-transform: uppercase;
}}
QLabel#heroValue {{ font-family: {FONT_DISPLAY}; font-size: 34px; }}
QLabel#tileValue {{ font-family: {FONT_DISPLAY}; font-size: 24px; }}
QLabel#subValue {{ font-family: {FONT_DISPLAY}; font-size: 15px; }}
QLabel#tileNote {{ color: {TEXT_2}; }}

/* -- fields -------------------------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {SURFACE_2};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    padding: 4px 8px;
    selection-background-color: {SELECTION};
    selection-color: {TEXT};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QDateEdit:hover,
QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {LINE_HOVER}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:read-only {{ color: {TEXT_2}; background: {SURFACE_1}; border-color: {LINE}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {{ color: {TEXT_3}; background: {SURFACE_1}; border-color: {LINE}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    border: none; background: transparent; width: 18px; subcontrol-origin: border;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {SURFACE_3}; border-radius: 4px; }}
QAbstractSpinBox::up-arrow {{ image: url({ARROW_UP}); width: 9px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url({ARROW_DOWN}); width: 9px; height: 6px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({ARROW_DOWN}); width: 9px; height: 6px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2};
    border: 1px solid {LINE_STRONG};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {SELECTION};
    selection-color: {TEXT};
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {LINE_HOVER};
    border-radius: 5px;
    background: {SURFACE_2};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT_FILL}; border-color: {ACCENT_FILL}; image: url({CHECK}); }}
QCheckBox:focus {{ color: {ACCENT}; }}

QCalendarWidget QWidget {{ alternate-background-color: {SURFACE_2}; }}
QCalendarWidget QAbstractItemView {{
    background: {SURFACE_1};
    selection-background-color: {ACCENT_FILL};
    selection-color: {ON_ACCENT};
}}
QCalendarWidget QToolButton {{ background: {SURFACE_2}; color: {TEXT}; padding: 4px 8px; border-radius: 6px; }}
QCalendarWidget QToolButton:hover {{ background: {SURFACE_3}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {SURFACE_2}; }}

/* -- buttons ------------------------------------------------------------------------- */
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {LINE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_1}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_3}; background: {SURFACE_1}; border-color: {LINE}; }}
QPushButton#primary {{
    background: {ACCENT_FILL};
    border-color: {ACCENT_FILL};
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_FILL_HOVER}; border-color: {ACCENT}; }}
QPushButton#primary:focus {{ border-color: {ACCENT}; }}
QPushButton#primary:disabled {{ background: {SURFACE_2}; border-color: {LINE}; color: {TEXT_3}; }}
QPushButton#danger {{ color: {BAD}; }}
QPushButton#danger:hover {{ background: {soft(BAD, SURFACE_2)}; border-color: {BAD}; }}
QPushButton#danger:disabled {{ color: {TEXT_3}; }}

/* -- tables -------------------------------------------------------------------------- */
QTableView, QTableWidget {{
    background: {SURFACE_1};
    alternate-background-color: {SURFACE_1};
    border: 1px solid {LINE};
    border-radius: 10px;
    gridline-color: {LINE};
    selection-background-color: {SELECTION};
    selection-color: {TEXT};
    font-size: 12px;
    outline: none;
}}
QTableView::item {{ padding: 0 5px; border-bottom: 1px solid {LINE}; }}
QTableView::item:hover {{ background: {SURFACE_2}; }}
QTableView::item:selected {{ background: {SELECTION}; color: {TEXT}; }}
QHeaderView {{ background: {SURFACE_1}; border: none; }}
QHeaderView::section {{
    background: {SURFACE_1};
    color: {TEXT_3};
    border: none;
    border-bottom: 1px solid {LINE_STRONG};
    padding: 7px 5px;
    font-size: 11px;
    font-weight: 600;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}
QTableCornerButton::section {{ background: {SURFACE_1}; border: none; }}

/* -- tabs (Settings) ---------------------------------------------------------------- */
QTabWidget::pane {{ border: none; top: 4px; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_3};
    padding: 7px 14px;
    margin-right: 4px;
    border-radius: 8px;
}}
QTabBar::tab:selected {{ color: {TEXT}; background: {SURFACE_2}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* -- scroll bars --------------------------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_STRONG}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {LINE_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE_STRONG}; border-radius: 3px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {LINE_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 12px; }}
QSplitter::handle:vertical {{ height: 12px; }}

QMenu {{ background: {SURFACE_2}; border: 1px solid {LINE_STRONG}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}

QStatusBar {{ background: {SURFACE_1}; border-top: 1px solid {LINE}; color: {TEXT_3}; }}
QStatusBar QLabel {{ color: {TEXT_3}; padding: 0 6px; }}

/* -- chrome: top bar and navigation ---------------------------------------------------- */
QToolBar#brandBar {{
    background: {SURFACE_1};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 2px 6px;
    spacing: 0px;
}}
QToolBar#brandBar::separator {{ width: 0; height: 0; }}
QPushButton#brandHelp {{
    background: transparent;
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    padding: 5px 16px;
    margin-right: 8px;
    color: {TEXT_2};
}}
QPushButton#brandHelp:hover {{ color: {TEXT}; border-color: {LINE_HOVER}; background: {SURFACE_2}; }}
QPushButton#brandHelp:focus {{ border-color: {ACCENT}; }}
QPushButton#brandGear {{
    background: transparent;
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    padding: 5px;
    margin-right: 6px;
    image: url({GEAR});
}}
QPushButton#brandGear:hover {{ border-color: {LINE_HOVER}; background: {SURFACE_2}; image: url({GEAR_HOVER}); }}
QPushButton#brandGear:focus {{ border-color: {ACCENT}; }}

QToolBar#navBar {{
    background: {SURFACE_1};
    border: none;
    border-right: 1px solid {LINE};
    padding: 0;
    spacing: 0;
}}
QToolButton#navItem {{
    background: transparent;
    color: {TEXT_3};
    border: none;
    border-radius: 10px;
    padding: 7px 4px 6px 4px;
    font-size: 11px;
}}
QToolButton#navItem:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QToolButton#navItem:checked {{ background: {soft(ACCENT)}; color: {TEXT}; font-weight: 600; }}
QToolButton#navItem:focus {{ border: 1px solid {ACCENT}; }}

/* -- the payment panel ---------------------------------------------------------------- */
QWidget#dockTitle {{ border-bottom: 1px solid {LINE}; }}
QLabel#dockTitleText {{ font-family: {FONT_DISPLAY}; font-size: 15px; color: {TEXT}; }}
QPushButton#dockCollapse {{
    background: transparent;
    border: 1px solid {LINE_STRONG};
    border-radius: 6px;
    color: {TEXT_3};
    padding: 0;
    font-size: 11px;
}}
QPushButton#dockCollapse:hover {{ color: {TEXT}; border-color: {LINE_HOVER}; background: {SURFACE_2}; }}
QPushButton#dockCollapse:focus {{ border-color: {ACCENT}; }}
QToolBar#controlsStripBar {{ background: {SURFACE_1}; border: none; padding: 0; spacing: 0; }}
QPushButton#addClient {{
    padding: 0;
    color: {ACCENT};
    font-size: 18px;
    font-weight: 600;
}}
QPushButton#addClient:hover {{ background: {ACCENT_FILL}; border-color: {ACCENT_FILL}; color: {ON_ACCENT}; }}
QPushButton#addClient:focus {{ border-color: {ACCENT}; }}
"""
