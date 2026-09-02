"""Storage tests for the two behaviours most likely to break: idempotent re-registration,
and the CHECK constraint that enforces exactly one of EDD or child date of birth.
"""

import sqlite3

import pytest

import store


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point the store at a throwaway database for each test."""
    monkeypatch.setenv(store.DB_PATH_ENV_VAR, str(tmp_path / "test.db"))


def test_reregistering_updates_fields_and_preserves_created_at():
    first = store.upsert_mother(
        session_id="94771234567",
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone="94112223344",
        edd_iso="2026-09-01",
    )

    second = store.upsert_mother(
        session_id="94771234567",
        first_name="Nimali",
        moh_area="Gampaha",
        phm_phone="94112223355",
        edd_iso="2026-10-01",
    )

    assert second["moh_area"] == "Gampaha"
    assert second["phm_phone"] == "94112223355"
    assert second["edd_iso"] == "2026-10-01"
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


def test_reregistering_does_not_create_a_second_row():
    for area in ("Colombo", "Gampaha", "Kandy"):
        store.upsert_mother(
            session_id="94771234567",
            first_name="Nimali",
            moh_area=area,
            phm_phone="94112223344",
            edd_iso="2026-09-01",
        )

    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mothers").fetchone()[0] == 1


def test_switching_from_edd_to_child_dob_clears_the_edd():
    store.upsert_mother(
        session_id="94771234567",
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone="94112223344",
        edd_iso="2026-09-01",
    )
    updated = store.upsert_mother(
        session_id="94771234567",
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone="94112223344",
        child_dob_iso="2026-06-01",
    )

    assert updated["edd_iso"] is None
    assert updated["child_dob_iso"] == "2026-06-01"


def test_check_constraint_rejects_neither_date():
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_mother(
            session_id="94771234567",
            first_name="Nimali",
            moh_area="Colombo",
            phm_phone="94112223344",
        )


def test_check_constraint_rejects_both_dates():
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_mother(
            session_id="94771234567",
            first_name="Nimali",
            moh_area="Colombo",
            phm_phone="94112223344",
            edd_iso="2026-09-01",
            child_dob_iso="2026-06-01",
        )


def test_get_mother_returns_none_when_not_registered():
    assert store.get_mother("94770000000") is None
