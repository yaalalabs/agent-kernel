import pytest

import phm_registry


@pytest.mark.parametrize(
    "contents", ["", "[", "phms: bad", "phms: [null]", "phms: [{phone: 94112223344, moh_areas: [Colombo]}]"]
)
def test_invalid_registry_denies_access(approved_registry, contents):
    approved_registry.write_text(contents, encoding="utf-8")
    assert not phm_registry.is_approved("94112223344")


def test_missing_registry_denies_access(monkeypatch, tmp_path):
    monkeypatch.setenv(phm_registry.REGISTRY_ENV, str(tmp_path / "missing.yaml"))
    assert not phm_registry.is_approved("94112223344")


def test_moh_area_matching_ignores_case_and_surrounding_spaces():
    assert phm_registry.is_approved("94112223344", " colombo ")
    assert not phm_registry.is_approved("94112223344", "Gampaha")
