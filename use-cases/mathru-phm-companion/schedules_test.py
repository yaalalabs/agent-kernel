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


def test_immunization_visit_date_is_dob_plus_the_age_in_calendar_months():
    dob = date(2026, 1, 5)
    calendar = schedules.immunization_visits(dob.isoformat(), today=TODAY)

    for visit in calendar["visits"]:
        expected = schedules.add_months(dob, visit["age_months"])
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


# --- add_months: calendar arithmetic, not four-week approximation -----------------------


def test_add_months_ordinary_case():
    assert schedules.add_months(date(2026, 1, 15), 2) == date(2026, 3, 15)


def test_add_months_crosses_a_year_boundary():
    assert schedules.add_months(date(2026, 11, 10), 4) == date(2027, 3, 10)


def test_add_months_zero_is_the_same_day():
    assert schedules.add_months(date(2026, 6, 15), 0) == date(2026, 6, 15)


@pytest.mark.parametrize(
    "start,months,expected",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # short month
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap February
        (date(2026, 3, 31), 1, date(2026, 4, 30)),  # 30-day month
        (date(2026, 8, 31), 6, date(2027, 2, 28)),
    ],
)
def test_add_months_clamps_onto_the_last_valid_day(start, months, expected):
    assert schedules.add_months(start, months) == expected


def test_months_are_not_four_weeks():
    # Mapping each month onto four weeks is the worse of the two approximations: sixty months
    # becomes 1680 days against 1826 actual, landing almost five months early.
    born = date(2026, 1, 1)
    calendar_result = schedules.add_months(born, 60)
    four_week_result = born + timedelta(days=60 * 4 * 7)
    assert calendar_result == date(2031, 1, 1)
    assert (calendar_result - four_week_result).days == 146


def test_sixty_months_as_260_weeks_drifts_by_six_days():
    born = date(2026, 1, 1)
    assert (schedules.add_months(born, 60) - (born + timedelta(weeks=260))).days == 6


# --- month-based immunisation entries ---------------------------------------------------

MONTH_TABLE = {
    "status": "sourced",
    "visits": [
        {"id": "birth", "age_months": 0, "label": "BCG"},
        {"id": "two_months", "age_months": 2, "label": "Penta 1"},
        {"id": "five_years", "age_months": 60, "label": "DT"},
    ],
}


@pytest.fixture
def month_table(monkeypatch):
    monkeypatch.setattr(schedules, "load_schedule", lambda name: MONTH_TABLE)


def test_month_based_visits_use_calendar_months(month_table):
    calendar_data = schedules.immunization_visits("2026-01-31", today=TODAY)
    by_id = {visit["id"]: visit["date_iso"] for visit in calendar_data["visits"]}

    assert by_id["birth"] == "2026-01-31"
    assert by_id["two_months"] == "2026-03-31"
    assert by_id["five_years"] == "2031-01-31"


def test_an_entry_with_neither_unit_is_skipped(monkeypatch):
    monkeypatch.setattr(schedules, "load_schedule", lambda name: {"status": "sourced", "visits": [{"id": "bad"}]})
    assert schedules.immunization_visits("2026-01-01", today=TODAY)["visits"] == []


def test_an_entry_with_both_units_is_skipped_rather_than_guessed(monkeypatch):
    # Ambiguous data must not be silently resolved one way.
    monkeypatch.setattr(
        schedules,
        "load_schedule",
        lambda name: {"status": "sourced", "visits": [{"id": "bad", "age_months": 2, "age_weeks": 8}]},
    )
    assert schedules.immunization_visits("2026-01-01", today=TODAY)["visits"] == []


def test_week_based_entries_still_work(monkeypatch):
    monkeypatch.setattr(
        schedules,
        "load_schedule",
        lambda name: {"status": "sourced", "visits": [{"id": "w", "age_weeks": 6, "label": "x"}]},
    )
    visits = schedules.immunization_visits("2026-01-01", today=TODAY)["visits"]
    assert visits[0]["date_iso"] == "2026-02-12"


# --- the shipped immunisation file ------------------------------------------------------


def test_shipped_immunisation_entries_are_month_based():
    data = schedules.load_schedule(schedules.IMMUNIZATION_FILE)
    for entry in data["visits"]:
        assert "age_months" in entry, f"{entry.get('id')} is not month-based"
        assert "age_weeks" not in entry, f"{entry.get('id')} carries both units"


def test_shipped_immunisation_entries_are_ordered_and_unique():
    data = schedules.load_schedule(schedules.IMMUNIZATION_FILE)
    ages = [entry["age_months"] for entry in data["visits"]]
    assert ages == sorted(ages)
    assert len(ages) == len(set(ages))


def test_shipped_immunisation_ages_are_within_the_registration_window():
    # The service covers children under 5, so a visit past 60 months could never be reached.
    data = schedules.load_schedule(schedules.IMMUNIZATION_FILE)
    assert max(entry["age_months"] for entry in data["visits"]) <= schedules.MAX_CHILD_AGE_YEARS * 12


# --- the other CHDR child schedules -----------------------------------------------------


@pytest.mark.parametrize("filename", schedules.CHILD_SCHEDULE_FILES)
def test_every_child_schedule_entry_is_month_based_and_unambiguous(filename):
    data = schedules.load_schedule(filename)
    for entry in data["visits"]:
        assert "age_months" in entry, f"{filename}:{entry.get('id')} is not month-based"
        assert "age_weeks" not in entry, f"{filename}:{entry.get('id')} carries both units"


@pytest.mark.parametrize("filename", schedules.CHILD_SCHEDULE_FILES)
def test_every_child_schedule_is_ordered_unique_and_within_five_years(filename):
    ages = [entry["age_months"] for entry in schedules.load_schedule(filename)["visits"]]
    assert ages == sorted(ages)
    assert len(ages) == len(set(ages))
    assert max(ages) <= schedules.MAX_CHILD_AGE_YEARS * 12


@pytest.mark.parametrize("filename", schedules.CHILD_SCHEDULE_FILES)
def test_every_child_schedule_entry_has_a_unique_id(filename):
    ids = [entry["id"] for entry in schedules.load_schedule(filename)["visits"]]
    assert len(ids) == len(set(ids))


def test_developmental_screening_has_the_ten_documented_points():
    ages = [entry["age_months"] for entry in schedules.load_schedule(schedules.DEVELOPMENTAL_SCREENING_FILE)["visits"]]
    assert ages == [2, 4, 6, 9, 12, 18, 24, 36, 48, 60]


def test_screening_points_exist_that_no_immunisation_covers():
    # The reason this schedule is modelled separately: a mother told only about immunisation
    # visits would miss these three entirely.
    screening = {e["age_months"] for e in schedules.load_schedule(schedules.DEVELOPMENTAL_SCREENING_FILE)["visits"]}
    immunisation = {e["age_months"] for e in schedules.load_schedule(schedules.IMMUNIZATION_FILE)["visits"]}
    assert screening - immunisation == {24, 48}
    assert 60 in screening


def test_vitamin_a_encodes_the_six_monthly_reading():
    ages = [entry["age_months"] for entry in schedules.load_schedule(schedules.VITAMIN_A_FILE)["visits"]]
    assert ages == [6, 12, 18, 24, 30, 36, 42, 48, 54, 60]


def test_vitamin_a_file_records_the_unresolved_discrepancy():
    # Two sources disagree on the interval. The file must say so, not silently pick one.
    raw = (schedules.DATA_DIR / schedules.VITAMIN_A_FILE).read_text(encoding="utf-8")
    assert "DISCREPANCY" in raw
    assert "6, 18 and 36" in raw


def test_mmn_entries_are_periods_with_a_duration():
    visits = schedules.load_schedule(schedules.MMN_SUPPLEMENTATION_FILE)["visits"]
    assert [entry["age_months"] for entry in visits] == [6, 12, 18]
    for entry in visits:
        assert entry["duration_days"] == 60


def test_duration_is_carried_through_to_the_computed_visit():
    calendar_data = schedules.mmn_supplementation_visits("2026-01-15", today=TODAY)
    for visit in calendar_data["visits"]:
        assert visit["duration_days"] == 60


def test_duration_is_absent_when_the_entry_has_none():
    calendar_data = schedules.immunization_visits("2026-01-15", today=TODAY)
    assert all("duration_days" not in visit for visit in calendar_data["visits"])


@pytest.mark.parametrize(
    "loader,kind",
    [
        (schedules.immunization_visits, "immunization"),
        (schedules.developmental_screening_visits, "developmental_screening"),
        (schedules.vitamin_a_visits, "vitamin_a"),
        (schedules.mmn_supplementation_visits, "mmn_supplementation"),
    ],
)
def test_each_child_schedule_loader_reports_its_kind_and_placeholder_status(loader, kind):
    calendar_data = loader("2026-01-15", today=TODAY)
    assert calendar_data["kind"] == kind
    assert calendar_data["status"] == "placeholder"


def test_child_schedule_dates_use_calendar_months():
    calendar_data = schedules.developmental_screening_visits("2026-01-31", today=TODAY)
    by_id = {visit["id"]: visit["date_iso"] for visit in calendar_data["visits"]}
    assert by_id["screening_02m"] == "2026-03-31"
    assert by_id["screening_60m"] == "2031-01-31"
