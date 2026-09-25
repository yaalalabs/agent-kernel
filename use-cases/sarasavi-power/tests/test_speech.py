"""Spoken-Sinhala wording: the exact strings a caller should hear.

These pin the agreed pronunciations: රුපියල් (never the letters LKR), සත for
the fraction (never දශම), zero cents left unsaid, and Sinhala digits worded so
the TTS voice cannot slip into an English reading.
"""

from __future__ import annotations

import pytest

import speech
from whatsapp_ext.media import _normalize_for_speech


# --- number words -----------------------------------------------------------------


@pytest.mark.parametrize(
    "n,words",
    [
        (2500, "දෙදහස් පන්සීය"),  # the agreed wording, verbatim
        (345, "තුන්සිය හතලිස් පහ"),
        (350, "තුන්සිය පනහ"),
        (61, "හැට එක"),
        (100, "සීය"),
        (630, "හයසිය තිහ"),
        (1000, "එක්දහස"),
        (1260, "එක්දහස් දෙසිය හැට"),
        (56710, "පනස් හයදහස් හත්සිය දහය"),
        (100000, "ලක්ෂය"),
        (0, "බිංදුව"),
    ],
)
def test_numbers_word_the_way_they_are_said(n: int, words: str) -> None:
    assert speech.number_to_sinhala_words(n) == words


def test_unwordable_numbers_raise_rather_than_mangle() -> None:
    with pytest.raises(ValueError):
        speech.number_to_sinhala_words(speech.MAX_WORDABLE + 1)
    with pytest.raises(ValueError):
        speech.number_to_sinhala_words(-1)


# --- rupee amounts ----------------------------------------------------------------


def test_zero_cents_are_never_said() -> None:
    spoken = speech.spoken_rupees(345.00, "si")

    assert spoken == "රුපියල් තුන්සිය හතලිස් පහයි"
    assert "සත" not in spoken and "දශම" not in spoken and "බිංදු" not in spoken


def test_cents_are_sata_never_dashama() -> None:
    spoken = speech.spoken_rupees(350.58, "si")

    assert spoken == "රුපියල් තුන්සිය පනහයි සත පනස් අටයි"
    assert "දශම" not in spoken


def test_the_verified_ceb_bill_amount_words_cleanly() -> None:
    # The real D-TOU bill the tariff table is verified against: LKR 56,710.77.
    assert speech.spoken_rupees(56710.77, "si") == "රුපියල් පනස් හයදහස් හත්සිය දහයයි සත හැත්තෑ හතයි"


def test_english_and_tamil_keep_digits_but_word_the_currency() -> None:
    assert speech.spoken_rupees(1260.00, "en") == "1,260 rupees"
    assert speech.spoken_rupees(350.58, "en") == "350 rupees and 58 cents"
    assert speech.spoken_rupees(1260.00, "ta") == "ரூபாய் 1,260"


# --- tool-result annotation (the live-call path) ----------------------------------


def test_money_fields_gain_spoken_siblings_recursively() -> None:
    result = {
        "ok": True,
        "total": 1260.0,
        "units": 61.0,
        "opportunities": [{"savings": 630.0, "target_units": 60}],
    }

    speech.annotate_spoken_amounts(result, "si")

    assert result["total"] == 1260.0  # raw numbers stay for the model's reasoning
    assert result["total_spoken"] == "රුපියල් එක්දහස් දෙසිය හැටයි"
    assert result["opportunities"][0]["savings_spoken"] == "රුපියල් හයසිය තිහයි"
    assert "units_spoken" not in result  # kWh is not money
    assert "ok_spoken" not in result


# --- voice-note text normalization (the TTS path) ---------------------------------


def test_lkr_never_reaches_the_tts_engine_in_either_order() -> None:
    spoken = _normalize_for_speech("ඔබේ ඇස්තමේන්තුගත බිල LKR 1,260.00 වේ.")
    reversed_order = _normalize_for_speech("ඔබේ ඇස්තමේන්තුගත බිල 1,260.00 LKR වේ.")

    for text in (spoken, reversed_order):
        assert "LKR" not in text
        assert "රුපියල් එක්දහස් දෙසිය හැටයි" in text


def test_sinhala_reply_ends_up_with_no_digits_at_all() -> None:
    spoken = _normalize_for_speech("බිල LKR 350.58 යි; භාවිතය 61 kWh (දින 30).")

    assert not any(ch.isdigit() for ch in spoken)
    assert "රුපියල් තුන්සිය පනහයි සත පනස් අටයි" in spoken
    assert "කිලෝ වොට් හැට එක" in spoken  # unit word leads, like රුපියල් leads a rupee amount
    assert "දින තිහ" in spoken


def test_kwh_unit_word_leads_the_number_in_sinhala_and_tamil_but_not_english() -> None:
    assert "කිලෝ වොට් පන්සිය විස්ස" in _normalize_for_speech("භාවිතය 520 kWh වේ.")
    assert "கிலோவாட் 520" in _normalize_for_speech("பயன்பாடு 520 kWh ஆகும்.")
    assert _normalize_for_speech("Usage is 520 kWh.") == "Usage is 520 units."


def test_plain_sinhala_number_is_worded_without_currency() -> None:
    assert "දෙදහස් පන්සීය" in _normalize_for_speech("ඒක 2500 පමණ වේ.")


def test_natively_written_rupiyal_amounts_are_worded_too() -> None:
    # Text replies now write "රුපියල් 1,260.00" instead of "LKR 1,260.00"; the
    # digits and zero cents still have to become words before TTS reads them.
    spoken = _normalize_for_speech("ඔබේ බිල රුපියල් 350.58 වේ.")

    assert "රුපියල් තුන්සිය පනහයි සත පනස් අටයි" in spoken
    assert not any(ch.isdigit() for ch in spoken)


def test_english_reply_keeps_digits_but_drops_lkr() -> None:
    spoken = _normalize_for_speech("Your estimated bill is LKR 1,260.00 for 61 kWh.")

    assert spoken == "Your estimated bill is 1,260 rupees for 61 units."
