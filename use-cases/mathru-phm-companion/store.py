"""Tool-owned SQLite storage for mother records.

This module is owned by the tools in `tool.py` and has nothing to do with Agent Kernel's
session backend, which stays `in_memory` (see `config.yaml`). Records are keyed by the
Agent Kernel session id, which the WhatsApp integration sets to the sender's phone number.

Only the fields SPEC.md permits are stored: first name, MOH division, one of EDD or child
date of birth, and the assigned PHM's phone number. No NIC, no full name, no address.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from redaction import redact_phone  # re-exported: callers have imported it from here since phase 2

__all__ = [
    "DB_PATH_ENV_VAR",
    "DEFAULT_DB_PATH",
    "SCHEMA",
    "acknowledge_escalation",
    "connect",
    "db_path",
    "get_mother",
    "is_registered_phm",
    "mothers_for_phm",
    "open_escalations_for_phm",
    "record_escalation",
    "redact_phone",
    "upsert_mother",
]

DB_PATH_ENV_VAR = "MATHRU_DB_PATH"
DEFAULT_DB_PATH = "mathru.db"

DELIVERED = "delivered"
UNDELIVERED = "undelivered"

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

-- An escalation row is written whether or not WhatsApp delivery succeeds, so an
-- undelivered escalation stays visible in the PHM's caseload instead of vanishing.
CREATE TABLE IF NOT EXISTS escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    matched_signs   TEXT NOT NULL,
    excerpt         TEXT NOT NULL,
    phm_phone       TEXT NOT NULL,
    delivery        TEXT NOT NULL CHECK (delivery IN ('delivered', 'undelivered')),
    delivery_error  TEXT,
    acknowledged_at TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES mothers (session_id)
);

CREATE INDEX IF NOT EXISTS idx_escalations_phm_phone ON escalations (phm_phone);
CREATE INDEX IF NOT EXISTS idx_escalations_session ON escalations (session_id);
"""

FIELDS = ("session_id", "first_name", "moh_area", "edd_iso", "child_dob_iso", "phm_phone", "created_at", "updated_at")

ESCALATION_FIELDS = (
    "id",
    "session_id",
    "severity",
    "matched_signs",
    "excerpt",
    "phm_phone",
    "delivery",
    "delivery_error",
    "acknowledged_at",
    "created_at",
)


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


def _escalation_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    record = {key: row[key] for key in ESCALATION_FIELDS}
    record["matched_signs"] = json.loads(record["matched_signs"])
    return record


def record_escalation(
    session_id: str,
    severity: str,
    matched_signs: list[str],
    excerpt: str,
    phm_phone: str,
    delivery: str,
    delivery_error: str | None = None,
) -> dict[str, Any]:
    """Persist an escalation. Called on both delivery success and delivery failure."""
    now = _now_iso()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO escalations (session_id, severity, matched_signs, excerpt, phm_phone,
                                     delivery, delivery_error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, severity, json.dumps(matched_signs), excerpt, phm_phone, delivery, delivery_error, now),
        )
        escalation_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM escalations WHERE id = ?", (escalation_id,)).fetchone()
        return _escalation_to_dict(row)


def is_registered_phm(phone: str) -> bool:
    """Whether this number is the assigned PHM of at least one registered mother."""
    with connect() as conn:
        cursor = conn.execute("SELECT 1 FROM mothers WHERE phm_phone = ? LIMIT 1", (phone,))
        return cursor.fetchone() is not None


def mothers_for_phm(phm_phone: str) -> list[dict[str, Any]]:
    """Every mother assigned to this PHM."""
    with connect() as conn:
        cursor = conn.execute("SELECT * FROM mothers WHERE phm_phone = ? ORDER BY first_name", (phm_phone,))
        return [_row_to_dict(row) for row in cursor.fetchall()]  # type: ignore[misc]


def open_escalations_for_phm(phm_phone: str) -> list[dict[str, Any]]:
    """Unacknowledged escalations for this PHM, undelivered ones first.

    An undelivered escalation never reached the PHM's phone, so it is the most urgent thing
    in her caseload and is ordered to the top.
    """
    with connect() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM escalations
            WHERE phm_phone = ? AND acknowledged_at IS NULL
            ORDER BY (delivery = 'undelivered') DESC, created_at DESC
            """,
            (phm_phone,),
        )
        return [_escalation_to_dict(row) for row in cursor.fetchall()]


def acknowledge_escalation(escalation_id: int, phm_phone: str) -> dict[str, Any] | None:
    """Mark an escalation acknowledged, but only if it belongs to this PHM.

    Returns the updated record, or None when no open escalation with that id belongs to the
    caller. Scoping the update by phm_phone stops one PHM closing another's escalation.
    """
    now = _now_iso()
    with connect() as conn:
        conn.execute(
            """
            UPDATE escalations SET acknowledged_at = ?
            WHERE id = ? AND phm_phone = ? AND acknowledged_at IS NULL
            """,
            (now, escalation_id, phm_phone),
        )
        row = conn.execute(
            "SELECT * FROM escalations WHERE id = ? AND phm_phone = ?", (escalation_id, phm_phone)
        ).fetchone()
        return _escalation_to_dict(row) if row is not None else None
