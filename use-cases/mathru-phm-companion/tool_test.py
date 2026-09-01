"""Tests for role resolution, PHM capabilities, and the screening tool's escalation path."""

import json

import pytest
from agentkernel.core import Session, ToolContext

import danger_signs
import escalation
import store
import tool

MOTHER = "94771234567"
PHM = "94112223344"
OTHER_PHM = "94119998888"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv(store.DB_PATH_ENV_VAR, str(tmp_path / "test.db"))


@pytest.fixture
def as_sender():
    """Run tool calls as a given session id, the way the runner would.

    The context is set but never reset: an async test body runs in a different context from
    this fixture, and a contextvar Token cannot be reset across that boundary. Each test
    sets its own, so there is nothing to unwind.
    """

    def _use(session_id):
        return ToolContext(None, None, Session(session_id), []).set()

    return _use


@pytest.fixture
def delivery_succeeds(monkeypatch):
    async def fake_send(to_number, text):
        return None

    monkeypatch.setattr(escalation, "send_whatsapp", fake_send)


def register(session_id, phm_phone=PHM, **kwargs):
    return store.upsert_mother(
        session_id=session_id,
        first_name=kwargs.get("first_name", "Nimali"),
        moh_area=kwargs.get("moh_area", "Colombo"),
        phm_phone=phm_phone,
        edd_iso=kwargs.get("edd_iso", "2026-09-01"),
        child_dob_iso=kwargs.get("child_dob_iso"),
    )


# --- resolve_role -----------------------------------------------------------------------


def test_unknown_sender_has_no_role(as_sender):
    as_sender("94770000000")
    assert json.loads(tool.resolve_role())["role"] == "unknown"


def test_registered_sender_is_a_mother(as_sender):
    register(MOTHER)
    as_sender(MOTHER)
    result = json.loads(tool.resolve_role())
    assert result["role"] == "mother"
    assert result["may_report_symptoms"] is True


def test_a_number_used_as_phm_phone_resolves_as_phm(as_sender):
    register(MOTHER, phm_phone=PHM)
    as_sender(PHM)
    result = json.loads(tool.resolve_role())
    assert result["role"] == "phm"
    assert result["is_phm"] is True


def test_a_phm_who_is_herself_pregnant_keeps_the_symptom_path_open(as_sender):
    # A midwife can be pregnant too. Role governs PHM capabilities only; it must not close
    # her own danger-sign path.
    register(MOTHER, phm_phone=PHM)
    register(PHM, phm_phone=OTHER_PHM)
    as_sender(PHM)

    result = json.loads(tool.resolve_role())
    assert result["role"] == "phm"
    assert result["is_phm"] is True
    assert result["is_registered_mother"] is True
    assert result["may_report_symptoms"] is True


async def test_a_pregnant_phm_can_still_escalate(as_sender, delivery_succeeds, monkeypatch):
    register(PHM, phm_phone=OTHER_PHM)
    as_sender(PHM)

    result = json.loads(await tool.screen_danger_signs("I have heavy bleeding"))
    assert result["severity"] == danger_signs.RED
    assert result["escalated"] is True


# --- screen_danger_signs ----------------------------------------------------------------


async def test_screening_escalates_on_red_within_the_same_call(as_sender, delivery_succeeds):
    register(MOTHER)
    as_sender(MOTHER)

    result = json.loads(await tool.screen_danger_signs("I have heavy bleeding"))

    assert result["severity"] == danger_signs.RED
    assert result["escalated"] is True
    assert result["delivered"] is True
    assert len(store.open_escalations_for_phm(PHM)) == 1


async def test_screening_reply_carries_the_standing_note(as_sender, delivery_succeeds):
    register(MOTHER)
    as_sender(MOTHER)
    result = json.loads(await tool.screen_danger_signs("I feel unwell"))
    assert result["standing_note"] == tool.STANDING_NOTE


async def test_unregistered_sender_is_told_to_seek_care_herself(as_sender):
    # Nobody to escalate to, so the reply must never imply anything was sent.
    as_sender("94770000000")

    result = json.loads(await tool.screen_danger_signs("I have heavy bleeding"))

    assert result["severity"] == danger_signs.RED
    assert result["escalated"] is False
    assert result["message_for_mother"] == escalation.ESCALATION_FAILED_MESSAGE


async def test_no_symptom_text_is_green_and_does_not_escalate(as_sender):
    register(MOTHER)
    as_sender(MOTHER)

    result = json.loads(await tool.screen_danger_signs(""))

    assert result["severity"] == danger_signs.GREEN
    assert "escalated" not in result
    assert store.open_escalations_for_phm(PHM) == []


# --- phm_caseload -----------------------------------------------------------------------


def test_caseload_is_refused_to_a_non_phm(as_sender):
    register(MOTHER)
    as_sender(MOTHER)
    assert json.loads(tool.phm_caseload())["ok"] is False


def test_caseload_lists_the_phms_mothers(as_sender):
    register(MOTHER, phm_phone=PHM)
    register("94770000001", phm_phone=PHM, first_name="Kumari")
    register("94770000002", phm_phone=OTHER_PHM, first_name="Sanduni")
    as_sender(PHM)

    result = json.loads(tool.phm_caseload())

    assert result["mother_count"] == 2
    assert {mother["first_name"] for mother in result["mothers"]} == {"Nimali", "Kumari"}


def test_caseload_does_not_expose_mothers_phone_numbers(as_sender):
    register(MOTHER, phm_phone=PHM)
    as_sender(PHM)
    assert MOTHER not in tool.phm_caseload()


async def test_caseload_counts_undelivered_escalations(as_sender, monkeypatch):
    async def failing_send(to_number, text):
        raise RuntimeError("window closed")

    monkeypatch.setattr(escalation, "send_whatsapp", failing_send)
    register(MOTHER, phm_phone=PHM)
    as_sender(MOTHER)
    await tool.screen_danger_signs("I have heavy bleeding")

    as_sender(PHM)
    result = json.loads(tool.phm_caseload())

    assert result["open_escalation_count"] == 1
    assert result["undelivered_count"] == 1


# --- acknowledge_escalation -------------------------------------------------------------


async def test_acknowledging_closes_the_escalation(as_sender, delivery_succeeds):
    register(MOTHER, phm_phone=PHM)
    as_sender(MOTHER)
    await tool.screen_danger_signs("I have heavy bleeding")

    as_sender(PHM)
    escalation_id = json.loads(tool.phm_caseload())["open_escalations"][0]["id"]
    result = json.loads(tool.acknowledge_escalation(escalation_id))

    assert result["acknowledged"] is True
    assert json.loads(tool.phm_caseload())["open_escalation_count"] == 0


async def test_a_phm_cannot_acknowledge_another_phms_escalation(as_sender, delivery_succeeds):
    register(MOTHER, phm_phone=PHM)
    as_sender(MOTHER)
    await tool.screen_danger_signs("I have heavy bleeding")

    escalation_id = store.open_escalations_for_phm(PHM)[0]["id"]
    register("94770000009", phm_phone=OTHER_PHM)
    as_sender(OTHER_PHM)

    assert json.loads(tool.acknowledge_escalation(escalation_id))["ok"] is False
    assert len(store.open_escalations_for_phm(PHM)) == 1


def test_acknowledging_is_refused_to_a_non_phm(as_sender):
    register(MOTHER)
    as_sender(MOTHER)
    assert json.loads(tool.acknowledge_escalation(1))["ok"] is False
