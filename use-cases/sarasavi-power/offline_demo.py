"""Keyless Sarasavi Power product demo.

This deterministic fallback exercises the same consumption and tariff engine as
the Agent Kernel tools. It deliberately does not imitate the conversational
agents; use ``demo.py`` for that. It gives judges a complete, reproducible user
journey before Gemini or Meta credentials are configured.

Examples:
    uv run python offline_demo.py
    uv run python offline_demo.py --units 61 --days 30
    uv run python offline_demo.py --appliance refrigerator:24 --appliance air_conditioner:5
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Sequence

from engine import boundary_opportunities, compute_bill, estimate_total, load_appliances
from localization import appliance_name, configure_utf8_console, currency_word, normalize_language, ui_text

SAMPLE_APPLIANCES = (
    "refrigerator:24",
    "ceiling_fan:8:2",
    "led_bulb:5:6",
    "tv_led:4",
    "iron:0.5",
)


@dataclass(frozen=True)
class DemoInput:
    appliances: list[dict]
    billing_days: int
    metered_units: float | None


def parse_appliance(spec: str) -> dict:
    """Parse ``KEY:HOURS[:QUANTITY]`` into an engine usage record."""
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) not in (2, 3):
        raise ValueError(f"invalid appliance '{spec}'; use KEY:HOURS[:QUANTITY]")

    key = parts[0].lower().replace(" ", "_").replace("-", "_")
    catalog = load_appliances()
    if key not in catalog:
        raise ValueError(f"unknown appliance '{parts[0]}'; use --list-appliances to see valid keys")

    try:
        hours = float(parts[1])
        quantity = int(parts[2]) if len(parts) == 3 else 1
    except ValueError as exc:
        raise ValueError(f"invalid number in appliance '{spec}'") from exc
    if not 0 <= hours <= 24:
        raise ValueError(f"hours must be between 0 and 24 in '{spec}'")
    if not 1 <= quantity <= 100:
        raise ValueError(f"quantity must be between 1 and 100 in '{spec}'")
    return {"key": key, "hours_per_day": hours, "quantity": quantity}


def build_report(demo_input: DemoInput) -> dict:
    """Return the complete deterministic report used by text and JSON output."""
    if not 1 <= demo_input.billing_days <= 366:
        raise ValueError("billing days must be between 1 and 366")
    if demo_input.metered_units is not None and demo_input.metered_units < 0:
        raise ValueError("metered units must be zero or greater")

    usages = [{**item, "days": demo_input.billing_days} for item in demo_input.appliances]
    estimate: dict[str, Any] = estimate_total(usages) if usages else {"total_kwh": 0.0, "breakdown": []}
    if demo_input.metered_units is not None:
        source = "metered"
        units = float(demo_input.metered_units)
    else:
        source = "estimated"
        units = float(estimate["total_kwh"])
    bill = compute_bill(units, billing_days=demo_input.billing_days)
    opportunities = boundary_opportunities(units, billing_days=demo_input.billing_days)
    return {
        "billing_days": demo_input.billing_days,
        "units": units,
        "units_source": source,
        "estimate": estimate,
        "bill": bill,
        "top_boundary_opportunity": opportunities[0] if opportunities else None,
    }


def render_report(report: dict, language: str = "en") -> str:
    language = normalize_language(language)
    bill = report["bill"]
    source_label = ui_text(language, "metered" if report["units_source"] == "metered" else "estimated")
    banner = ui_text(language, "banner")
    lines = [
        banner,
        "=" * len(banner),
        f"{ui_text(language, 'billing_period')} : {report['billing_days']} {ui_text(language, 'days')}",
        f"{ui_text(language, 'usage')} : {report['units']:.2f} kWh ({source_label})",
        f"{ui_text(language, 'tariff_slab')} : {bill['slab']} "
        f"({ui_text(language, 'effective')} {bill['effective_date']})",
        f"{ui_text(language, 'bill')} : {currency_word(language)} {bill['total']:,.2f}",
    ]

    breakdown = report["estimate"]["breakdown"]
    if breakdown:
        lines.extend(["", ui_text(language, "loads")])
        for item in breakdown[:3]:
            name = appliance_name(item["key"], language, item["name"])
            lines.append(f"  - {name}: {item['kwh']:.2f} kWh ({item['share_pct']:.1f}%)")

    opportunity = report["top_boundary_opportunity"]
    lines.extend(["", ui_text(language, "opportunity")])
    if opportunity:
        lines.append(
            "  "
            + ui_text(language, "cut").format(
                cut=opportunity["units_to_cut"],
                target=opportunity["target_units"],
                bill=opportunity["new_bill"],
                saving=opportunity["savings"],
            )
        )
    else:
        lines.append(f"  {ui_text(language, 'no_opportunity')}")

    lines.extend(
        [
            "",
            ui_text(language, "disclaimer"),
            ui_text(language, "next"),
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sarasavi Power without API credentials.")
    parser.add_argument(
        "--appliance",
        action="append",
        default=[],
        metavar="KEY:HOURS[:QUANTITY]",
        help="appliance usage; repeat for multiple appliances",
    )
    parser.add_argument("--units", type=float, help="actual units from a bill or meter (optional)")
    parser.add_argument("--days", type=int, default=30, help="billing-period days (default: 30)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--language", choices=("en", "si", "ta"), default="en", help="output language")
    parser.add_argument("--list-appliances", action="store_true", help="list valid appliance keys and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_appliances:
        for key, appliance in sorted(load_appliances().items()):
            print(f"{key:22} {appliance_name(key, args.language, appliance.name)}")
        return 0

    if args.appliance:
        specs = args.appliance
    elif args.units is None:
        specs = list(SAMPLE_APPLIANCES)
    else:
        specs = []
    try:
        appliances = [parse_appliance(spec) for spec in specs]
        report = build_report(DemoInput(appliances, args.days, args.units))
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_report(report, args.language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
