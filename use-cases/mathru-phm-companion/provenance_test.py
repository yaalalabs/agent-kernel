"""Tests that make the provenance header load-bearing rather than decorative.

The rule these enforce: a clinical data file may not claim `status: sourced` until it can
say, in the file itself, which published document its values came from. Without this the
header is a comment nobody has to honour, and the difference between "we sourced this" and
"we made up some dates" is a promise rather than a check.
"""

import pathlib

import pytest
import yaml

import provenance

DATA_DIR = pathlib.Path(__file__).parent / "data"
CLINICAL_FILES = (
    "antenatal_schedule.yaml",
    "immunization_schedule.yaml",
    "developmental_screening.yaml",
    "vitamin_a.yaml",
    "mmn_supplementation.yaml",
    "danger_signs.yaml",
)


def load(name):
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(params=CLINICAL_FILES)
def clinical_file(request):
    return request.param, load(request.param)


# --- the contract every clinical file must satisfy --------------------------------------


def test_every_clinical_file_has_a_provenance_block(clinical_file):
    name, data = clinical_file
    assert isinstance(data.get("provenance"), dict), f"{name} has no provenance block"


def test_every_clinical_file_declares_a_recognised_status(clinical_file):
    name, data = clinical_file
    assert data.get("status") in (provenance.SOURCED, provenance.PLACEHOLDER), f"{name} has an unrecognised status"


def test_a_file_claiming_sourced_must_have_complete_provenance(clinical_file):
    name, data = clinical_file
    if provenance.is_sourced(data):
        assert provenance.provenance_problems(data) == [], f"{name} claims sourced with incomplete provenance"


def test_no_clinical_file_cites_a_banned_re_upload(clinical_file):
    # Copies of these documents are on Scribd and are convenient. They are unverifiable
    # re-uploads of unknown vintage, so citing one is never acceptable.
    name, data = clinical_file
    raw = (DATA_DIR / name).read_text(encoding="utf-8").lower()
    for host in provenance.BANNED_HOSTS:
        assert host not in raw, f"{name} cites banned host {host}"


def test_clinician_review_is_declared(clinical_file):
    name, data = clinical_file
    assert str(data["provenance"].get("clinician_review", "")).strip(), f"{name} does not state its review status"


# --- the shipped state, recorded so a change is deliberate ------------------------------


def test_all_clinical_files_currently_ship_as_placeholders(clinical_file):
    # This test failing is the expected, wanted outcome once real values land. Update it in
    # the same commit that flips the status, so the flip is never silent.
    name, data = clinical_file
    assert data["status"] == provenance.PLACEHOLDER, f"{name} is no longer a placeholder - update this test"


# --- the validator itself ---------------------------------------------------------------


def complete_provenance(**overrides):
    block = {
        "source": "National Immunization Schedule - Sri Lanka",
        "publisher": "Epidemiology Unit, Ministry of Health, Sri Lanka",
        "document_date": "2017",
        "url": "https://www.epid.gov.lk/storage/post/pdfs/example.pdf",
        "retrieved": "2026-09-02",
        "cross_checked_against": "CHDR, physical copy",
        "clinician_review": "NOT PERFORMED.",
    }
    block.update(overrides)
    return {"provenance": block, "status": provenance.SOURCED}


def test_complete_provenance_has_no_problems():
    assert provenance.provenance_problems(complete_provenance()) == []


def test_missing_block_is_a_problem():
    assert provenance.provenance_problems({"status": "sourced"}) == ["no provenance block"]


@pytest.mark.parametrize("field", provenance.REQUIRED_FIELDS)
def test_each_field_is_required(field):
    problems = provenance.provenance_problems(complete_provenance(**{field: ""}))
    assert any(field in problem for problem in problems)


@pytest.mark.parametrize("field", provenance.REQUIRED_FIELDS)
def test_a_field_left_as_todo_is_a_problem(field):
    problems = provenance.provenance_problems(complete_provenance(**{field: "TODO"}))
    assert any(field in problem for problem in problems)


def test_a_scribd_url_is_rejected():
    problems = provenance.provenance_problems(complete_provenance(url="https://www.scribd.com/document/123/mcp"))
    assert any("banned re-upload" in problem for problem in problems)


def test_a_non_government_url_is_rejected():
    problems = provenance.provenance_problems(complete_provenance(url="https://example.com/schedule.pdf"))
    assert any("not a" in problem for problem in problems)


def test_a_who_url_is_accepted():
    assert provenance.provenance_problems(complete_provenance(url="https://www.who.int/publications/x")) == []


def test_the_old_epid_domain_is_still_accepted_but_must_be_dated():
    # old.epid.gov.lk is a .gov.lk host, so the URL check alone will not catch a stale
    # document. document_date is what catches it, which is why it is required.
    data = complete_provenance(url="http://old.epid.gov.lk/web/attachments/article/138/Immunization_Schedule.pdf")
    assert provenance.provenance_problems(data) == []
    assert data["provenance"]["document_date"], "document_date is the only guard against a stale official PDF"


# --- is_sourced is strict ---------------------------------------------------------------


@pytest.mark.parametrize("status", ["sourcedd", "Sourced", " sourced", "reviewed", "", None, True, 1])
def test_only_the_exact_string_counts_as_sourced(status):
    assert provenance.is_sourced({"status": status}) is False


def test_the_exact_string_counts():
    assert provenance.is_sourced({"status": "sourced"}) is True
