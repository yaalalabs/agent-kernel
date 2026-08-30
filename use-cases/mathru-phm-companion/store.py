"""Tool-owned SQLite storage for mother records.

This module is owned by the tools in `tool.py` and has nothing to do with Agent Kernel's
session backend, which stays `in_memory` (see `config.yaml`). Records are keyed by the
Agent Kernel session id, which the WhatsApp integration sets to the sender's phone number.

Only the fields SPEC.md permits are stored: first name, MOH division, one of EDD or child
date of birth, and the assigned PHM's phone number. No NIC, no full name, no address.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

DB_PATH_ENV_VAR = "MATHRU_DB_PATH"
DEFAULT_DB_PATH = "mathru.db"

# The single source of truth for the schema. The CHECK constraint enforces SPEC.md's
# "either edd_iso or child_dob_iso is required, not both" at the storage layer, so the rule
# holds even if a caller skips the tool-level validation.
SCHEMA = """
CREATE TABLE IF NOT EXISTS mothers (
    session_id    TEXT PRIMARY KEY,
    first_name    TEXT NOT NULL,
    moh_area      TEXT NOT NULL,
    edd_iso       TEXT,
    child_dob_iso TEXT,
    phm_phone     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK ((edd_iso IS NOT NULL) <> (child_dob_iso IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_mothers_phm_phone ON mothers (phm_phone);
"""

FIELDS = ("session_id", "first_name", "moh_area", "edd_iso", "child_dob_iso", "phm_phone", "created_at", "updated_at")


def redact_phone(phone: str) -> str:
    """Mask a phone number for log output, per SPEC.md. Keeps the last three digits only."""
    if not phone:
        return "<empty>"
    return f"***{phone[-3:]}" if len(phone) > 3 else "***"


def db_path() -> str:
    """Return the SQLite database path, from MATHRU_DB_PATH or the local default."""
    return os.environ.get(DB_PATH_ENV_VAR) or DEFAULT_DB_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with the schema applied and foreign/CHECK enforcement on."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return {key: row[key] for key in FIELDS} if row is not None else None


def get_mother(session_id: str) -> dict[str, Any] | None:
    """Return the stored record for a session id, or None when not registered."""
    with connect() as conn:
        cursor = conn.execute("SELECT * FROM mothers WHERE session_id = ?", (session_id,))
        return _row_to_dict(cursor.fetchone())


def upsert_mother(
    session_id: str,
    first_name: str,
    moh_area: str,
    phm_phone: str,
    edd_iso: str | None = None,
    child_dob_iso: str | None = None,
) -> dict[str, Any]:
    """Create or update a mother's record. Idempotent: re-registering the same session id
    updates the mutable fields and preserves the original created_at.

    Raises sqlite3.IntegrityError when neither or both of edd_iso and child_dob_iso are set.
    """
    now = _now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mothers (session_id, first_name, moh_area, edd_iso, child_dob_iso, phm_phone,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                first_name    = excluded.first_name,
                moh_area      = excluded.moh_area,
                edd_iso       = excluded.edd_iso,
                child_dob_iso = excluded.child_dob_iso,
                phm_phone     = excluded.phm_phone,
                updated_at    = excluded.updated_at
            """,
            (session_id, first_name, moh_area, edd_iso, child_dob_iso, phm_phone, now, now),
        )

    stored = get_mother(session_id)
    if stored is None:  # pragma: no cover - the insert above guarantees a row
        raise RuntimeError("Record was not persisted")
    return stored
