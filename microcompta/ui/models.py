"""A sortable, formatted Qt table model over a list of dicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..core.money import fmt_money
from .theme import BAD, FG, FG_DIM, STATUS_COLOURS

_NUMERIC = ("eur", "money", "rate", "pct", "int", "bytes", "days", "qty")


@dataclass(frozen=True)
class Col:
    """Presentation spec for one column."""

    key: str
    title: str
    fmt: str = "text"     # text|eur|money|rate|pct|date|datetime|int|bytes|days|status|bool
    width: int = 100
    tip: str = ""
    currency_key: str = ""
    sort_key: str = ""    # sort on this field instead, when the shown text wouldn't sort


def local_time(value: datetime) -> str:
    """Stored in UTC, shown in local time."""
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def fmt_value(value: Any, fmt: str, currency: str = "EUR") -> str:
    if value is None or value == "":
        return "—"
    if fmt == "eur":
        return fmt_money(Decimal(value), "EUR")
    if fmt == "money":
        return fmt_money(Decimal(value), currency)
    if fmt == "rate":
        text = f"{Decimal(value):.6f}".rstrip("0")
        return text + "0" if text.endswith(".") else text
    if fmt == "pct":
        return f"{Decimal(value) * 100:.1f}%"
    if fmt == "date":
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if fmt == "datetime":
        return local_time(value) if isinstance(value, datetime) else str(value)
    if fmt == "qty":
        return f"{Decimal(value):f}".rstrip("0").rstrip(".")
    if fmt == "int":
        return f"{int(value):,}"
    if fmt == "days":
        n = int(value)
        return "today" if n == 0 else (f"{n} d" if n > 0 else f"{-n} d late")
    if fmt == "bytes":
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
            size /= 1024
    if fmt == "bool":
        return "yes" if value else "—"
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
            return f"{text}\n{spec.tip}" if spec.tip else text
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
            return spec.tip or spec.title
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
