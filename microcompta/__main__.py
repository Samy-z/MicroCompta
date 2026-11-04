"""Application entry point: ``python -m microcompta``."""

from __future__ import annotations

# First, before anything can build an SSL context. This machine's TLS is intercepted:
# Python's own CA bundle fails every HTTPS call, and the OS store has the right root.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # the app still runs offline; uploads will report the failure
    pass

import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from typing import Any  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from .config import APP_ICO, APP_NAME, LOGO_ICON, WINDOWS_APP_ID, logs_dir  # noqa: E402
from .core.book import Book  # noqa: E402
from .i18n import DEFAULT_LANGUAGE, tr  # noqa: E402
from .ui.language import apply_language  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402
from .ui.single_instance import SingleInstance  # noqa: E402

_SECRET_PATTERNS = (
    re.compile(r"ya29\.[\w\-.]+"),
    re.compile(r"1//[\w\-.]+"),
    re.compile(r"GOCSPX-[\w\-]+"),
    re.compile(r"(?i)(access_token|refresh_token|client_secret|authorization|code)[\"']?\s*[:=]\s*[\"']?[^\s\"',&]+"),
    re.compile(r"(?i)bearer\s+[\w\-.]+"),
    re.compile(r"upload_id=[\w\-.]+"),
)


class _Redact(logging.Filter):
    """A second line of defence. The code doesn't log secrets, and this strips any that slip."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub("[redacted]", message)
        record.msg = message
        record.args = ()
        return True


def _setup_logging() -> None:
    handler = RotatingFileHandler(
        logs_dir() / "microcompta.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_Redact())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # At debug level these print full URLs, which for uploads include the session id.
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _excepthook(kind: Any, value: Any, tb: Any) -> None:
    """Under pythonw there's no console, so an unhandled error would just vanish."""
    logging.getLogger(__name__).critical(
        "Unhandled error: %s", "".join(traceback.format_exception(kind, value, tb))
    )
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None, tr("{app}: unexpected error", app=APP_NAME),
            tr("{error}\n\nYour records are safe: each one is committed when it's made. "
               "The details are in the log file.", error=value),
        )


def _claim_windows_taskbar_identity() -> None:
    """Without our own AppUserModelID, the taskbar shows the generic Python icon."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:  # noqa: BLE001 - cosmetic only, never fatal
        pass


def _bring_to_front(window: Any) -> None:
    window.setWindowState((window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    window.show()
    window.raise_()
    window.activateWindow()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _setup_logging()
    sys.excepthook = _excepthook
    _claim_windows_taskbar_identity()

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    # Closing the window can mean "keep running in the tray".
    app.setQuitOnLastWindowClosed(False)
    # Until the records are open and the saved choice can be read.
    apply_language(DEFAULT_LANGUAGE)

    icon_path = APP_ICO if APP_ICO.exists() else LOGO_ICON
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Before anything opens the database: DuckDB takes an exclusive lock.
    guard = SingleInstance()
    if not guard.try_acquire():
        return 0

    try:
        book = Book()
    except Exception as exc:  # noqa: BLE001 - no console under pythonw, so say it here
        logging.getLogger(__name__).exception("Could not open the database")
        QMessageBox.critical(
            None, tr("{app} cannot start", app=APP_NAME),
            tr("Could not open the records.\n\n{error}", error=exc),
        )
        return 1

    window = MainWindow(book)
    guard.setParent(window)
    guard.set_activation_handler(lambda: _bring_to_front(window))
    window.showMaximized()
    try:
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
