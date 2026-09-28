"""Operator-managed PHM approvals, independent of mother registration.

Reload on every check so removing an entry revokes access without a restart. This file is
never writable through an agent tool. Missing or malformed configuration denies access.
"""

import logging
import os
import re
from pathlib import Path

import yaml

REGISTRY_ENV = "MATHRU_PHM_REGISTRY"
DEFAULT_PATH = Path(__file__).with_name("phm_registry.yaml")
log = logging.getLogger("mathru.phm_registry")


def approved_areas(phone: str) -> set[str]:
    """Return the approved MOH areas for a verified number, or an empty set."""
    try:
        path = Path(os.environ.get(REGISTRY_ENV) or DEFAULT_PATH)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("phms"), list):
            raise ValueError("expected a phms list")
        registry = {}
        for entry in data["phms"]:
            if not isinstance(entry, dict):
                raise ValueError("expected a PHM mapping")
            number, areas = entry.get("phone"), entry.get("moh_areas")
            if not isinstance(number, str) or not re.fullmatch(r"94[0-9]{9}", number):
                raise ValueError("expected a quoted Sri Lankan phone number")
            if number in registry or not isinstance(areas, list) or not areas:
                raise ValueError("duplicate PHM or missing MOH areas")
            if any(not isinstance(area, str) or not area.strip() for area in areas):
                raise ValueError("invalid MOH area")
            registry[number] = {area.strip().casefold() for area in areas}
        return registry.get(phone, set())
    except (OSError, ValueError, yaml.YAMLError):
        log.error("PHM registry unavailable or invalid; denying PHM access and delivery")
        return set()


def is_approved(phone: str, moh_area: str | None = None) -> bool:
    areas = approved_areas(phone)
    return bool(areas) if moh_area is None else moh_area.strip().casefold() in areas
