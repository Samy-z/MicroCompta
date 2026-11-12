"""Google sign-in for a desktop app: browser, loopback redirect, PKCE.

The owner creates the OAuth client and signs in themselves, in their own browser. This code never
sees a Google password. It holds only the client file and the resulting token, both
under the data directory's secrets folder, and it never writes either to a log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from ..i18n import tr
from .drive_client import AuthRequired, TransientDriveError

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"

_DONE_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>MicroCompta</title>"
    "<body style='font:15px system-ui;background:#0d1016;color:#e9ecf2;padding:48px'>"
    "<h2>{title}</h2><p>{body}</p></body>"
)


class OAuthError(Exception):
    """Sign-in didn't complete. The message is safe to show."""


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str


def load_client_file(path: Path) -> OAuthClient:
    """Read the JSON downloaded from Google Cloud Console."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OAuthError(tr("That file could not be read as JSON.")) from exc
    if not isinstance(raw, dict):
        raise OAuthError(tr("That is not an OAuth client file."))
    if "installed" not in raw:
        kind = next(iter(raw), "unknown")
        raise OAuthError(
            tr("That client is of type '{kind}'. Create one of type 'Desktop app' instead.", kind=kind)
        )
    block = raw["installed"]
    if not block.get("client_id"):
        raise OAuthError(tr("That file has no client_id."))
    return OAuthClient(block["client_id"], block.get("client_secret", ""))


def install_client_file(source: Path, dest: Path) -> None:
    """Validate, then keep a copy in the secrets folder."""
    load_client_file(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(client: OAuthClient, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })


class _Callback(HTTPServer):
    allow_reuse_address = False
    result: dict[str, str] | None = None
    expected_state = ""


class _Handler(BaseHTTPRequestHandler):
    server: _Callback

    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlsplit(self.path).query)
        if "state" not in query:  # the browser asking for /favicon.ico, say
            self.send_response(404)
            self.end_headers()
            return
        ok = query["state"][0] == self.server.expected_state
        if not ok:
            self.server.result = {"error": "state_mismatch"}
        elif "code" in query:
            self.server.result = {"code": query["code"][0]}
        else:
            self.server.result = {"error": query.get("error", ["unknown"])[0]}
        succeeded = ok and "code" in query
        page = _DONE_PAGE.format(
            title=tr("Signed in") if succeeded else tr("Sign-in did not complete"),
            body=tr("You can close this tab and go back to MicroCompta.")
            if succeeded else tr("Go back to MicroCompta and try again."),
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        """Silent: the default handler prints the request line, which holds the code."""


def run_sign_in(
    client: OAuthClient,
    token_file: Path,
    *,
    open_browser: Callable[[str], Any] = webbrowser.open,
    http: Any = requests,
    timeout: float = 300.0,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """Open the browser, wait for Google to redirect back, store the token."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    server = _Callback(("127.0.0.1", 0), _Handler)
    server.timeout = 0.25
    server.expected_state = state
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        open_browser(authorization_url(client, redirect_uri, state, challenge))
        deadline = time.monotonic() + timeout
        while server.result is None:
            if cancelled():
                raise OAuthError(tr("Sign-in cancelled."))
            if time.monotonic() > deadline:
                raise OAuthError(tr("Sign-in timed out. Start it again when you're ready."))
            server.handle_request()
    finally:
        server.server_close()

    result = server.result
    if "code" not in result:
        if result["error"] == "state_mismatch":
            raise OAuthError(tr("The browser's reply didn't match this sign-in, so it was refused."))
        if result["error"] == "access_denied":
            raise OAuthError(tr("Access was declined in the browser."))
        raise OAuthError(tr("Google reported: {error}.", error=result["error"]))

    payload = {
        "code": result["code"],
        "client_id": client.client_id,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client.client_secret:
        payload["client_secret"] = client.client_secret
    try:
        response = http.post(TOKEN_URL, data=payload, timeout=30)
    except requests.RequestException as exc:
        raise OAuthError(tr("No connection to Google ({error}).", error=type(exc).__name__)) from None
    if response.status_code != 200:
        raise OAuthError(tr("Google refused the sign-in (HTTP {status}).", status=response.status_code))

    token = response.json()
    if SCOPE not in token.get("scope", "").split():
        raise OAuthError(tr(
            "Google Drive access wasn't granted. Sign in again and tick the Drive box on "
            "the consent screen."
        ))
    if not token.get("refresh_token"):
        raise OAuthError(tr("Google returned no refresh token. Remove the app's access in your "
                            "Google account, then sign in again."))
    _store_token(token_file, token)
    log.info("Google Drive sign-in completed.")


def _store_token(path: Path, token: dict[str, Any]) -> None:
    """Atomic, so a crash mid-write can't leave a half-written token behind."""
    record = dict(token)
    record["expires_at"] = time.time() + float(token.get("expires_in", 3600))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class TokenManager:
    """Hands out a valid access token, refreshing it when needed."""

    MARGIN_SECONDS = 60

    def __init__(self, client_file: Path, token_file: Path, http: Any = requests):
        self.client_file = Path(client_file)
        self.token_file = Path(token_file)
        self.http = http

    def state(self) -> str:
        """no_client | signed_out | connected"""
        if not self.client_file.exists():
            return "no_client"
        return "connected" if self.token_file.exists() else "signed_out"

    def sign_out(self) -> None:
        """Forget the token on this machine. Nothing in Drive is touched."""
        self.token_file.unlink(missing_ok=True)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuthRequired(tr("Not signed in to Google Drive.")) from exc

    def drop_access_token(self) -> None:
        token = self._load()
        token["expires_at"] = 0
        token["expires_in"] = 0
        self.token_file.write_text(json.dumps(token), encoding="utf-8")

    def access_token(self) -> str:
        token = self._load()
        if token.get("access_token") and time.time() < float(token.get("expires_at", 0)) - self.MARGIN_SECONDS:
            return token["access_token"]
        return self._refresh(token)

    def _refresh(self, token: dict[str, Any]) -> str:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            self.sign_out()
            raise AuthRequired(tr("Not signed in to Google Drive."))
        try:
            client = load_client_file(self.client_file)
        except OAuthError as exc:
            raise AuthRequired(str(exc)) from None
        payload = {
            "client_id": client.client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if client.client_secret:
            payload["client_secret"] = client.client_secret
        try:
            response = self.http.post(TOKEN_URL, data=payload, timeout=30)
        except requests.RequestException as exc:
            raise TransientDriveError(
                tr("No connection to Google ({error}).", error=type(exc).__name__)
            ) from None

        if response.status_code >= 500 or response.status_code == 429:
            raise TransientDriveError(tr("Google sign-in service: HTTP {status}.", status=response.status_code))
        if response.status_code != 200:
            try:
                error = response.json().get("error", "")
            except ValueError:
                error = ""
            if error == "invalid_grant":
                self.sign_out()
                raise AuthRequired(tr(
                    "Google sign-in expired or was revoked. Reconnect Google Drive. If this "
                    "happens every 7 days, the OAuth app is still in Testing: publish it."
                ))
            raise AuthRequired(tr("Google refused the sign-in ({error}).", error=error or response.status_code))

        fresh = response.json()
        merged = {**token, **fresh, "refresh_token": fresh.get("refresh_token", refresh_token)}
        _store_token(self.token_file, merged)
        return merged["access_token"]
