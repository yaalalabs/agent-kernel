"""Inbound media routing: voice notes and bill photos.

These pin the two multimodal entry points that Agent Kernel's stock handler does
not provide — audio is hard-rejected upstream, and images arrive with a bare
"[Image received]" caption that gives the model no reason to extract a reading.
"""

from __future__ import annotations

import agent
from whatsapp_ext.handler import _BILL_PHOTO_INSTRUCTION, _VOICE_NOTE_INSTRUCTION


def test_photo_instruction_demands_tool_use_not_model_arithmetic() -> None:
    """The engine must own every number, even ones read off an image."""
    assert "record_bill_reading" in _BILL_PHOTO_INSTRUCTION
    assert "never guess a number" in _BILL_PHOTO_INSTRUCTION.lower()


def test_photo_instruction_asks_the_model_to_show_its_reading() -> None:
    """A misread bill is worse than no bill, so the user must be able to correct it."""
    lowered = _BILL_PHOTO_INSTRUCTION.lower()
    assert "correct you" in lowered
    assert "type just that value" in lowered


def test_photo_instruction_covers_sri_lankan_bill_vocabulary() -> None:
    assert "kWh" in _BILL_PHOTO_INSTRUCTION
    assert "ඒකක" in _BILL_PHOTO_INSTRUCTION  # "units" on a Sinhala CEB bill


def test_voice_note_instruction_pins_reply_language_to_the_audio() -> None:
    assert "language" in _VOICE_NOTE_INSTRUCTION.lower()
    assert "Sinhala" in _VOICE_NOTE_INSTRUCTION and "Tamil" in _VOICE_NOTE_INSTRUCTION


def test_intake_no_longer_refuses_photo_parsing() -> None:
    """v1 explicitly told the model to ask for typed units instead of reading photos."""
    instruction = agent.intake.instruction

    assert "rather than promising" not in instruction
    assert "PHOTOGRAPH" in instruction
    assert "record_bill_reading" in instruction


def test_orchestrator_routes_photos_to_intake() -> None:
    instruction = agent.orchestrator.instruction

    assert "photo" in instruction.lower()
    assert "'intake'" in instruction


def test_bill_reading_tools_stay_bound_to_intake() -> None:
    """Photo reading is worthless if the tool that stores the value is unbound."""
    names = {t.name for t in agent.intake.tools}

    assert "record_bill_reading" in names
    assert "clear_bill_reading" in names
