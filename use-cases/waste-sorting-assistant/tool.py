from __future__ import annotations

import copy
import json
import re
from typing import Any

from agentkernel.core import ToolContext

SESSION_REGION_KEY = "waste_sorting.region"
SESSION_REGION_RULES_KEY = "waste_sorting.region_rules"
FOOD_SCRAPS = "food scraps"
MIXED_MATERIAL = "mixed material"
RIGID_PLASTIC = "rigid plastic"

DISPOSAL_RULES: dict[str, Any] = {
    "base_materials": {
        "aluminum": {
            "category": "recycle",
            "instructions": "Rinse the container and place it loose in the recycling bin.",
            "examples": ["aluminum can", "foil tray", "clean foil"],
        },
        "battery": {
            "category": "hazardous waste",
            "instructions": (
                "Do not place batteries in curbside bins. Take them to a battery or hazardous-waste drop-off site."
            ),
            "examples": ["AA battery", "lithium battery", "button cell"],
        },
        "cardboard": {
            "category": "recycle",
            "instructions": "Flatten boxes and keep cardboard dry and free of food residue.",
            "examples": ["shipping box", "cereal box", "paperboard package"],
        },
        "carton": {
            "category": "check local rules",
            "instructions": "Carton acceptance varies. Rinse and cap cartons only if your local program accepts them.",
            "examples": ["milk carton", "juice carton", "soup carton"],
        },
        "electronics": {
            "category": "e-waste",
            "instructions": "Use an e-waste collection event, retailer take-back, or municipal electronics drop-off.",
            "examples": ["phone", "charger", "keyboard"],
        },
        FOOD_SCRAPS: {
            "category": "compost",
            "instructions": "Place food scraps in the organics or compost bin where available.",
            "examples": ["apple core", "coffee grounds", "vegetable peels"],
        },
        "glass": {
            "category": "recycle",
            "instructions": "Empty and rinse bottles or jars. Do not include ceramics, mirrors, or light bulbs.",
            "examples": ["glass bottle", "sauce jar", "jam jar"],
        },
        MIXED_MATERIAL: {
            "category": "landfill",
            "instructions": (
                "If the item combines materials that cannot be separated, place it in landfill unless a local program "
                "accepts it."
            ),
            "examples": ["chip bag", "laminated pouch", "waxed wrapper"],
        },
        "paper": {
            "category": "recycle",
            "instructions": "Recycle clean, dry paper. Compost or landfill paper that is wet or heavily food-soiled.",
            "examples": ["newspaper", "office paper", "mail"],
        },
        "plastic film": {
            "category": "store drop-off",
            "instructions": (
                "Keep plastic film out of curbside recycling unless your region explicitly accepts it. Use grocery-store "
                "film drop-off when available."
            ),
            "examples": ["plastic bag", "bread bag", "bubble wrap"],
        },
        RIGID_PLASTIC: {
            "category": "recycle",
            "instructions": "Recycle only if the shape and resin code are accepted locally. Empty and rinse containers.",
            "examples": ["plastic bottle", "yogurt tub", "detergent jug"],
        },
        "textile": {
            "category": "reuse or textile recycling",
            "instructions": "Donate wearable items. Use textile recycling for damaged fabric if available.",
            "examples": ["shirt", "towel", "pair of jeans"],
        },
    },
    "regions": {
        "default": {
            "name": "Default local rules",
            "notes": "Rules vary by municipality. Confirm edge cases with your local waste authority.",
            "accepted_materials": ["aluminum", "cardboard", "glass", "paper", RIGID_PLASTIC],
            "overrides": {},
        },
        "austin, tx": {
            "name": "Austin, TX",
            "notes": "Austin supports curbside recycling and separate composting for many households.",
            "accepted_materials": ["aluminum", "cardboard", FOOD_SCRAPS, "glass", "paper", RIGID_PLASTIC],
            "overrides": {
                "plastic film": {
                    "category": "store drop-off",
                    "instructions": (
                        "Do not place plastic bags or wrap in Austin curbside recycling. Use store drop-off or landfill "
                        "if no drop-off is available."
                    ),
                }
            },
        },
        "london, uk": {
            "name": "London, UK",
            "notes": "Borough rules differ, so borough-specific instructions should override these defaults when known.",
            "accepted_materials": ["aluminum", "cardboard", "glass", "paper", RIGID_PLASTIC],
            "overrides": {
                FOOD_SCRAPS: {
                    "category": "food waste collection",
                    "instructions": "Use your council food-waste caddy if provided. Otherwise follow borough guidance.",
                }
            },
        },
        "san francisco, ca": {
            "name": "San Francisco, CA",
            "notes": "San Francisco uses blue recycling, green compost, and black landfill bins.",
            "accepted_materials": ["aluminum", "cardboard", FOOD_SCRAPS, "glass", "paper", RIGID_PLASTIC],
            "overrides": {
                MIXED_MATERIAL: {
                    "category": "landfill",
                    "instructions": (
                        "Place mixed-material wrappers and pouches in the black landfill bin unless the materials can be "
                        "separated."
                    ),
                }
            },
        },
    },
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _load_rules() -> dict[str, Any]:
    return copy.deepcopy(DISPOSAL_RULES)


def _get_session_region() -> str | None:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        cached_region = cache.get(SESSION_REGION_KEY)
        if cached_region:
            return str(cached_region)
    except RuntimeError:
        pass

    return None


def _set_session_region(region: str) -> None:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        cache.set(SESSION_REGION_KEY, region)
    except RuntimeError:
        pass


def _get_session_region_overrides(region: str) -> dict[str, dict[str, str]]:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        region_rules = cache.get(SESSION_REGION_RULES_KEY, {})
        if isinstance(region_rules, dict):
            return region_rules.get(region, {})
        return {}
    except RuntimeError:
        return {}


def _set_session_region_rule(region: str, material: str, category: str, instructions: str) -> None:
    try:
        cache = ToolContext.get().session.get_non_volatile_cache()
        region_rules = cache.get(SESSION_REGION_RULES_KEY, {})
        if not isinstance(region_rules, dict):
            region_rules = {}
        region_rules.setdefault(region, {})[material] = {
            "category": category,
            "instructions": instructions,
            "source": "session_memory",
        }
        cache.set(SESSION_REGION_RULES_KEY, region_rules)
    except RuntimeError:
        pass


def _match_material(item: str, material: str, rules: dict[str, Any]) -> str:
    normalized_material = _normalize(material)
    if normalized_material in rules["base_materials"]:
        return normalized_material

    normalized_item = _normalize(item)
    for material_name, details in rules["base_materials"].items():
        examples = [_normalize(example) for example in details.get("examples", [])]
        if material_name in normalized_item or any(example in normalized_item for example in examples):
            return material_name

    return MIXED_MATERIAL


def _build_lookup(item: str, material: str, region: str | None = None) -> dict[str, Any]:
    rules = _load_rules()
    resolved_material = _match_material(item, material, rules)
    resolved_region = _normalize(region or _get_session_region() or "default")
    if resolved_region not in rules["regions"]:
        rules["regions"][resolved_region] = {
            "name": region or resolved_region.title(),
            "notes": "No built-in municipal profile is available yet. Using remembered local rules and default guidance.",
            "accepted_materials": rules["regions"]["default"]["accepted_materials"],
            "overrides": {},
        }

    region_rules = rules["regions"][resolved_region]
    memory_overrides = _get_session_region_overrides(resolved_region)
    override = memory_overrides.get(resolved_material) or region_rules.get("overrides", {}).get(resolved_material)
    base = rules["base_materials"][resolved_material]

    category = override.get("category") if override else base["category"]
    instructions = override.get("instructions") if override else base["instructions"]
    source = override.get("source", "regional_profile") if override else "base_material"

    if resolved_material not in region_rules["accepted_materials"] and not override:
        category = "check local rules"
        instructions = (
            f"{region_rules['name']} does not list {resolved_material} as accepted in the built-in profile. "
            f"Default guidance: {base['instructions']}"
        )

    _set_session_region(resolved_region)

    return {
        "item": item,
        "material": resolved_material,
        "region": region_rules["name"],
        "category": category,
        "instructions": instructions,
        "rule_source": source,
        "regional_notes": region_rules["notes"],
    }


def lookup_disposal_category(item: str, material: str, region: str = "") -> str:
    """Look up the recommended disposal category for an item, material, and optional local region."""
    return json.dumps(_build_lookup(item=item, material=material, region=region or None), indent=2)


def remember_region_rule(region: str, material: str, category: str, instructions: str) -> str:
    """Remember a region-specific disposal rule supplied by the user for future lookups."""
    normalized_region = _normalize(region)
    normalized_material = _normalize(material)
    _set_session_region_rule(normalized_region, normalized_material, _normalize(category), instructions.strip())
    _set_session_region(normalized_region)
    return (
        f"Remembered rule for {normalized_material} in {normalized_region}: "
        f"{_normalize(category)} - {instructions.strip()}"
    )


def get_region_memory(region: str = "") -> str:
    """Return remembered local disposal rules for a region, or for the active session region."""
    resolved_region = _normalize(region or _get_session_region() or "default")
    overrides = _get_session_region_overrides(resolved_region)
    return json.dumps({"region": resolved_region, "remembered_rules": overrides}, indent=2)
