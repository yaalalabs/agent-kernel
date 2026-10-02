"""The platform extras ship what both serverless Lambdas import (#760 Q5).

A static guard over ``pyproject.toml``: the development venv has every extra installed, so an
import test here could not notice a dependency missing from an extra.
"""

import re
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
WEBHOOK_EXTRAS = ["slack", "teams", "telegram", "whatsapp", "messenger", "instagram"]


def _requirement_names(extra: str) -> set[str]:
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    return {re.split(r"[\s<>=!~\[;]", requirement, maxsplit=1)[0].lower() for requirement in extras[extra]}


@pytest.mark.parametrize("extra", WEBHOOK_EXTRAS)
def test_each_webhook_platform_extra_ships_fastapi(extra):
    assert "fastapi" in _requirement_names(extra)


def test_the_slack_extra_ships_aiohttp():
    assert "aiohttp" in _requirement_names("slack")


def test_the_gmail_extra_stays_fastapi_free():
    assert "fastapi" not in _requirement_names("gmail")
