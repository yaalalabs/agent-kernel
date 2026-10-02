"""Spoken-Sinhala numbers and rupee amounts for the two voice channels.

Read aloud as written, the reply tokens sound broken: a TTS engine spells
"LKR" letter by letter (එල් කේ ආර්) and reads "350.58" with a decimal point,
which hides that .58 means cents. Both voice paths convert before anything is
spoken, and both convert the same way through this module:

* the WhatsApp voice-note path rewrites the reply text (whatsapp_ext.media);
* the live-call path attaches ready-to-read ``*_spoken`` strings to tool
  results (voice.live_agent), because Gemini Live speaks its answer directly
  and there is no text stage left to rewrite.

The wording follows how amounts are actually said in Sinhala: රුපියල් comes
first, the final word of each part takes -යි, cents are සත (never දශම), and
zero cents are simply not said:

    345.00 -> "රුපියල් තුන්සිය හතලිස් පහයි"
    350.58 -> "රුපියල් තුන්සිය පනහයි සත පනස් අටයි"
    2500   -> "දෙදහස් පන්සීය"          (plain count, no -යි)
"""

from __future__ import annotations

from typing import Any

# Digits 0-9 as standalone words.
_ONES = ["බිංදුව", "එක", "දෙක", "තුන", "හතර", "පහ", "හය", "හත", "අට", "නවය"]
# 10-19 standalone.
_TEENS = ["දහය", "එකොළහ", "දොළහ", "දහතුන", "දාහතර", "පහළොව", "දාසය", "දාහත", "දහඅට", "දහනවය"]
# Whole tens standalone (20 විස්ස) vs followed by a unit (විසි එක).
_TENS = {2: "විස්ස", 3: "තිහ", 4: "හතලිහ", 5: "පනහ", 6: "හැට", 7: "හැත්තෑව", 8: "අසූව", 9: "අනූව"}
_TENS_JOINED = {2: "විසි", 3: "තිස්", 4: "හතලිස්", 5: "පනස්", 6: "හැට", 7: "හැත්තෑ", 8: "අසූ", 9: "අනූ"}
# Multipliers in front of සිය/සීය, and of දහස්/ලක්ෂ for single digits.
_HUNDRED_PREFIX = {1: "එක", 2: "දෙ", 3: "තුන්", 4: "හාර", 5: "පන්", 6: "හය", 7: "හත්", 8: "අට", 9: "නව"}
_UNIT_JOINED = {1: "එක්", 2: "දෙ", 3: "තුන්", 4: "හාර", 5: "පන්", 6: "හය", 7: "හත්", 8: "අට", 9: "නව"}
# 10-19 as a multiplier (12,000 දොළොස්දහස්).
_TEENS_JOINED = ["දහ", "එකොළොස්", "දොළොස්", "දහතුන්", "දාහතර", "පහළොස්", "දාසය", "දාහත්", "දහඅට", "දහනව"]

# Beyond 99 lakhs the wording rules here stop being trustworthy; callers fall
# back to digits, which a TTS engine at least reads unambiguously.
MAX_WORDABLE = 9_999_999


def _under_hundred(n: int) -> str:
    """1-99 standalone: 45 -> හතලිස් පහ, 58 -> පනස් අට."""
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    tens, unit = divmod(n, 10)
    if unit == 0:
        return _TENS[tens]
    return f"{_TENS_JOINED[tens]} {_ONES[unit]}"


def _under_hundred_joined(n: int) -> str:
    """1-99 as a multiplier prefix: 2 -> දෙ(දහස්), 56 -> පනස් හය(දහස්)."""
    if n < 10:
        return _UNIT_JOINED[n]
    if n < 20:
        return _TEENS_JOINED[n - 10]
    tens, unit = divmod(n, 10)
    if unit == 0:
        return _TENS_JOINED[tens]
    return f"{_TENS_JOINED[tens]} {_UNIT_JOINED[unit]}"


def _attach(multiplier: str, suffix: str) -> str:
    """Glue දහස්/ලක්ෂ onto the last word: 'පනස් හය' + 'දහස්' -> 'පනස් හයදහස්'."""
    head, _, last = multiplier.rpartition(" ")
    return (head + " " if head else "") + last + suffix


def _hundreds(n: int) -> str:
    """100-999, always the tail of the number: 345 -> තුන්සිය හතලිස් පහ, 500 -> පන්සීය."""
    h, rest = divmod(n, 100)
    if rest == 0:
        return "සීය" if h == 1 else _HUNDRED_PREFIX[h] + "සීය"
    prefix = "එකසිය" if h == 1 else _HUNDRED_PREFIX[h] + "සිය"
    return f"{prefix} {_under_hundred(rest)}"


def number_to_sinhala_words(n: int) -> str:
    """A whole number 0..9,999,999 in spoken-Sinhala words (base form, no -යි)."""
    if not 0 <= n <= MAX_WORDABLE:
        raise ValueError(f"cannot word {n}; supported range is 0..{MAX_WORDABLE}")
    if n == 0:
        return _ONES[0]
    parts: list[str] = []
    lakhs, n = divmod(n, 100_000)
    thousands, rest = divmod(n, 1000)
    if lakhs:
        joined = _under_hundred_joined(lakhs)
        if thousands or rest:
            parts.append(_attach(joined, "ලක්ෂ"))
        else:
            parts.append("ලක්ෂය" if lakhs == 1 else _attach(joined, "ලක්ෂය"))
    if thousands:
        parts.append(_attach(_under_hundred_joined(thousands), "දහස්" if rest else "දහස"))
    if rest:
        parts.append(_hundreds(rest) if rest >= 100 else _under_hundred(rest))
    return " ".join(parts)


def sinhala_digits(digits: str) -> str:
    """Digits read one by one, as decimal tails are: '58' -> 'පහ අට'."""
    return " ".join(_ONES[int(d)] for d in digits)


def rupees_to_sinhala_words(whole: int, cents: int = 0) -> str:
    """A rupee amount as it is said: 350/58 -> රුපියල් තුන්සිය පනහයි සත පනස් අටයි.

    Zero cents are not said at all, and the word දශම never appears; on a rupee
    amount the fraction IS cents. Raises ValueError above MAX_WORDABLE.
    """
    if whole == 0 and cents:
        return f"සත {number_to_sinhala_words(cents)}යි"
    spoken = f"රුපියල් {number_to_sinhala_words(whole)}යි"
    if cents:
        spoken += f" සත {number_to_sinhala_words(cents)}යි"
    return spoken


def _split_cents(amount: float) -> tuple[int, int]:
    total_cents = int(round(float(amount) * 100))
    return divmod(total_cents, 100)


def spoken_rupees(amount: float, language: str) -> str:
    """One rupee amount ready to be said aloud in the given language.

    Sinhala gets full words; English and Tamil keep digits (their TTS reads
    digits cleanly) with the currency worded and zero cents dropped. Amounts
    too large to word fall back to the digit form.
    """
    whole, cents = _split_cents(amount)
    if language == "si":
        try:
            return rupees_to_sinhala_words(whole, cents)
        except ValueError:
            spoken = f"රුපියල් {whole:,}"
            return f"{spoken} සත {cents}" if cents else spoken
    if language == "ta":
        spoken = f"ரூபாய் {whole:,}"
        return f"{spoken} சதம் {cents}" if cents else spoken
    spoken = f"{whole:,} rupees"
    return f"{spoken} and {cents} cents" if cents else spoken


# Every LKR-valued field a voice tool can return (engine/tariff.py and tool.py
# result shapes). Numbers under these keys get a ``<key>_spoken`` sibling.
_MONEY_KEYS = frozenset(
    {
        "total",
        "fixed_charge",
        "energy_charge",
        "sscl_levy",
        "charge",
        "current_bill",
        "new_bill",
        "savings",
        "savings_per_unit_cut",
        "before_total",
        "after_total",
        "bill_savings",
        "bill_at_those_units",
        "difference",
    }
)


def annotate_spoken_amounts(result: Any, language: str) -> Any:
    """Add ``<key>_spoken`` next to each money field, recursively, in place.

    The live call has no text stage to rewrite, so the ready-to-say string
    rides inside the tool result and the system prompt tells the model to read
    it verbatim. Raw numbers stay untouched for the model's own reasoning.
    """
    if isinstance(result, dict):
        additions = {}
        for key, value in result.items():
            if isinstance(value, (dict, list)):
                annotate_spoken_amounts(value, language)
            elif key in _MONEY_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                additions[f"{key}_spoken"] = spoken_rupees(value, language)
        result.update(additions)
    elif isinstance(result, list):
        for item in result:
            annotate_spoken_amounts(item, language)
    return result
