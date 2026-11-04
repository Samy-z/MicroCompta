"""Shared fixtures. Fake identity and client only, and a temporary data directory."""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

# Before anything imports Qt or resolves a data directory.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from microcompta import i18n  # noqa: E402
from microcompta.backup.drive_client import (  # noqa: E402
    AuthRequired, PermanentDriveError, RemoteFile, TransientDriveError,
)
from microcompta.core import clock  # noqa: E402
from microcompta.core.book import Book  # noqa: E402
from microcompta.core.db import Database  # noqa: E402
from microcompta.core.profile import Profile  # noqa: E402

FAKE_SIREN = "123456782"  # passes the check digit; fake


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROCOMPTA_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture(autouse=True)
def _english_by_default():
    """Tests read the source text. The French ones set the language themselves."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pinned_today(monkeypatch: pytest.MonkeyPatch):
    """Set the date the app sees. Returns a setter, already set to 2027-06-15."""
    state = {"today": date(2027, 6, 15)}

    def set_today(value: date) -> None:
        state["today"] = value

    monkeypatch.setattr(clock, "today", lambda: state["today"])
    monkeypatch.setattr(
        clock, "now", lambda: datetime.combine(state["today"], datetime.min.time()).replace(hour=12)
    )
    return set_today


@pytest.fixture
def book(tmp_path: Path, pinned_today: Any):
    b = Book(Database(tmp_path / "book.duckdb"), tmp_path / "documents")
    yield b
    b.close()


@pytest.fixture
def identity() -> Profile:
    return Profile(
        legal_name="Camille Exemple",
        address="12 rue de l'Exemple\n00000 Exempleville",
        siren=FAKE_SIREN,
        email="camille@example.invalid",
        start_date=date(2027, 1, 1),
    )


@pytest.fixture
def client_id(book: Book) -> int:
    return book.clients.add(
        name="Acme Annotation LLC",
        address="1 Example Street\nSpringfield",
        country="United States",
        currency="USD",
        taxed_in_france=False,
        vat_note="Non-EU business client",
    )


def pay(book: Book, client_id: int, on: date, gross: str = "1000", rate: str = "1.25",
        fee: str = "0", net: str | None = None, **extra: Any) -> int:
    """Record a payment with sensible defaults."""
    if net is None:
        net = str(int(gross) / float(rate)) if float(gross).is_integer() else gross
    return book.ledger.record_payment(
        received_on=on, client_id=client_id, description=extra.pop("description", "Annotation work"),
        amount_gross=gross, fx_rate=rate, fee_amount=fee, net_credited=net,
        payment_method=extra.pop("payment_method", "Stripe"), **extra,
    )


class FakeDrive:
    """An in-memory Drive. The tests set what goes wrong."""

    def __init__(self) -> None:
        self.folders: dict[tuple[str, str | None], str] = {}
        self.files: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.fail_next: list[Exception] = []
        self.corrupt_uploads = False
        self.lose_upload_replies = 0
        self.hide_md5_once = False
        self._n = 0

    def _next_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def _maybe_fail(self, op: str) -> None:
        self.calls.append(op)
        if self.fail_next:
            raise self.fail_next.pop(0)

    def find_folder(self, name: str, parent_id: str | None) -> str | None:
        self._maybe_fail("find_folder")
        return self.folders.get((name, parent_id))

    def create_folder(self, name: str, parent_id: str | None) -> str:
        self._maybe_fail("create_folder")
        folder_id = self._next_id("folder")
        self.folders[(name, parent_id)] = folder_id
        return folder_id

    def find_files(self, name: str, parent_id: str) -> list[RemoteFile]:
        self._maybe_fail("find_files")
        return [self._remote(i) for i, f in self.files.items()
                if f["name"] == name and f["parent"] == parent_id]

    def upload(self, path: Path, name: str, parent_id: str) -> RemoteFile:
        self._maybe_fail("upload")
        content = Path(path).read_bytes()
        if self.corrupt_uploads:
            content = content + b"corrupted"
        file_id = self._next_id("file")
        self.files[file_id] = {"name": name, "parent": parent_id, "content": content}
        if self.lose_upload_replies:
            self.lose_upload_replies -= 1
            raise TransientDriveError("The connection dropped before the reply arrived.")
        return self._remote(file_id)

    def metadata(self, file_id: str) -> RemoteFile:
        self._maybe_fail("metadata")
        remote = self._remote(file_id)
        if self.hide_md5_once:
            self.hide_md5_once = False
            return RemoteFile(remote.id, remote.name, None, None, remote.size)
        return remote

    def _remote(self, file_id: str) -> RemoteFile:
        f = self.files[file_id]
        return RemoteFile(
            id=file_id, name=f["name"], md5=hashlib.md5(f["content"]).hexdigest(),
            sha256=hashlib.sha256(f["content"]).hexdigest(), size=len(f["content"]),
        )

    def path_of(self, file_id: str) -> list[str]:
        """The folder names above a file, root first."""
        names = {v: k for k, v in self.folders.items()}
        parts = []
        current = self.files[file_id]["parent"]
        while current is not None:
            name, current = names[current]
            parts.insert(0, name)
        return parts


@pytest.fixture
def drive() -> FakeDrive:
    return FakeDrive()


__all__ = ["AuthRequired", "FakeDrive", "PermanentDriveError", "TransientDriveError", "pay", "FAKE_SIREN"]
