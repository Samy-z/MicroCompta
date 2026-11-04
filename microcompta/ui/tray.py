"""Notification-area icon: deadline reminders, backup state, and a way back in.

Deadline reminders only fire while the process runs, so by default closing the window
keeps the app here. Quit from this menu to really stop it.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..i18n import tr


class TrayController(QObject):
    show_requested = Signal()
    upload_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(icon, parent)
        self.tray.setToolTip("MicroCompta")

        menu = QMenu()
        header = QAction("MicroCompta", menu)
        header.setEnabled(False)
        menu.addAction(header)

        self.status_action = QAction("", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        self.show_action = QAction(menu)
        self.show_action.triggered.connect(self.show_requested.emit)
        menu.addAction(self.show_action)

        self.upload_action = QAction(menu)
        self.upload_action.triggered.connect(self.upload_requested.emit)
        menu.addAction(self.upload_action)
        menu.addSeparator()

        self.quit_action = QAction(menu)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(self.quit_action)

        # Kept on self: a menu parented to nothing would be collected when this returns,
        # leaving an icon whose right-click does nothing.
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activated)
        self.retranslate()

    def retranslate(self) -> None:
        self.show_action.setText(tr("Show window"))
        self.upload_action.setText(tr("Upload to Drive now"))
        self.quit_action.setText(tr("Quit MicroCompta"))

    def _activated(self, reason: Any) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_status(self, text: str) -> None:
        self.status_action.setText(text)
        self.tray.setToolTip(f"MicroCompta: {text}")

    def notify(self, title: str, message: str) -> None:
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, self.tray.icon(), 8000)
