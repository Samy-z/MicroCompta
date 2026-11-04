"""Background workers, so the window never waits on the network."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..backup import oauth
from ..backup.queue import UploadQueue

log = logging.getLogger(__name__)


class _Cancellable(QThread):
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel


class UploadWorker(_Cancellable):
    """One pass over what is due. The QTimer in the main window decides when."""

    finished_ok = Signal(object)  # QueueReport

    def __init__(self, queue: UploadQueue, make_client: Callable[[], Any],
                 parent: QObject | None = None):
        super().__init__(parent)
        self.queue = queue
        self.make_client = make_client

    def run(self) -> None:
        try:
            self.finished_ok.emit(
                self.queue.process_due(self.make_client(), cancelled=self.is_cancelled)
            )
        except Exception:  # noqa: BLE001 - the queue is intact; report and try next tick
            log.exception("Upload pass failed")
            self.failed.emit(traceback.format_exc().strip().splitlines()[-1])


class SignInWorker(_Cancellable):
    """Waits for the browser. Samples the cancel flag so it never holds up shutdown."""

    finished_ok = Signal()

    def __init__(self, client_file: Any, token_file: Any, parent: QObject | None = None):
        super().__init__(parent)
        self.client_file = client_file
        self.token_file = token_file

    def run(self) -> None:
        try:
            client = oauth.load_client_file(self.client_file)
            oauth.run_sign_in(client, self.token_file, cancelled=self.is_cancelled)
            self.finished_ok.emit()
        except oauth.OAuthError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Sign-in failed")
            self.failed.emit(f"Sign-in failed ({type(exc).__name__}).")
