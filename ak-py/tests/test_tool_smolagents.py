import pytest

from agentkernel.framework.smolagents.smolagents import SmolagentsToolBuilder


def get_weather(city: str) -> str:
    """Returns the weather for a given city.

    Args:
        city: The target city.
    """
    return f"Weather in {city}: sunny"


def test_bind_returns_list():
    tools = SmolagentsToolBuilder.bind([get_weather])
    assert isinstance(tools, list)
    assert len(tools) == 1


def test_bind_non_callable_string_raises():
    with pytest.raises(TypeError, match="Expected a callable"):
        SmolagentsToolBuilder.bind(["not a function"])


def test_smolagents_module_runner_init():
    from agentkernel.core.config import AKConfig
    from agentkernel.framework.smolagents.smolagents import SmolagentsModule, SmolagentsRunner

    # Under standard un-traced testing context, runner should instantiate as SmolagentsRunner
    AKConfig.get().trace.enabled = False
    module = SmolagentsModule([])
    assert isinstance(module.runner, SmolagentsRunner)


def test_override_system_prompt_uses_prompt_templates_for_readonly_system_prompt():
    from agentkernel.framework.smolagents.smolagents import SmolagentsAgent, SmolagentsRunner

    class ReadOnlySystemPromptAgent:
        name = "readonly_code_agent"
        tools = []
        description = "A code-agent style wrapper"

        def __init__(self):
            self.prompt_templates = {"system_prompt": "base"}

        @property
        def system_prompt(self):
            return self.prompt_templates["system_prompt"]

        @system_prompt.setter
        def system_prompt(self, value):
            raise AttributeError("The 'system_prompt' property is read-only")

    wrapper = SmolagentsAgent("readonly_code_agent", SmolagentsRunner(), ReadOnlySystemPromptAgent())
    wrapper.override_system_prompt("extra-guidance")

    assert "extra-guidance" in wrapper.agent.prompt_templates["system_prompt"]
