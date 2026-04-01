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


def test_a2a_card_dict_tools():
    from a2a.types import AgentCard

    from agentkernel.framework.smolagents.smolagents import SmolagentsAgent, SmolagentsRunner

    class MockTool:
        name = "mock_tool"
        description = "A mock tool for tests"

    class MockAgent:
        tools = {"mock_tool": MockTool()}
        system_prompt = "Mock agent description"
        name = "mock_agent"

    wrapper = SmolagentsAgent("mock_agent", SmolagentsRunner(), MockAgent())
    card = wrapper.get_a2a_card()

    assert isinstance(card, AgentCard)
    assert len(card.skills) == 1
    assert card.skills[0].name == "mock_tool"


def test_smolagents_module_runner_init():
    from agentkernel.core.config import AKConfig
    from agentkernel.framework.smolagents.smolagents import SmolagentsModule, SmolagentsRunner

    # Under standard un-traced testing context, runner should instantiate as SmolagentsRunner
    AKConfig.get().trace.enabled = False
    module = SmolagentsModule([])
    assert isinstance(module.runner, SmolagentsRunner)
