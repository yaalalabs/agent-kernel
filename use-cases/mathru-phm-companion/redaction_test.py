"""Tests for log redaction, and for its scope.

The scope test matters as much as the redaction itself: redaction that reached the
escalation path would strip the number the message has to be delivered to.
"""

import logging

import pytest

import escalation
import redaction
import store

SESSION_ID = "94771234567"
PHM_PHONE = "94112223344"


# --- redaction of values and free text --------------------------------------------------


def test_redact_phone_keeps_the_last_three_digits():
    assert redaction.redact_phone("94771234567") == "***567"


def test_redact_phone_handles_empty_and_short_values():
    assert redaction.redact_phone("") == "<empty>"
    assert redaction.redact_phone("12") == "***"


def test_redact_text_masks_numbers_inside_a_sentence():
    assert redaction.redact_text("Escalation sent to 94112223344 now") == "Escalation sent to ***344 now"


def test_redact_text_masks_multiple_numbers():
    result = redaction.redact_text("from 94771234567 to 94112223344")
    assert "94771234567" not in result
    assert "94112223344" not in result


def test_redact_text_leaves_short_numbers_alone():
    assert redaction.redact_text("visit 3 of 8") == "visit 3 of 8"


# --- the logging filter -----------------------------------------------------------------


def test_filter_redacts_the_log_message():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "sender 94771234567 registered", None, None)
    redaction.PhoneRedactionFilter().filter(record)
    assert "94771234567" not in record.msg
    assert "***567" in record.msg


def test_filter_redacts_log_arguments():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "sender %s registered", ("94771234567",), None)
    redaction.PhoneRedactionFilter().filter(record)
    assert "94771234567" not in record.getMessage()


def test_filter_redacts_the_logger_name():
    # Agent Kernel names its session logger `ak.core.session [<session id>]`, and the
    # session id is the mother's phone number.
    record = logging.LogRecord(
        f"ak.core.session [{SESSION_ID}]", logging.INFO, __file__, 1, "session stored", None, None
    )
    redaction.PhoneRedactionFilter().filter(record)
    assert SESSION_ID not in record.name


def test_filter_leaves_ordinary_messages_intact():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "nothing to redact", None, None)
    redaction.PhoneRedactionFilter().filter(record)
    assert record.msg == "nothing to redact"


def test_installed_filter_redacts_emitted_logs(caplog):
    redaction.install()
    with caplog.at_level(logging.INFO, logger="mathru.redaction_test"):
        logging.getLogger("mathru.redaction_test").info("PHM %s unreachable", PHM_PHONE)

    assert PHM_PHONE not in " ".join(record.getMessage() for record in caplog.records)


# --- scope: redaction must NOT reach the escalation path --------------------------------


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv(store.DB_PATH_ENV_VAR, str(tmp_path / "test.db"))


async def test_escalation_is_delivered_to_the_real_unredacted_number(monkeypatch):
    redaction.install()
    sent = []

    async def fake_send(to_number, text):
        sent.append(to_number)

    monkeypatch.setattr(escalation, "send_whatsapp", fake_send)
    record = store.upsert_mother(
        session_id=SESSION_ID,
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone=PHM_PHONE,
        edd_iso="2026-09-01",
    )

    await escalation.escalate(record, "red", ["sign_a"], "bleeding")

    assert sent == [PHM_PHONE]
    assert "***" not in sent[0]


async def test_stored_escalation_keeps_the_real_number(monkeypatch):
    redaction.install()

    async def fake_send(to_number, text):
        return None

    monkeypatch.setattr(escalation, "send_whatsapp", fake_send)
    record = store.upsert_mother(
        session_id=SESSION_ID,
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone=PHM_PHONE,
        edd_iso="2026-09-01",
    )

    await escalation.escalate(record, "red", ["sign_a"], "bleeding")

    assert store.open_escalations_for_phm(PHM_PHONE)[0]["phm_phone"] == PHM_PHONE


def test_stored_mother_record_keeps_the_real_number():
    redaction.install()
    stored = store.upsert_mother(
        session_id=SESSION_ID,
        first_name="Nimali",
        moh_area="Colombo",
        phm_phone=PHM_PHONE,
        edd_iso="2026-09-01",
    )
    assert stored["session_id"] == SESSION_ID
    assert stored["phm_phone"] == PHM_PHONE
