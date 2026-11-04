"""The REST client and sign-in, with a fake transport. Nothing here reaches Google.

These pin the requests the app sends, and the safety rules. They cannot prove that
Google accepts those requests: only a real sign-in can.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from microcompta import config
from microcompta.backup import oauth
from microcompta.backup.drive_client import (
    AuthRequired, ForbiddenRequest, PermanentDriveError, RestDriveClient, TransientDriveError,
)

ACCESS = "ya29.FAKE-ACCESS-TOKEN"
REFRESH = "1//FAKE-REFRESH-TOKEN"
SECRET = "GOCSPX-FAKE-CLIENT-SECRET"


class Reply:
    def __init__(self, status: int = 200, payload: Any = None, headers: dict[str, str] | None = None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeSession:
    def __init__(self, replies: list[Any]):
        self.replies = list(replies)
        self.sent: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Reply:
        body = kwargs.get("data")
        self.sent.append({"method": method, "url": url, **kwargs,
                          "body": body.read() if hasattr(body, "read") else body})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeTokens:
    def __init__(self) -> None:
        self.dropped = 0

    def access_token(self) -> str:
        return ACCESS

    def drop_access_token(self) -> None:
        self.dropped += 1


def client(*replies: Any) -> tuple[RestDriveClient, FakeSession, FakeTokens]:
    session = FakeSession(list(replies))
    tokens = FakeTokens()
    return RestDriveClient(tokens, session=session), session, tokens


# -- what is sent ------------------------------------------------------------
def test_resumable_upload_sends_the_documented_requests(tmp_path):
    path = tmp_path / "FA-2027-0001.pdf"
    path.write_bytes(b"%PDF body")
    drive, session, _ = client(
        Reply(200, headers={"Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=abc"}),
        Reply(200, {"id": "f1", "name": path.name, "md5Checksum": "m", "size": "9"}),
    )
    remote = drive.upload(path, path.name, "parent1")
    start, put = session.sent
    assert start["method"] == "POST"
    assert start["url"] == "https://www.googleapis.com/upload/drive/v3/files"
    assert start["params"]["uploadType"] == "resumable"
    assert start["json"] == {"name": path.name, "parents": ["parent1"]}
    assert start["headers"]["X-Upload-Content-Length"] == "9"
    assert put["method"] == "PUT"
    assert put["body"] == b"%PDF body"
    assert remote.id == "f1"
    assert remote.size == 9


def test_every_request_is_authorised(tmp_path):
    drive, session, _ = client(Reply(200, {"files": []}))
    drive.find_files("a.pdf", "p")
    assert session.sent[0]["headers"]["Authorization"] == f"Bearer {ACCESS}"
    assert session.sent[0]["allow_redirects"] is False


def test_a_quote_in_a_name_cannot_break_the_query():
    drive, session, _ = client(Reply(200, {"files": []}))
    drive.find_files("l'avoir' or name='x.pdf", "p")
    query = session.sent[0]["params"]["q"]
    assert "l\\'avoir\\' or name=\\'x.pdf" in query


def test_metadata_asks_for_the_checksums():
    drive, session, _ = client(Reply(200, {"id": "f1", "md5Checksum": "abc", "sha256Checksum": "def"}))
    remote = drive.metadata("f1")
    assert "md5Checksum" in session.sent[0]["params"]["fields"]
    assert remote.md5 == "abc"
    assert remote.sha256 == "def"


def test_folder_create_and_find():
    drive, session, _ = client(Reply(200, {"files": []}), Reply(200, {"id": "new"}))
    assert drive.find_folder("2027", "root1") is None
    assert drive.create_folder("2027", "root1") == "new"
    assert "application/vnd.google-apps.folder" in session.sent[0]["params"]["q"]
    assert session.sent[1]["json"]["parents"] == ["root1"]


# -- safety ------------------------------------------------------------------
@pytest.mark.parametrize("method", ["DELETE", "PATCH", "delete"])
def test_it_cannot_delete_or_trash(method):
    drive, session, _ = client()
    with pytest.raises(ForbiddenRequest):
        drive._request(method, "https://www.googleapis.com/drive/v3/files/x")
    assert session.sent == []


def test_it_has_no_method_that_deletes():
    names = [n.lower() for n in dir(RestDriveClient)]
    assert not [n for n in names if "delete" in n or "trash" in n or "remove" in n]


@pytest.mark.parametrize("url", [
    "https://example.com/upload",
    "http://www.googleapis.com/drive/v3/files",
    "https://www.googleapis.com.evil.example/x",
    "https://googleapis.com@evil.example/x",
])
def test_it_only_talks_to_google_over_https(url):
    drive, session, _ = client()
    with pytest.raises(ForbiddenRequest):
        drive._request("GET", url)
    assert session.sent == []


def test_a_session_uri_on_another_host_is_refused(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"x")
    drive, session, _ = client(Reply(200, headers={"Location": "https://evil.example/upload"}))
    with pytest.raises(ForbiddenRequest):
        drive.upload(path, "a.pdf", "p")
    assert len(session.sent) == 1


# -- error classes -----------------------------------------------------------
@pytest.mark.parametrize("failure", [requests.ConnectionError("x"), requests.Timeout("x")])
def test_no_network_is_transient(failure):
    drive, _, _ = client(failure)
    with pytest.raises(TransientDriveError):
        drive.metadata("f1")


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_busy_is_transient(status):
    drive, _, _ = client(Reply(status, {"error": {"message": "busy"}}))
    with pytest.raises(TransientDriveError):
        drive.metadata("f1")


def test_rate_limit_403_is_transient():
    payload = {"error": {"message": "slow down", "errors": [{"reason": "rateLimitExceeded"}]}}
    drive, _, _ = client(Reply(403, payload))
    with pytest.raises(TransientDriveError):
        drive.metadata("f1")


def test_other_403_is_permanent():
    payload = {"error": {"message": "quota", "errors": [{"reason": "storageQuotaExceeded"}]}}
    drive, _, _ = client(Reply(403, payload))
    with pytest.raises(PermanentDriveError) as caught:
        drive.metadata("f1")
    assert caught.value.status == 403
    assert "quota" in str(caught.value)


def test_404_is_permanent_and_carries_its_status():
    drive, _, _ = client(Reply(404, {"error": {"message": "File not found"}}))
    with pytest.raises(PermanentDriveError) as caught:
        drive.metadata("f1")
    assert caught.value.status == 404


def test_401_retries_once_with_a_fresh_token_then_asks_for_sign_in():
    drive, session, tokens = client(Reply(401, {}), Reply(401, {}))
    with pytest.raises(AuthRequired):
        drive.metadata("f1")
    assert len(session.sent) == 2
    assert tokens.dropped == 1


def test_401_then_success_needs_no_sign_in():
    drive, _, _ = client(Reply(401, {}), Reply(200, {"id": "f1"}))
    assert drive.metadata("f1").id == "f1"


# -- client file -------------------------------------------------------------
def write_client(path: Path, kind: str = "installed") -> Path:
    path.write_text(json.dumps({kind: {"client_id": "abc.apps.googleusercontent.com",
                                       "client_secret": SECRET}}), encoding="utf-8")
    return path


def test_client_file_must_be_a_desktop_client(tmp_path):
    with pytest.raises(oauth.OAuthError, match="Desktop app"):
        oauth.load_client_file(write_client(tmp_path / "web.json", "web"))


def test_client_file_must_be_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(oauth.OAuthError):
        oauth.load_client_file(bad)


def test_a_bad_client_file_is_not_installed(tmp_path):
    dest = tmp_path / "secrets" / "client.json"
    with pytest.raises(oauth.OAuthError):
        oauth.install_client_file(write_client(tmp_path / "web.json", "web"), dest)
    assert not dest.exists()


def test_secrets_live_outside_the_project_folder():
    for path in (config.oauth_client_path(), config.token_path()):
        assert config.ROOT_DIR not in Path(path).resolve().parents


def _git_ignores(path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=config.ROOT_DIR)
    assert result.returncode in (0, 1), "git check-ignore failed"
    return result.returncode == 0


@pytest.mark.parametrize("path", [
    "data/microcompta.duckdb",
    "documents/2027/factures/FA-2027-0001.pdf",
    "secrets/google_token.json",
    "client_secret_123.apps.googleusercontent.com.json",
    "google_oauth_client.json",
    "google_token.json",
    "token.json",
    "microcompta.duckdb",
    "microcompta.duckdb.wal",
    "livre_recettes_2027.csv",
    "logs/microcompta.log",
])
def test_git_ignores_the_records_and_the_secrets(path):
    assert _git_ignores(path), path


@pytest.mark.parametrize("path", [
    "microcompta/data/figures_seed.json",   # an unanchored "data/" once hid this one
    "microcompta/data/i18n/fr.json",
    "assets/gear.svg",
    "microcompta/core/ledger.py",
    "assets/MicroCompta.ico",
    "README.md",
])
def test_git_keeps_what_the_app_needs(path):
    assert not _git_ignores(path), path


# -- sign-in -----------------------------------------------------------------
class FakeHttp:
    def __init__(self, reply: Reply):
        self.reply = reply
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, data: dict[str, str], timeout: int) -> Reply:
        self.posts.append({"url": url, **data})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _granted() -> Reply:
    return Reply(200, {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600,
                       "scope": oauth.SCOPE, "token_type": "Bearer"})


def sign_in(tmp_path: Path, http: FakeHttp, **browser: Any) -> tuple[Path, dict[str, list[str]]]:
    """Run the flow, playing the browser: follow the URL back to the loopback server."""
    token_file = tmp_path / "token.json"
    seen: dict[str, list[str]] = {}

    def fake_browser(url: str) -> None:
        seen.update(parse_qs(urlsplit(url).query))
        redirect = seen["redirect_uri"][0]
        state = browser.get("state", seen["state"][0])
        query = browser.get("query", "code=FAKE-CODE")

        def visit() -> None:
            time.sleep(0.1)
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                f"{redirect}/?state={state}&{query}", timeout=5
            ).read()

        threading.Thread(target=visit, daemon=True).start()

    oauth.run_sign_in(oauth.OAuthClient("abc", SECRET), token_file, open_browser=fake_browser,
                      http=http, timeout=10)
    return token_file, seen


def test_sign_in_asks_for_the_narrow_scope_with_pkce(tmp_path):
    http = FakeHttp(_granted())
    token_file, seen = sign_in(tmp_path, http)
    assert seen["scope"] == ["https://www.googleapis.com/auth/drive.file"]
    assert seen["code_challenge_method"] == ["S256"]
    assert seen["redirect_uri"][0].startswith("http://127.0.0.1:")
    verifier = http.posts[0]["code_verifier"]
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert seen["code_challenge"] == [expected]
    assert http.posts[0]["code"] == "FAKE-CODE"
    assert json.loads(token_file.read_text())["refresh_token"] == REFRESH


def test_a_reply_with_the_wrong_state_is_refused(tmp_path):
    http = FakeHttp(_granted())
    with pytest.raises(oauth.OAuthError, match="didn't match"):
        sign_in(tmp_path, http, state="forged")
    assert http.posts == []
    assert not (tmp_path / "token.json").exists()


def test_declining_in_the_browser_is_reported(tmp_path):
    with pytest.raises(oauth.OAuthError, match="declined"):
        sign_in(tmp_path, FakeHttp(_granted()), query="error=access_denied")


def test_an_unticked_drive_box_is_reported(tmp_path):
    reply = Reply(200, {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600,
                        "scope": "openid"})
    with pytest.raises(oauth.OAuthError, match="tick the Drive box"):
        sign_in(tmp_path, FakeHttp(reply))
    assert not (tmp_path / "token.json").exists()


def test_sign_in_can_be_cancelled(tmp_path):
    with pytest.raises(oauth.OAuthError, match="cancelled"):
        oauth.run_sign_in(oauth.OAuthClient("abc", SECRET), tmp_path / "t.json",
                          open_browser=lambda _url: None, http=FakeHttp(_granted()),
                          cancelled=lambda: True)


def manager(tmp_path: Path, reply: Any, **token: Any) -> oauth.TokenManager:
    client_file = write_client(tmp_path / "client.json")
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"access_token": ACCESS, "refresh_token": REFRESH, **token}),
                          encoding="utf-8")
    return oauth.TokenManager(client_file, token_file, http=FakeHttp(reply))


def test_a_valid_token_needs_no_network(tmp_path):
    tokens = manager(tmp_path, Exception("should not be called"), expires_at=time.time() + 3600)
    assert tokens.access_token() == ACCESS
    assert tokens.http.posts == []


def test_an_expired_token_is_refreshed_and_keeps_the_refresh_token(tmp_path):
    reply = Reply(200, {"access_token": "ya29.NEW", "expires_in": 3600})
    tokens = manager(tmp_path, reply, expires_at=0)
    assert tokens.access_token() == "ya29.NEW"
    assert tokens.http.posts[0]["grant_type"] == "refresh_token"
    stored = json.loads(tokens.token_file.read_text())
    assert stored["refresh_token"] == REFRESH
    assert stored["access_token"] == "ya29.NEW"


def test_a_revoked_or_expired_grant_signs_out_and_says_why(tmp_path):
    tokens = manager(tmp_path, Reply(400, {"error": "invalid_grant"}), expires_at=0)
    with pytest.raises(AuthRequired, match="7 days"):
        tokens.access_token()
    assert not tokens.token_file.exists()
    assert tokens.state() == "signed_out"


def test_offline_refresh_keeps_the_token_and_is_transient(tmp_path):
    tokens = manager(tmp_path, requests.ConnectionError("x"), expires_at=0)
    with pytest.raises(TransientDriveError):
        tokens.access_token()
    assert tokens.token_file.exists()


def test_sign_out_touches_only_the_local_token(tmp_path):
    tokens = manager(tmp_path, Exception("no network expected"), expires_at=0)
    tokens.sign_out()
    assert not tokens.token_file.exists()
    assert tokens.http.posts == []
    assert tokens.client_file.exists()


def test_state_reports_what_is_missing(tmp_path):
    tokens = oauth.TokenManager(tmp_path / "none.json", tmp_path / "token.json")
    assert tokens.state() == "no_client"
    write_client(tmp_path / "none.json")
    assert tokens.state() == "signed_out"
    tokens.token_file.write_text("{}", encoding="utf-8")
    assert tokens.state() == "connected"


def test_secrets_never_reach_the_log(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    sign_in(tmp_path, FakeHttp(_granted()))
    tokens = manager(tmp_path, Reply(200, {"access_token": "ya29.NEW2", "expires_in": 3600}),
                     expires_at=0)
    tokens.access_token()
    drive, _, _ = client(Reply(500, {"error": {"message": "busy"}}))
    with pytest.raises(TransientDriveError):
        drive.metadata("f1")
    for secret in (ACCESS, REFRESH, SECRET, "ya29.NEW2", "FAKE-CODE"):
        assert secret not in caplog.text
