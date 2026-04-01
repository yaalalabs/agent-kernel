import pytest

from agentkernel.framework.smolagents.smolagents import SmolagentsToolBuilder


def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny"


def test_bind_returns_list():
    tools = SmolagentsToolBuilder.bind([get_weather])
    assert isinstance(tools, list)
    assert len(tools) == 1


def test_bind_non_callable_string_raises():
    with pytest.raises(TypeError, match="Expected a callable"):
        SmolagentsToolBuilder.bind(["not a function"])
