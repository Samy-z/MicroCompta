"""A sortable, formatted Qt table model over a list of dicts."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..i18n import fmt_date, fmt_datetime, fmt_money, fmt_number, fmt_percent, fmt_rate, tr
from .theme import BAD, FG, FG_DIM, STATUS_COLOURS

_NUMERIC = ("eur", "money", "rate", "pct", "int", "bytes", "days", "qty")


# Above this length a bubble wraps, at a width that keeps its lines comfortable to read.
_ONE_LINE_CHARS = 60
_BUBBLE_WIDTH_PX = 340


def wrap_tip(text: str) -> str:
    """Rich text, because Qt only wraps a tooltip that is rich text, and left to itself it
    picks a narrow column: 135 px for a two-sentence bubble (measured)."""
    body = html.escape(text, quote=False).replace("\n", "<br>")
    if len(text) <= _ONE_LINE_CHARS and "\n" not in text:
        return f"<qt><span style='white-space:nowrap'>{body}</span></qt>"
    return f"<qt><table width='{_BUBBLE_WIDTH_PX}'><tr><td>{body}</td></tr></table></qt>"


@dataclass(frozen=True)
class Col:
    """Presentation spec for one column. Build these at runtime, so they follow the language."""

    key: str
    title: str
    fmt: str = "text"     # text|eur|money|rate|pct|date|datetime|int|bytes|days|status|bool|qty
    width: int = 100
    tip: str = ""
    currency_key: str = ""
    sort_key: str = ""    # sort on this field instead, when the shown text wouldn't sort


def local_time(value: datetime) -> str:
    """Stored in UTC, shown in local time."""
    return fmt_datetime(value.replace(tzinfo=timezone.utc).astimezone())


def fmt_value(value: Any, fmt: str, currency: str = "EUR") -> str:
    if value is None or value == "":
        return "—"
    if fmt == "eur":
        return fmt_money(Decimal(value), "EUR")
    if fmt == "money":
        return fmt_money(Decimal(value), currency)
    if fmt == "rate":
        return fmt_rate(value)
    if fmt == "pct":
        return fmt_percent(value)
    if fmt == "date":
        return fmt_date(value) if isinstance(value, (date, datetime)) else str(value)
    if fmt == "datetime":
        return local_time(value) if isinstance(value, datetime) else str(value)
    if fmt == "qty":
        decimals = len(f"{Decimal(value):f}".rstrip("0").partition(".")[2])
        return fmt_number(value, decimals)
    if fmt == "int":
        return fmt_number(int(value), 0)
    if fmt == "days":
        n = int(value)
        if n == 0:
            return tr("today")
        return tr("{days} d", days=n) if n > 0 else tr("{days} d late", days=-n)
    if fmt == "bytes":
        size = float(value)
        for unit in (tr("B"), tr("KB"), tr("MB"), tr("GB")):
            if size < 1024 or unit == tr("GB"):
                return f"{fmt_number(size, 0 if unit == tr('B') else 1)} {unit}"
            size /= 1024
    if fmt == "bool":
        return tr("yes") if value else "—"
    if fmt == "status":
        return tr(str(value))
    return str(value)


def _sort_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).lower()


class RowsModel(QAbstractTableModel):
    def __init__(self, columns: list[Col], parent: Any = None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict[str, Any]] = []

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        spec = self.columns[index.column()]
        row = self.rows[index.row()]
        value = row.get(spec.key)
        currency = row.get(spec.currency_key, "EUR") if spec.currency_key else "EUR"

        if role == Qt.DisplayRole:
            return fmt_value(value, spec.fmt, currency)
        if role == Qt.ToolTipRole:
            text = fmt_value(value, spec.fmt, currency)
            return wrap_tip(f"{text}\n{spec.tip}" if spec.tip else text)
        if role == Qt.TextAlignmentRole:
            side = Qt.AlignRight if spec.fmt in _NUMERIC else Qt.AlignLeft
            return int(Qt.AlignVCenter | side)
        if role == Qt.ForegroundRole:
            if spec.fmt == "status":
                return QColor(STATUS_COLOURS.get(str(value), FG))
            if row.get("_dim"):
                return QColor(FG_DIM)
            if isinstance(value, Decimal) and value < 0:
                return QColor(BAD)
            if value is None or value == "":
                return QColor(FG_DIM)
            return QColor(FG)
        if role == Qt.UserRole:
            return _sort_value(row.get(spec.sort_key) if spec.sort_key else value)
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if orientation != Qt.Horizontal or not 0 <= section < len(self.columns):
            return None
        spec = self.columns[section]
        if role == Qt.DisplayRole:
            return spec.title
        if role == Qt.ToolTipRole:
            return wrap_tip(spec.tip or spec.title)
        return None


class SortProxy(QSortFilterProxyModel):
    """Sorts on the raw value and filters across all columns."""

    def __init__(self, parent: Any = None):
        super().__init__(parent)
        self.setSortRole(Qt.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._needle = ""

    def set_search(self, text: str) -> None:
        self._needle = (text or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:  # noqa: N802
        if not self._needle:
            return True
        model = self.sourceModel()
        return any(
            self._needle in str(model.data(model.index(row, col, parent), Qt.DisplayRole) or "").lower()
            for col in range(model.columnCount())
        )
