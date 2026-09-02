"""Pure date arithmetic and input validation for the visit calendars.

Nothing in this module involves the language model. Every clinical value - which visits
exist, at which gestational week or child age, and the term reference used to convert a
gestational week into a date - lives in `data/*.yaml`, not here.

Every function that depends on the current date accepts an optional `today` argument so the
behaviour is deterministic under test.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).parent / "data"
ANTENATAL_FILE = "antenatal_schedule.yaml"
IMMUNIZATION_FILE = "immunization_schedule.yaml"

# The CHDR carries several overlapping schedules that do not share their ages. Each gets its
# own data file, its own provenance, and its own placeholder guard.
DEVELOPMENTAL_SCREENING_FILE = "developmental_screening.yaml"
VITAMIN_A_FILE = "vitamin_a.yaml"
MMN_SUPPLEMENTATION_FILE = "mmn_supplementation.yaml"

CHILD_SCHEDULE_FILES = (
    IMMUNIZATION_FILE,
    DEVELOPMENTAL_SCREENING_FILE,
    VITAMIN_A_FILE,
    MMN_SUPPLEMENTATION_FILE,
)

MAX_EDD_WEEKS = 43
MAX_EDD_DAYS = MAX_EDD_WEEKS * 7
MAX_CHILD_AGE_YEARS = 5

DATE_FORMAT_HINT = "Please give the date in YYYY-MM-DD format, for example 2026-03-15."

# Relayed verbatim by the agent. The EDD-in-the-past-or-today case is the one validation
# failure that can reach a mother in an urgent situation, so it reads as help rather than as
# a form error, and offers the registration path she may actually need.
EDD_NOT_FUTURE_MESSAGE = (
    "That date is today or in the past. If your baby is due today, or you think labour has started, "
    "please contact your PHM or your nearest hospital now. If your baby has already been born, tell me "
    "the date of birth instead and I will register your child."
)
EDD_TOO_FAR_MESSAGE = (
    f"That date is more than {MAX_EDD_WEEKS} weeks away, so I could not record it. "
    f"Please check the expected delivery date. {DATE_FORMAT_HINT}"
)
DOB_FUTURE_MESSAGE = (
    "That date of birth is in the future. If you are still expecting, tell me your expected delivery "
    f"date instead. {DATE_FORMAT_HINT}"
)
DOB_TOO_OLD_MESSAGE = (
    f"That date of birth is more than {MAX_CHILD_AGE_YEARS} years ago. This service covers children "
    f"under {MAX_CHILD_AGE_YEARS}. Please check the date. {DATE_FORMAT_HINT}"
)


def _today(today: date | None) -> date:
    return today if today is not None else date.today()


def parse_iso_date(value: str) -> date | None:
    """Parse a strict YYYY-MM-DD date, returning None when the input is not one."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def years_ago(reference: date, years: int) -> date:
    """The same calendar day N years earlier, mapping 29 February onto 28 February."""
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        return reference.replace(year=reference.year - years, month=2, day=28)


def validate_edd(edd_iso: str, today: date | None = None) -> str | None:
    """Validate an expected delivery date. Returns an error message, or None when valid.

    The EDD must be strictly in the future and no more than 43 weeks away.
    """
    now = _today(today)
    edd = parse_iso_date(edd_iso)
    if edd is None:
        return f"I could not read that as a date. {DATE_FORMAT_HINT}"
    if edd <= now:
        return EDD_NOT_FUTURE_MESSAGE
    if edd > now + timedelta(days=MAX_EDD_DAYS):
        return EDD_TOO_FAR_MESSAGE
    return None


def validate_child_dob(child_dob_iso: str, today: date | None = None) -> str | None:
    """Validate a child's date of birth. Returns an error message, or None when valid.

    The date must not be in the future and must be within the last 5 years. A child born
    today is valid: registration on day zero is a supported case.
    """
    now = _today(today)
    dob = parse_iso_date(child_dob_iso)
    if dob is None:
        return f"I could not read that as a date. {DATE_FORMAT_HINT}"
    if dob > now:
        return DOB_FUTURE_MESSAGE
    if dob < years_ago(now, MAX_CHILD_AGE_YEARS):
        return DOB_TOO_OLD_MESSAGE
    return None


@lru_cache(maxsize=None)
def load_schedule(filename: str) -> dict[str, Any]:
    """Load and cache a schedule data file from `data/`."""
    with (DATA_DIR / filename).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{filename} must contain a YAML mapping")
    return loaded


def _visit_entry(visit_date: date, entry: dict[str, Any], now: date, extra_key: str) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "label": entry.get("label"),
        extra_key: entry.get(extra_key),
        "date_iso": visit_date.isoformat(),
        "days_from_today": (visit_date - now).days,
        "is_past": visit_date < now,
    }


def antenatal_visits(edd_iso: str, today: date | None = None) -> dict[str, Any]:
    """The antenatal calendar derived from an EDD.

    A visit at gestational week W falls on `edd - (term_weeks - W) * 7 days`.
    """
    now = _today(today)
    edd = parse_iso_date(edd_iso)
    if edd is None:
        raise ValueError(f"Not an ISO date: {edd_iso!r}")

    data = load_schedule(ANTENATAL_FILE)
    term_weeks = data.get("term_gestational_weeks")
    if not isinstance(term_weeks, int):
        raise ValueError(f"{ANTENATAL_FILE} must define an integer term_gestational_weeks")

    visits = []
    for entry in data.get("visits") or []:
        week = entry.get("gestational_week")
        if not isinstance(week, int):
            continue
        visit_date = edd - timedelta(days=(term_weeks - week) * 7)
        visits.append(_visit_entry(visit_date, entry, now, "gestational_week"))

    visits.sort(key=lambda visit: visit["date_iso"])
    return {
        "kind": "antenatal",
        "status": data.get("status"),
        "source_file": f"data/{ANTENATAL_FILE}",
        "edd_iso": edd.isoformat(),
        "visits": visits,
    }


def add_months(start: date, months: int) -> date:
    """Add calendar months, clamping onto the last valid day of the target month.

    The national schedule is written in months, so it has to be computed in months. Treating
    a month as 4 weeks drifts: 60 months as 260 weeks lands six days early, and the error
    grows with age. 31 January plus one month clamps to 28 or 29 February.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def child_visits(filename: str, kind: str, child_dob_iso: str, today: date | None = None) -> dict[str, Any]:
    """A calendar of age-based child visits derived from a date of birth.

    Shared by every child-health schedule, since they differ only in their data file. An entry
    carries either `age_months` or `age_weeks`. Months are calendar months from the date of
    birth; weeks are `child_dob + W * 7 days`. An entry with both is a data error and is
    skipped rather than silently resolved one way.

    An entry may also carry `duration_days`, for a schedule item that is a period rather than
    a single appointment. The date is then the day the period starts.
    """
    now = _today(today)
    dob = parse_iso_date(child_dob_iso)
    if dob is None:
        raise ValueError(f"Not an ISO date: {child_dob_iso!r}")

    data = load_schedule(filename)

    visits = []
    for entry in data.get("visits") or []:
        months = entry.get("age_months")
        weeks = entry.get("age_weeks")
        has_months = isinstance(months, int) and not isinstance(months, bool)
        has_weeks = isinstance(weeks, int) and not isinstance(weeks, bool)

        if has_months == has_weeks:  # neither, or ambiguously both
            continue
        if has_months:
            visit = _visit_entry(add_months(dob, months), entry, now, "age_months")
        else:
            visit = _visit_entry(dob + timedelta(days=weeks * 7), entry, now, "age_weeks")

        duration = entry.get("duration_days")
        if isinstance(duration, int) and not isinstance(duration, bool):
            visit["duration_days"] = duration
        visits.append(visit)

    visits.sort(key=lambda visit: visit["date_iso"])
    return {
        "kind": kind,
        "status": data.get("status"),
        "source_file": f"data/{filename}",
        "child_dob_iso": dob.isoformat(),
        "visits": visits,
    }


def immunization_visits(child_dob_iso: str, today: date | None = None) -> dict[str, Any]:
    """The immunisation calendar derived from a child's date of birth."""
    return child_visits(IMMUNIZATION_FILE, "immunization", child_dob_iso, today)


def developmental_screening_visits(child_dob_iso: str, today: date | None = None) -> dict[str, Any]:
    """The developmental screening calendar derived from a child's date of birth."""
    return child_visits(DEVELOPMENTAL_SCREENING_FILE, "developmental_screening", child_dob_iso, today)


def vitamin_a_visits(child_dob_iso: str, today: date | None = None) -> dict[str, Any]:
    """The vitamin A calendar derived from a child's date of birth."""
    return child_visits(VITAMIN_A_FILE, "vitamin_a", child_dob_iso, today)


def mmn_supplementation_visits(child_dob_iso: str, today: date | None = None) -> dict[str, Any]:
    """The micronutrient supplementation calendar. Each entry is a period, not an appointment."""
    return child_visits(MMN_SUPPLEMENTATION_FILE, "mmn_supplementation", child_dob_iso, today)


def next_due(visits: list[dict[str, Any]], today: date | None = None) -> dict[str, Any] | None:
    """The earliest visit falling on or after today, or None when all are in the past."""
    now = _today(today)
    upcoming = [visit for visit in visits if parse_iso_date(visit["date_iso"]) >= now]  # type: ignore[operator]
    if not upcoming:
        return None
    return min(upcoming, key=lambda visit: visit["date_iso"])
