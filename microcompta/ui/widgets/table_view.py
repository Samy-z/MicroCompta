"""A table with a filter box, a row count and its own action buttons."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

from ..models import Col, RowsModel, SortProxy, fmt_value


class DataTable(QWidget):
    row_selected = Signal(object)    # dict or None
    row_activated = Signal(object)   # double-click

    def __init__(self, columns: list[Col], *, title: str = "", key: str = "",
                 toolbar: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._columns = columns
        self._key = key
        self._wrap = False

        self.model = RowsModel(columns, self)
        self.proxy = SortProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        # setSortingEnabled sorts straight away on column 0, descending. Each panel supplies
        # its rows in the order that means something; a click on a header re-sorts them.
        self.table.sortByColumn(-1, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(23)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setSortIndicatorShown(True)
        self.table.doubleClicked.connect(self._on_activated)
        for i, spec in enumerate(columns):
            self.table.setColumnWidth(i, spec.width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.bar = QHBoxLayout()
        self.bar.setSpacing(6)
        self.search: QLineEdit | None = None
        self.count_label: QLabel | None = None
        if toolbar:
            if title:
                label = QLabel(title)
                label.setObjectName("h1")
                self.bar.addWidget(label)
            self.search = QLineEdit()
            self.search.setPlaceholderText("Filter rows…")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self._on_search)
            self.bar.addWidget(self.search, 1)
            self.count_label = QLabel("0 rows")
            self.count_label.setObjectName("dim")
            self.bar.addWidget(self.count_label)
            layout.addLayout(self.bar)
        layout.addWidget(self.table, 1)

        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        copy = QAction("Copy", self)
        copy.setShortcut(QKeySequence.Copy)
        copy.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy.triggered.connect(self.copy_selection)
        self.addAction(copy)

    # -- toolbar ------------------------------------------------------------
    def add_button(self, text: str, slot: Callable[[], Any], *, primary: bool = False,
                   danger: bool = False, tip: str = "") -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        if danger:
            button.setObjectName("danger")
        if tip:
            button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False: slot())
        self.bar.addWidget(button)
        return button

    def add_widget(self, widget: QWidget) -> None:
        self.bar.addWidget(widget)

    # -- data ---------------------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Replace the rows, keeping the selected one selected where it still exists."""
        selected = self.current_row()
        keep = selected.get(self._key) if selected and self._key else None
        self.model.set_rows(rows)
        self._update_count()
        if keep is not None:
            self.select_key(keep)
        if self._wrap:
            self.table.resizeRowsToContents()

    def set_wrapped(self) -> None:
        """For a short table of sentences meant to be read, not skimmed."""
        self._wrap = True
        self.table.setWordWrap(True)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_a: self.table.resizeRowsToContents()
        )

    def select_key(self, value: Any) -> None:
        for r in range(self.proxy.rowCount()):
            row = self.model.rows[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
            if row.get(self._key) == value:
                self.table.selectRow(r)
                return

    def select_first(self) -> None:
        if self.proxy.rowCount():
            self.table.selectRow(0)

    def current_row(self) -> dict[str, Any] | None:
        index = self.table.selectionModel().currentIndex()
        if not index.isValid() or not self.table.selectionModel().hasSelection():
            return None
        row = self.proxy.mapToSource(index).row()
        return self.model.rows[row] if 0 <= row < len(self.model.rows) else None

    # -- interaction --------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self.proxy.set_search(text)
        self._update_count()

    def _update_count(self) -> None:
        if self.count_label is not None:
            n = self.proxy.rowCount()
            self.count_label.setText(f"{n:,} row{'' if n == 1 else 's'}")

    def _on_selection(self, *_args: Any) -> None:
        self.row_selected.emit(self.current_row())

    def _on_activated(self, *_args: Any) -> None:
        row = self.current_row()
        if row is not None:
            self.row_activated.emit(row)

    def copy_selection(self) -> None:
        row = self.current_row()
        if row is None:
            return
        cells = [
            fmt_value(row.get(c.key), c.fmt, row.get(c.currency_key, "EUR") if c.currency_key else "EUR")
            for c in self._columns
        ]
        QApplication.clipboard().setText("\t".join(cells))
