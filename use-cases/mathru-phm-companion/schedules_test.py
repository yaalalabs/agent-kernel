"""Unit tests for the pure date arithmetic and the validation rules.

Every test injects `today`, so none of them depend on the day they are run.
"""

from datetime import date, timedelta

import pytest

import schedules

TODAY = date(2026, 6, 15)


# --- parse_iso_date ---------------------------------------------------------------------


def test_parse_iso_date_accepts_iso():
    assert schedules.parse_iso_date("2026-03-15") == date(2026, 3, 15)


def test_parse_iso_date_strips_surrounding_space():
    assert schedules.parse_iso_date("  2026-03-15 ") == date(2026, 3, 15)


@pytest.mark.parametrize("value", ["15-03-2026", "2026/03/15", "next Tuesday", "", "2026-02-30", None, 20260315])
def test_parse_iso_date_rejects_everything_else(value):
    assert schedules.parse_iso_date(value) is None


# --- years_ago --------------------------------------------------------------------------


def test_years_ago_ordinary_date():
    assert schedules.years_ago(date(2026, 6, 15), 5) == date(2021, 6, 15)


def test_years_ago_maps_leap_day_onto_28_february():
    # 2021 is not a leap year, so 2016-02-29 has no exact counterpart.
    assert schedules.years_ago(date(2016, 2, 29), 5) == date(2011, 2, 28)


# --- validate_edd -----------------------------------------------------------------------


def test_validate_edd_accepts_a_future_date():
    assert schedules.validate_edd("2026-09-01", today=TODAY) is None


def test_validate_edd_rejects_a_past_date():
    assert schedules.validate_edd("2026-06-14", today=TODAY) == schedules.EDD_NOT_FUTURE_MESSAGE


def test_validate_edd_rejects_today():
    # An antenatal calendar starting today is empty, and the mother may be in labour.
    assert schedules.validate_edd("2026-06-15", today=TODAY) == schedules.EDD_NOT_FUTURE_MESSAGE


def test_edd_not_future_message_directs_to_care_rather_than_reading_as_a_form_error():
    message = schedules.EDD_NOT_FUTURE_MESSAGE
    assert "hospital" in message
    assert "PHM" in message


def test_validate_edd_accepts_the_43_week_boundary_exactly():
    edd = TODAY + timedelta(days=schedules.MAX_EDD_DAYS)
    assert schedules.validate_edd(edd.isoformat(), today=TODAY) is None


def test_validate_edd_rejects_one_day_past_the_43_week_boundary():
    edd = TODAY + timedelta(days=schedules.MAX_EDD_DAYS + 1)
    assert schedules.validate_edd(edd.isoformat(), today=TODAY) == schedules.EDD_TOO_FAR_MESSAGE


def test_validate_edd_rejects_malformed_input():
    error = schedules.validate_edd("sometime in March", today=TODAY)
    assert error is not None
    assert "YYYY-MM-DD" in error


# --- validate_child_dob -----------------------------------------------------------------


def test_validate_child_dob_accepts_a_past_date():
    assert schedules.validate_child_dob("2025-01-10", today=TODAY) is None


def test_validate_child_dob_accepts_today():
    # Registration on day zero is a supported case.
    assert schedules.validate_child_dob("2026-06-15", today=TODAY) is None


def test_validate_child_dob_rejects_a_future_date():
    assert schedules.validate_child_dob("2026-06-16", today=TODAY) == schedules.DOB_FUTURE_MESSAGE


def test_validate_child_dob_accepts_the_five_year_boundary_exactly():
    dob = schedules.years_ago(TODAY, schedules.MAX_CHILD_AGE_YEARS)
    assert schedules.validate_child_dob(dob.isoformat(), today=TODAY) is None


def test_validate_child_dob_rejects_one_day_before_the_five_year_boundary():
    dob = schedules.years_ago(TODAY, schedules.MAX_CHILD_AGE_YEARS) - timedelta(days=1)
    assert schedules.validate_child_dob(dob.isoformat(), today=TODAY) == schedules.DOB_TOO_OLD_MESSAGE


def test_validate_child_dob_five_year_boundary_across_a_leap_day():
    leap_today = date(2016, 2, 29)
    assert schedules.validate_child_dob("2011-02-28", today=leap_today) is None
    assert schedules.validate_child_dob("2011-02-27", today=leap_today) == schedules.DOB_TOO_OLD_MESSAGE


def test_validate_child_dob_rejects_malformed_input():
    error = schedules.validate_child_dob("last year", today=TODAY)
    assert error is not None
    assert "YYYY-MM-DD" in error


# --- antenatal_visits -------------------------------------------------------------------


def test_antenatal_visit_date_is_edd_minus_the_remaining_weeks():
    edd = date(2026, 9, 1)
    calendar = schedules.antenatal_visits(edd.isoformat(), today=TODAY)
    term = schedules.load_schedule(schedules.ANTENATAL_FILE)["term_gestational_weeks"]

    for visit in calendar["visits"]:
        expected = edd - timedelta(days=(term - visit["gestational_week"]) * 7)
        assert visit["date_iso"] == expected.isoformat()


def test_antenatal_visits_are_sorted_by_date():
    calendar = schedules.antenatal_visits("2026-09-01", today=TODAY)
    dates = [visit["date_iso"] for visit in calendar["visits"]]
    assert dates == sorted(dates)


def test_antenatal_visits_relay_the_placeholder_status_of_the_data_file():
    # The shipped data files carry placeholder values, so the calendar must say so and the
    # agent must decline to read the dates out.
    calendar = schedules.antenatal_visits("2026-09-01", today=TODAY)
    assert calendar["status"] == "placeholder"


def test_antenatal_visits_reject_a_non_iso_edd():
    with pytest.raises(ValueError):
        schedules.antenatal_visits("not-a-date", today=TODAY)


# --- immunization_visits ----------------------------------------------------------------


def test_immunization_visit_date_is_dob_plus_the_age_in_weeks():
    dob = date(2026, 1, 5)
    calendar = schedules.immunization_visits(dob.isoformat(), today=TODAY)

    for visit in calendar["visits"]:
        expected = dob + timedelta(days=visit["age_weeks"] * 7)
        assert visit["date_iso"] == expected.isoformat()


def test_immunization_visits_relay_the_placeholder_status_of_the_data_file():
    calendar = schedules.immunization_visits("2026-01-05", today=TODAY)
    assert calendar["status"] == "placeholder"


def test_immunization_visits_reject_a_non_iso_dob():
    with pytest.raises(ValueError):
        schedules.immunization_visits("", today=TODAY)


# --- next_due ---------------------------------------------------------------------------


def _visits(*iso_dates: str) -> list[dict]:
    return [{"id": iso, "date_iso": iso} for iso in iso_dates]


def test_next_due_picks_the_earliest_future_visit():
    visits = _visits("2026-07-01", "2026-06-20", "2026-08-01")
    assert schedules.next_due(visits, today=TODAY)["date_iso"] == "2026-06-20"


def test_next_due_ignores_past_visits():
    visits = _visits("2026-01-01", "2026-06-20")
    assert schedules.next_due(visits, today=TODAY)["date_iso"] == "2026-06-20"


def test_next_due_includes_a_visit_falling_today():
    visits = _visits("2026-06-15", "2026-07-01")
    assert schedules.next_due(visits, today=TODAY)["date_iso"] == "2026-06-15"


def test_next_due_returns_none_when_every_visit_is_past():
    assert schedules.next_due(_visits("2026-01-01", "2026-02-01"), today=TODAY) is None


def test_next_due_returns_none_for_an_empty_calendar():
    assert schedules.next_due([], today=TODAY) is None
