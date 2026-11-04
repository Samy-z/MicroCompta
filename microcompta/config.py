"""Application identity and filesystem locations."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "MicroCompta"

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
LOGO_DISPLAY_DARK = ASSETS_DIR / "MicroCompta_logo_display_dark.png"
LOGO_ICON = ASSETS_DIR / "MicroCompta_logo_icon.png"
APP_ICO = ASSETS_DIR / "MicroCompta.ico"

PACKAGE_DATA_DIR = Path(__file__).resolve().parent / "data"
FIGURES_SEED = PACKAGE_DATA_DIR / "figures_seed.json"

# Distinguishes the app from generic "python.exe" so Windows groups its taskbar
# button under our own icon rather than the interpreter's.
WINDOWS_APP_ID = "MicroCompta.Desktop.1"

# Set by tests and the smoke script, so they never touch the real records.
DATA_DIR_ENV = "MICROCOMPTA_DATA_DIR"


def _base_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def data_dir() -> Path:
    """Per-user directory for the records. Deliberately outside the repository."""
    override = os.environ.get(DATA_DIR_ENV)
    d = Path(override) if override else _base_dir() / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "microcompta.duckdb"


def documents_dir() -> Path:
    d = data_dir() / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def secrets_dir() -> Path:
    """The Google OAuth client file and token. Outside the project folder."""
    d = data_dir() / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def oauth_client_path() -> Path:
    return secrets_dir() / "google_oauth_client.json"


def token_path() -> Path:
    return secrets_dir() / "google_token.json"
