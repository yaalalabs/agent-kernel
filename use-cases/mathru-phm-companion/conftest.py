"""Isolate operator approvals from a developer's real registry in all unit tests."""

import pytest
import yaml

import phm_registry


@pytest.fixture(autouse=True)
def approved_registry(tmp_path, monkeypatch):
    path = tmp_path / "phm_registry.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "phms": [
                    {"phone": "94112223344", "moh_areas": ["Colombo"]},
                    {"phone": "94119998888", "moh_areas": ["Colombo"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(phm_registry.REGISTRY_ENV, str(path))
    return path
