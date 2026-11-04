"""Google Drive over plain REST through ``requests``.

Not google-api-python-client: requests is the smaller dependency and works with
truststore on this machine. Measured 2026-11-04 against www.googleapis.com, where every
client failed without truststore and worked with it (requests, httpx and httplib2).

Two guards are enforced in one place rather than trusted to callers. The verbs are
GET, POST and PUT only, so this client cannot delete or trash anything. The hosts are
Google's API hosts only, which is the whole of the app's network access.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,size,md5Checksum,sha256Checksum,trashed"

ALLOWED_METHODS = frozenset({"GET", "POST", "PUT"})
_TRANSIENT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "backendError"})


class DriveError(Exception):
    """Base class for anything that stops an upload."""


class TransientDriveError(DriveError):
    """Offline, or Google is busy. Try again later."""


class PermanentDriveError(DriveError):
    """Retrying the same way won't help on its own."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthRequired(DriveError):
    """The owner needs to sign in again in the browser."""


class ForbiddenRequest(DriveError):
    """The client was asked to do something it must never do."""


@dataclass(frozen=True)
class RemoteFile:
    id: str
    name: str = ""
    md5: str | None = None
    sha256: str | None = None
    size: int | None = None


class DriveClient(Protocol):
    def find_folder(self, name: str, parent_id: str | None) -> str | None: ...
    def create_folder(self, name: str, parent_id: str | None) -> str: ...
    def find_files(self, name: str, parent_id: str) -> list[RemoteFile]: ...
    def upload(self, path: Path, name: str, parent_id: str) -> RemoteFile: ...
    def metadata(self, file_id: str) -> RemoteFile: ...


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _remote(payload: dict[str, Any]) -> RemoteFile:
    size = payload.get("size")
    return RemoteFile(
        id=payload["id"],
        name=payload.get("name", ""),
        md5=payload.get("md5Checksum"),
        sha256=payload.get("sha256Checksum"),
        size=int(size) if size is not None else None,
    )


def _error_info(response: Any) -> tuple[str, str]:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return "", f"HTTP {response.status_code}"
    if not isinstance(error, dict):
        return "", str(error)[:200]
    reasons = error.get("errors") or [{}]
    return reasons[0].get("reason", ""), str(error.get("message", ""))[:200]


class RestDriveClient:
    TIMEOUT = (15, 300)

    def __init__(self, tokens: Any, session: Any = None):
        self.tokens = tokens
        self.session = session or requests.Session()

    # -- the only route to the network --------------------------------------
    @staticmethod
    def _guard(method: str, url: str) -> None:
        if method.upper() not in ALLOWED_METHODS:
            raise ForbiddenRequest(f"Method {method} is not allowed: nothing is ever deleted.")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host.endswith(".googleapis.com"):
            raise ForbiddenRequest("Only Google's API hosts over HTTPS are allowed.")

    def _request(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, json_body: Any = None,
                 data: Any = None) -> Any:
        self._guard(method, url)
        for attempt in (1, 2):
            sent = dict(headers or {})
            sent["Authorization"] = f"Bearer {self.tokens.access_token()}"
            try:
                response = self.session.request(
                    method, url, params=params, headers=sent, json=json_body, data=data,
                    timeout=self.TIMEOUT, allow_redirects=False,
                )
            except requests.RequestException as exc:
                # The type only: the message of a connection error can carry the URL.
                raise TransientDriveError(
                    f"No connection to Google Drive ({type(exc).__name__})."
                ) from None
            if response.status_code == 401 and attempt == 1:
                self.tokens.drop_access_token()
                if hasattr(data, "seek"):
                    data.seek(0)
                continue
            return response
        return response

    def _checked(self, response: Any, what: str) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            return response
        reason, message = _error_info(response)
        log.warning("Drive %s failed: HTTP %s %s", what, status, reason)
        detail = f"{what}: HTTP {status} {message}".strip()
        if status == 401:
            raise AuthRequired("Google refused the sign-in. Reconnect Google Drive.")
        if status == 429 or status >= 500 or reason in _TRANSIENT_REASONS:
            raise TransientDriveError(detail)
        raise PermanentDriveError(detail, status=status)

    # -- folders ------------------------------------------------------------
    def find_folder(self, name: str, parent_id: str | None) -> str | None:
        parent = _quote(parent_id) if parent_id else "root"
        response = self._checked(self._request("GET", API_URL, params={
            "q": f"name = '{_quote(name)}' and mimeType = '{FOLDER_MIME}' "
                 f"and '{parent}' in parents and trashed = false",
            "fields": "files(id)",
            "pageSize": 1,
        }), "folder lookup")
        files = response.json().get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name: str, parent_id: str | None) -> str:
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            body["parents"] = [parent_id]
        response = self._checked(
            self._request("POST", API_URL, params={"fields": "id"}, json_body=body),
            "folder creation",
        )
        return response.json()["id"]

    # -- files --------------------------------------------------------------
    def find_files(self, name: str, parent_id: str) -> list[RemoteFile]:
        response = self._checked(self._request("GET", API_URL, params={
            "q": f"name = '{_quote(name)}' and '{_quote(parent_id)}' in parents and trashed = false",
            "fields": f"files({FILE_FIELDS})",
            "pageSize": 20,
        }), "file lookup")
        return [_remote(f) for f in response.json().get("files", [])]

    def metadata(self, file_id: str) -> RemoteFile:
        response = self._checked(
            self._request("GET", f"{API_URL}/{_quote(file_id)}", params={"fields": FILE_FIELDS}),
            "checksum check",
        )
        return _remote(response.json())

    def upload(self, path: Path, name: str, parent_id: str) -> RemoteFile:
        """A resumable session with one PUT. On any failure the next retry starts over,
        and an interrupted session leaves no file behind."""
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        size = Path(path).stat().st_size
        start = self._checked(self._request(
            "POST", UPLOAD_URL,
            params={"uploadType": "resumable", "fields": FILE_FIELDS},
            headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)},
            json_body={"name": name, "parents": [parent_id]},
        ), "upload start")
        session_uri = start.headers.get("Location")
        if not session_uri:
            raise TransientDriveError("Google did not return an upload session.")
        with open(path, "rb") as fh:
            done = self._checked(self._request(
                "PUT", session_uri,
                headers={"Content-Type": mime, "Content-Length": str(size)},
                data=fh,
            ), "upload")
        return _remote(done.json())
