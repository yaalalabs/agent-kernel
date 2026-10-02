from __future__ import annotations

import pytest

from offline_demo import DemoInput, build_report, parse_appliance, render_report


def test_keyless_demo_uses_metered_units_for_boundary_advice() -> None:
    report = build_report(
        DemoInput(
            appliances=[parse_appliance("refrigerator:24")],
            billing_days=30,
            metered_units=61,
        )
    )

    assert report["units_source"] == "metered"
    assert report["bill"]["total"] == 1260.0
    assert report["top_boundary_opportunity"]["units_to_cut"] == 1.0
    assert "save LKR 630.00" in render_report(report)


def test_keyless_demo_uses_appliance_estimate_without_meter_reading() -> None:
    report = build_report(
        DemoInput(
            appliances=[parse_appliance("refrigerator:24"), parse_appliance("led_bulb:5:6")],
            billing_days=30,
            metered_units=None,
        )
    )

    assert report["units_source"] == "estimated"
    assert report["units"] == pytest.approx(45.9)
    assert report["bill"]["total"] == pytest.approx(503.1)


@pytest.mark.parametrize("spec", ["unknown:2", "refrigerator", "refrigerator:25", "refrigerator:2:0"])
def test_keyless_demo_rejects_invalid_appliance_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_appliance(spec)


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Estimated bill"), ("si", "ඇස්තමේන්තුගත බිල"), ("ta", "மதிப்பிடப்பட்ட கட்டணம்")],
)
def test_keyless_demo_renders_all_supported_languages(language: str, expected: str) -> None:
    report = build_report(DemoInput([parse_appliance("refrigerator:24")], 30, None))

    assert expected in render_report(report, language)


@pytest.mark.parametrize(("language", "word"), [("si", "රුපියල්"), ("ta", "ரூபாய்")])
def test_sinhala_and_tamil_renders_never_write_lkr(language: str, word: str) -> None:
    report = build_report(DemoInput([parse_appliance("refrigerator:24")], 30, 61))

    rendered = render_report(report, language)

    assert word in rendered
    assert "LKR" not in rendered
