"""DuckDB storage layer."""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import duckdb

from ..config import db_path
from ..i18n import tr
from .errors import ImmutableError

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key VARCHAR PRIMARY KEY, value VARCHAR);
CREATE TABLE IF NOT EXISTS settings (key VARCHAR PRIMARY KEY, value VARCHAR);

-- Every limit, rate and fixed date. Effective-dated and editable, never in code.
CREATE TABLE IF NOT EXISTS figures (
    key            VARCHAR NOT NULL,
    effective_from DATE NOT NULL,
    value          VARCHAR NOT NULL,
    unit           VARCHAR NOT NULL,     -- eur | rate | days | date | md
    label          VARCHAR,
    source         VARCHAR,
    note           VARCHAR,
    edited_at      TIMESTAMP,
    PRIMARY KEY (key, effective_from)
);

CREATE TABLE IF NOT EXISTS clients (
    id              BIGINT PRIMARY KEY,
    name            VARCHAR NOT NULL,
    address         VARCHAR,
    country         VARCHAR,
    tax_id          VARCHAR,
    email           VARCHAR,
    currency        VARCHAR NOT NULL,
    taxed_in_france BOOLEAN NOT NULL,
    vat_note        VARCHAR,
    active          BOOLEAN NOT NULL,
    created_at      TIMESTAMP NOT NULL
);

-- Livre des recettes. Insert-only: see Database.GUARDED.
CREATE TABLE IF NOT EXISTS ledger (
    seq            BIGINT PRIMARY KEY,
    kind           VARCHAR NOT NULL,     -- payment | reversal
    reverses_seq   BIGINT,
    reason         VARCHAR,
    received_on    DATE NOT NULL,
    client_id      BIGINT,
    client_name    VARCHAR NOT NULL,
    description    VARCHAR NOT NULL,
    currency       VARCHAR NOT NULL,
    amount_gross   DECIMAL(14,2) NOT NULL,
    fx_rate        DECIMAL(12,6) NOT NULL,  -- units of currency per 1 EUR, as the ECB quotes it
    fx_source      VARCHAR NOT NULL,
    eur_gross      DECIMAL(14,2) NOT NULL,
    fee_amount     DECIMAL(14,2) NOT NULL,
    fee_currency   VARCHAR NOT NULL,
    fee_eur        DECIMAL(14,2) NOT NULL,
    net_credited   DECIMAL(14,2) NOT NULL,
    net_currency   VARCHAR NOT NULL,
    payment_method VARCHAR NOT NULL,
    provider_ref   VARCHAR,
    recorded_at    TIMESTAMP NOT NULL,
    prev_hash      VARCHAR NOT NULL,
    entry_hash     VARCHAR NOT NULL
);

-- Drafts and their state. Once issued, the register below is the record.
CREATE TABLE IF NOT EXISTS invoices (
    id                  BIGINT PRIMARY KEY,
    kind                VARCHAR NOT NULL,   -- invoice | credit_note
    status              VARCHAR NOT NULL,   -- draft | issued
    client_id           BIGINT NOT NULL,
    service_start       DATE,
    service_end         DATE,
    currency            VARCHAR NOT NULL,
    notes               VARCHAR,
    credited_invoice_id BIGINT,
    reason              VARCHAR,
    created_at          TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id           BIGINT PRIMARY KEY,
    invoice_id   BIGINT NOT NULL,
    position     INTEGER NOT NULL,
    description  VARCHAR NOT NULL,
    quantity     DECIMAL(12,3) NOT NULL,
    unit_price   DECIMAL(14,2) NOT NULL,
    total        DECIMAL(14,2) NOT NULL,
    ledger_seq   BIGINT,
    payment_date DATE
);

-- One row per issued document. Insert-only. seq is the unbroken number.
CREATE TABLE IF NOT EXISTS invoice_register (
    seq           BIGINT PRIMARY KEY,
    number        VARCHAR NOT NULL UNIQUE,
    invoice_id    BIGINT NOT NULL UNIQUE,
    kind          VARCHAR NOT NULL,
    issue_date    DATE NOT NULL,
    client_name   VARCHAR NOT NULL,
    currency      VARCHAR NOT NULL,
    total         DECIMAL(14,2) NOT NULL,
    fx_rate       DECIMAL(12,6) NOT NULL,
    total_eur     DECIMAL(14,2) NOT NULL,
    snapshot_json VARCHAR NOT NULL,
    pdf_sha256    VARCHAR NOT NULL,
    document_id   BIGINT NOT NULL,
    issued_at     TIMESTAMP NOT NULL,
    prev_hash     VARCHAR NOT NULL,
    entry_hash    VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id         BIGINT PRIMARY KEY,
    kind       VARCHAR NOT NULL,      -- invoice | receipt | export | snapshot
    title      VARCHAR NOT NULL,
    rel_path   VARCHAR NOT NULL,
    size       BIGINT NOT NULL,
    sha256     VARCHAR NOT NULL,
    md5        VARCHAR NOT NULL,
    year       INTEGER NOT NULL,
    ledger_seq BIGINT,
    invoice_id BIGINT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS upload_queue (
    document_id     BIGINT PRIMARY KEY,
    status          VARCHAR NOT NULL,  -- pending | uploaded | failed
    attempts        INTEGER NOT NULL,
    next_attempt_at TIMESTAMP NOT NULL,
    last_error      VARCHAR,
    drive_file_id   VARCHAR,
    drive_md5       VARCHAR,
    uploaded_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drive_folders (path VARCHAR PRIMARY KEY, folder_id VARCHAR NOT NULL);

CREATE TABLE IF NOT EXISTS deadline_state (
    key          VARCHAR PRIMARY KEY,
    done_at      TIMESTAMP,
    due_override DATE
);

CREATE TABLE IF NOT EXISTS reminder_log (
    key       VARCHAR NOT NULL,
    threshold INTEGER NOT NULL,
    sent_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (key, threshold)
);

CREATE TABLE IF NOT EXISTS annual_review (
    year INTEGER NOT NULL,
    item VARCHAR NOT NULL,
    done BOOLEAN NOT NULL,
    PRIMARY KEY (year, item)
);
"""

_WRITE_VERBS = r"(?:UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|DROP\s+TABLE(?:\s+IF\s+EXISTS)?|ALTER\s+TABLE)"


class Database:
    """One connection, serialised by a lock: the UI and the uploader thread share it."""

    #: Records that can only ever grow. The app's only route to them is execute(),
    #: so this holds for every write the app can make. See core/chain.py for the rest.
    GUARDED = ("ledger", "invoice_register")
    _GUARD_RE = re.compile(
        rf"^\s*{_WRITE_VERBS}\s+(?:main\.)?\"?({'|'.join(GUARDED)})\"?\b", re.IGNORECASE
    )

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path))
        self._lock = threading.RLock()
        self._tx_depth = 0
        self.con.execute(SCHEMA)
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    # -- statements ---------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        if self._GUARD_RE.match(sql):
            raise ImmutableError(tr("This record cannot be changed. Corrections are new entries."))
        with self._lock:
            self.con.execute(sql, list(params) if params is not None else [])

    def rows(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.con.execute(sql, list(params) if params is not None else [])
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]

    def row(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        found = self.rows(sql, params)
        return found[0] if found else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        with self._lock:
            found = self.con.execute(sql, list(params) if params is not None else []).fetchone()
        return found[0] if found else None

    def next_id(self, table: str, column: str = "id") -> int:
        return int(self.scalar(f"SELECT coalesce(max({column}), 0) + 1 FROM {table}"))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Re-entrant: an inner block joins the outer transaction."""
        with self._lock:
            outermost = self._tx_depth == 0
            if outermost:
                self.con.execute("BEGIN TRANSACTION")
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                self._tx_depth -= 1
                if outermost:
                    self.con.execute("ROLLBACK")
                raise
            else:
                self._tx_depth -= 1
                if outermost:
                    self.con.execute("COMMIT")

    # -- key/value ----------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        return self.scalar("SELECT value FROM meta WHERE key = ?", [key])

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            [key, value],
        )

    # -- whole-file operations ----------------------------------------------
    def checkpoint(self) -> None:
        with self._lock:
            self.con.execute("CHECKPOINT")

    def copy_to(self, dest: Path) -> None:
        """Write a consistent copy of the database to ``dest``.

        Checkpoint, then copy through DuckDB. Copying the file with shutil is not an
        option on Windows: the open connection holds it, and the copy fails with
        WinError 32 (measured with duckdb 2.0.0).
        """
        target = str(dest).replace("'", "''")
        with self._lock:
            self.con.execute("CHECKPOINT")
            source = self.con.execute("SELECT current_database()").fetchone()[0]
            self.con.execute(f"ATTACH '{target}' AS microcompta_snapshot")
            try:
                self.con.execute(f'COPY FROM DATABASE "{source}" TO microcompta_snapshot')
            finally:
                self.con.execute("DETACH microcompta_snapshot")

    def close(self) -> None:
        with self._lock:
            self.con.close()
