"""One running copy of the app, enforced before anything else happens.

DuckDB takes an exclusive lock on the database, so a second copy cannot work anyway.
Detecting it here means the window the user already has comes to the front instead.
"""

from __future__ import annotations

import getpass
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _socket_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - unusual environments have no login name
        user = "default"
    return f"MicroCompta-single-instance-{user}"


class SingleInstance(QObject):
    """Holds the lock for this process, and wakes the holder if someone else has it."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._name = _socket_name()
        self._server: QLocalServer | None = None
        self._on_second_launch: Any = None

    def try_acquire(self, timeout_ms: int = 300) -> bool:
        """True if we are the only instance; False if one is already running."""
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(timeout_ms):
            probe.write(b"raise")
            probe.waitForBytesWritten(timeout_ms)
            probe.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_connection)
        if not self._server.listen(self._name):
            # Let the caller start rather than block the user over a socket problem.
            self._server = None
        return True

    def set_activation_handler(self, handler: Any) -> None:
        self._on_second_launch = handler

    def _handle_connection(self) -> None:
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: conn.readAll())
        conn.disconnected.connect(conn.deleteLater)
        if self._on_second_launch is not None:
            self._on_second_launch()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._name)
            self._server = None
