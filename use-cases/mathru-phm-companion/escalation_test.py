"""Tests for escalation delivery, persistence, and the honesty of the mother-facing text."""

import pytest

import escalation
import store

SESSION_ID = "94771234567"
PHM_PHONE = "94112223344"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv(store.DB_PATH_ENV_VAR, str(tmp_path / "test.db"))


@pytest.fixture
def mother():
    return store.upsert_mother(
        session_id=SESSION_ID,
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone=PHM_PHONE,
        edd_iso="2026-09-01",
    )


@pytest.fixture
def delivery_succeeds(monkeypatch):
    sent = []

    async def fake_send(to_number, text):
        sent.append((to_number, text))

    monkeypatch.setattr(escalation, "send_whatsapp", fake_send)
    return sent


@pytest.fixture
def delivery_fails(monkeypatch):
    async def fake_send(to_number, text):
        raise RuntimeError("24-hour customer service window is closed")

    monkeypatch.setattr(escalation, "send_whatsapp", fake_send)


# --- delivery succeeds ------------------------------------------------------------------


async def test_successful_delivery_is_persisted_as_delivered(mother, delivery_succeeds):
    result = await escalation.escalate(mother, "red", ["sign_a"], "I have heavy bleeding")

    assert result["delivered"] is True
    stored = store.open_escalations_for_phm(PHM_PHONE)
    assert len(stored) == 1
    assert stored[0]["delivery"] == store.DELIVERED
    assert stored[0]["delivery_error"] is None


async def test_message_goes_to_the_assigned_phm(mother, delivery_succeeds):
    await escalation.escalate(mother, "red", ["sign_a"], "I have heavy bleeding")
    to_number, _ = delivery_succeeds[0]
    assert to_number == PHM_PHONE


# --- delivery fails: the case that must never be silent ---------------------------------


async def test_failed_delivery_is_still_persisted(mother, delivery_fails):
    result = await escalation.escalate(mother, "red", ["sign_a"], "I have heavy bleeding")

    assert result["delivered"] is False
    stored = store.open_escalations_for_phm(PHM_PHONE)
    assert len(stored) == 1
    assert stored[0]["delivery"] == store.UNDELIVERED
    assert "window is closed" in stored[0]["delivery_error"]


async def test_failed_delivery_tells_the_mother_to_seek_care_herself(mother, delivery_fails):
    result = await escalation.escalate(mother, "red", ["sign_a"], "I have heavy bleeding")
    message = result["message_for_mother"]

    assert message == escalation.ESCALATION_FAILED_MESSAGE
    assert "hospital" in message
    assert "yourself" in message


def test_failure_message_never_implies_help_is_coming():
    message = escalation.ESCALATION_FAILED_MESSAGE.lower()
    for implication in ("i have sent", "has been sent", "notified", "on the way", "will contact you"):
        assert implication not in message
    assert "do not wait" in message


def test_failure_and_success_messages_are_different():
    assert escalation.ESCALATION_FAILED_MESSAGE != escalation.ESCALATION_SENT_MESSAGE


async def test_escalation_never_raises_when_delivery_fails(mother, delivery_fails):
    # A raised exception would surface as a generic error, which reads to a mother as though
    # nothing was wrong.
    result = await escalation.escalate(mother, "red", ["sign_a"], "bleeding")
    assert result["escalated"] is True


# --- payload shape ----------------------------------------------------------------------


async def test_payload_carries_the_required_fields(mother, delivery_succeeds):
    await escalation.escalate(mother, "red", ["sign_a", "sign_b"], "I have heavy bleeding since morning")
    _, text = delivery_succeeds[0]

    assert "RED" in text
    assert "Nimali" in text
    assert "Colombo" in text
    assert "sign_a, sign_b" in text
    assert "I have heavy bleeding since morning" in text
    assert "not a clinical assessment" in text


async def test_payload_sends_stored_edd_not_a_derived_gestational_week(mother, delivery_succeeds):
    # The week would have to come from the placeholder term reference. The raw stored date
    # is real data a midwife converts herself.
    await escalation.escalate(mother, "red", ["sign_a"], "bleeding")
    _, text = delivery_succeeds[0]
    assert "EDD 2026-09-01" in text


async def test_payload_omits_the_mothers_phone_number(mother, delivery_succeeds):
    await escalation.escalate(mother, "red", ["sign_a"], "bleeding")
    _, text = delivery_succeeds[0]
    assert SESSION_ID not in text


async def test_child_age_is_reported_in_weeks_for_a_registered_child(delivery_succeeds):
    # UTC, matching the implementation. Using the local date here would be off by one
    # whenever local and UTC fall on different days.
    from datetime import datetime, timedelta, timezone

    born = datetime.now(timezone.utc).date() - timedelta(weeks=6)
    record = store.upsert_mother(
        session_id=SESSION_ID,
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone=PHM_PHONE,
        child_dob_iso=born.isoformat(),
    )
    await escalation.escalate(record, "red", ["sign_a"], "baby is not feeding")
    _, text = delivery_succeeds[0]
    assert "age 6 weeks" in text


# --- excerpt ----------------------------------------------------------------------------


def test_excerpt_is_verbatim_when_short():
    assert escalation.excerpt("I have heavy bleeding") == "I have heavy bleeding"


def test_excerpt_collapses_whitespace():
    assert escalation.excerpt("I  have\n\nheavy   bleeding") == "I have heavy bleeding"


def test_excerpt_is_capped():
    long_text = "bleeding " * 200
    assert len(escalation.excerpt(long_text)) <= escalation.EXCERPT_MAX_CHARS
