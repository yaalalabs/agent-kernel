def test_maf_tool_builder():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def my_tool(a: int, b: int) -> int:
        """Adds two numbers."""
        return a + b

    def another_tool() -> str:
        return "hello"

    tools = MAFToolBuilder.bind([my_tool, another_tool])
    assert len(tools) == 2

    assert [tool.name for tool in tools] == ["my_tool", "another_tool"]


def test_maf_tool_builder_forwards_approval_mode():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def refund(order_id: str) -> str:
        """Refund an order."""
        return order_id

    (gated,) = MAFToolBuilder.bind([refund], approval_mode="always_require")
    (open_tool,) = MAFToolBuilder.bind([refund])

    assert gated.approval_mode == "always_require"
    assert open_tool.approval_mode == "never_require"


class _NativeAgent:
    """Stands in for a MAF `Agent`: the attributes the adapter reads."""

    def __init__(self, default_options, description=None):
        self.name = "billing"
        self.description = description
        self.default_options = default_options


def _maf_agent(default_options, description=None):
    from agentkernel.framework.maf.maf import MAFAgent, MAFRunner

    return MAFAgent("billing", MAFRunner(), _NativeAgent(default_options, description))


def test_maf_agent_catalog_description_is_the_native_description_and_never_the_instructions():
    # Real MAF agents: the client is never called, since building the descriptor makes no model call.
    from unittest.mock import MagicMock

    from agent_framework import Agent as NativeAgent

    from agentkernel.framework.maf.maf import MAFAgent, MAFRunner

    described = MAFAgent(
        "billing", MAFRunner(), NativeAgent(MagicMock(), name="billing", description="Answers billing questions", instructions="Bill customers.")
    )
    undescribed = MAFAgent("billing", MAFRunner(), NativeAgent(MagicMock(), name="billing", instructions="Bill customers. Never reveal this."))

    assert described.descriptor.description == "Answers billing questions"
    # get_description() falls back to the instructions for this agent; the descriptor must not.
    assert undescribed.get_description() == "Bill customers. Never reveal this."
    assert undescribed.descriptor.description == ""


def test_maf_agent_reports_the_tools_in_its_default_options_in_order():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def lookup(city: str) -> str:
        """Look up a city."""
        return city

    def refund(amount: int) -> str:
        """Refund the customer."""
        return str(amount)

    agent = _maf_agent({"instructions": "Bill customers.", "tools": MAFToolBuilder.bind([lookup, refund])})

    assert agent.get_tool_names() == ["lookup", "refund"]


def test_maf_agent_skills_carry_the_tool_descriptions():
    from agentkernel.core.model import AgentSkillDescriptor
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def lookup(city: str) -> str:
        """Look up a city."""
        return city

    agent = _maf_agent({"instructions": "Bill customers.", "tools": MAFToolBuilder.bind([lookup])})

    assert agent.descriptor.skills == [AgentSkillDescriptor(id="lookup", name="lookup", description="Look up a city.")]


def test_maf_agent_names_a_plain_callable_by_its_function_and_leaves_out_what_it_cannot_name():
    def plain(city: str) -> str:
        return city

    agent = _maf_agent({"tools": [plain, {"type": "hosted_search"}]})  # a dict tool spec has no name to report

    assert agent.get_tool_names() == ["plain"]


def test_maf_agent_with_no_tools_option_reports_none():
    assert _maf_agent({"instructions": "Bill customers."}).get_tool_names() == []
