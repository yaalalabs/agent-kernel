import logging
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestText, SystemTool
from agentkernel.core.tool import SystemToolFactory


class MockRunner(Runner):

    def __init__(self, name: str):
        super().__init__(name)

    @property
    def supports_streaming(self) -> bool:
        return True

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        return AgentReply(content="mock-reply")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


def test_runner_init():
    runner = MockRunner("test-runner")
    assert runner.name == "test-runner"
    assert repr(runner) == "Runner(test-runner)"


class MockAgent(Agent):

    def __init__(self, name: str, runner: Runner):
        super().__init__(name, runner)

    def get_description(self) -> str:
        return "Mock Agent"

    def get_a2a_card(self) -> Any:
        return "Mock A2A Card"

    def override_system_prompt(self, prompt: str) -> None:
        pass

    def attach_tool(self, tool: Any) -> None:
        pass


def test_agent_init():
    runner = MockRunner("test-runner")
    agent = MockAgent("test-agent", runner)
    assert agent.name == "test-agent"
    assert agent.runner == runner
    assert repr(agent) == "Agent(test-agent)"
    assert agent.get_description() == "Mock Agent"
    assert agent.get_a2a_card() == "Mock A2A Card"


def test_agent_hooks():
    runner = MockRunner("test-runner")
    agent = MockAgent("test-agent", runner)

    pre_hook_1 = lambda req: req
    pre_hook_2 = lambda req: req
    post_hook_1 = lambda rep: rep
    post_hook_2 = lambda rep: rep

    agent.pre_hooks.extend([pre_hook_1, pre_hook_2])
    agent.post_hooks.extend([post_hook_1, post_hook_2])

    assert pre_hook_1 in agent.pre_hooks
    assert pre_hook_2 in agent.pre_hooks
    assert post_hook_1 in agent.post_hooks
    assert post_hook_2 in agent.post_hooks


def test_agent_current_default_none():
    assert Agent.current() is None


def test_agent_activate_sets_and_resets_current():
    agent = MockAgent("test-agent", MockRunner("test-runner"))
    assert Agent.current() is None
    with agent._activate():
        assert Agent.current() is agent
    assert Agent.current() is None


def test_agent_activate_resets_on_exception():
    agent = MockAgent("test-agent", MockRunner("test-runner"))
    try:
        with agent._activate():
            raise ValueError("boom")
    except ValueError:
        pass
    assert Agent.current() is None


def test_agent_activate_nested_restores_previous_agent():
    outer = MockAgent("outer-agent", MockRunner("outer-runner"))
    inner = MockAgent("inner-agent", MockRunner("inner-runner"))
    with outer._activate():
        assert Agent.current() is outer
        with inner._activate():
            assert Agent.current() is inner
        assert Agent.current() is outer
    assert Agent.current() is None


def test_get_framework_session_requires_current_agent():
    session = Session("test-session")
    with pytest.raises(RuntimeError):
        session.get_framework_session()


def test_get_framework_session_returns_none_when_not_stored():
    agent = MockAgent("test-agent", MockRunner("openai"))
    session = Session("test-session")
    with agent._activate():
        assert session.get_framework_session() is None


def test_get_framework_session_returns_value_keyed_by_runner_name():
    agent = MockAgent("test-agent", MockRunner("openai"))
    session = Session("test-session")
    session.set("openai", "native-openai-session")
    with agent._activate():
        assert session.get_framework_session() == "native-openai-session"


def test_get_framework_session_scoped_to_current_agents_runner_name():
    """A framework session stored under a different runner name is not returned."""
    agent = MockAgent("test-agent", MockRunner("langgraph"))
    session = Session("test-session")
    session.set("openai", "native-openai-session")
    with agent._activate():
        assert session.get_framework_session() is None


class ToolCarryingAgent(MockAgent):
    """An agent exposing a framework-native agent whose `tools` carries names.

    Both shapes the adapters use are supported: a list of tool objects, and the name-keyed
    mapping smolagents holds (`SmolagentsAgent._append_tools` writes `agent.tools[name] = tool`).
    """

    def __init__(self, name: str, runner: Runner, tool_names: list, as_mapping: bool = False):
        tools = {n: SimpleNamespace(name=n) for n in tool_names} if as_mapping else [SimpleNamespace(name=n) for n in tool_names]
        self._native = SimpleNamespace(tools=tools)
        self.attached: list = []
        super().__init__(name, runner)

    @property
    def agent(self) -> Any:
        return self._native

    def attach_tool(self, tool: Any) -> None:
        self.attached.append(tool)


def _system_tool(name: str):
    def func():
        return name

    func.__name__ = name
    return SystemTool(name=name, description="", func=func)


class TestSystemToolNameCollisions:
    """Warn when a capability's system tool shadows one the application bound by hand (#553).

    Attaching anyway is the deliberate choice: skipping would make newly enabling a capability
    silently do nothing for that agent, which is the worse of the two failures.
    """

    def test_a_collision_warns_and_still_attaches(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            agent = ToolCarryingAgent("kb-agent", MockRunner("r"), ["read_kb", "write_kb"])
            agent._attach_system_tools()

        assert "kb-agent" in caplog.text
        assert "read_kb" in caplog.text
        assert [tool.__name__ for tool in agent.attached] == ["read_kb"]

    def test_the_warning_names_only_the_colliding_tools(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb"), _system_tool("browse_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            ToolCarryingAgent("kb-agent", MockRunner("r"), ["read_kb"])._attach_system_tools()

        assert "['read_kb']" in caplog.text

    def test_no_overlap_is_silent(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("browse_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            ToolCarryingAgent("kb-agent", MockRunner("r"), ["something_else"])._attach_system_tools()

        assert caplog.text == ""

    def test_an_agent_exposing_no_native_tools_attribute_warns_nothing(self, monkeypatch, caplog):
        # Entirely defensive: not every adapter exposes a `tools` collection, and a missing one
        # must mean no warning, never a raise.
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            agent = MockAgent("plain-agent", MockRunner("r"))
            agent._attach_system_tools()

        assert caplog.text == ""

    def test_a_collision_is_detected_in_a_name_keyed_tools_mapping(self, monkeypatch, caplog):
        # Smolagents keys its tools by name, so iterating `tools` directly yields plain strings
        # whose .name and .__name__ are both None — every name was filtered out and the warning
        # never fired on that framework at all.
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            ToolCarryingAgent("kb-agent", MockRunner("r"), ["read_kb", "write_kb"], as_mapping=True)._attach_system_tools()

        assert "['read_kb']" in caplog.text

    def test_a_tools_attribute_that_is_not_a_collection_warns_nothing(self, monkeypatch, caplog):
        # The other half of "never a raise": an adapter meaning something else entirely by
        # `tools` must not take agent construction down with a TypeError.
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        agent = MockAgent("odd-agent", MockRunner("r"))
        monkeypatch.setattr(type(agent), "agent", property(lambda self: SimpleNamespace(tools=object())), raising=False)

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            agent._attach_system_tools()

        assert caplog.text == ""


class TestAgentRunOptions:
    """Agent.run_options / RESERVED_RUN_OPTIONS / validate_run_options (spec #754, Agent section)."""

    def test_fresh_agent_has_empty_live_run_options_and_reserves_nothing(self):
        agent = MockAgent("test-agent", MockRunner("test-runner"))

        assert agent.run_options == {}
        assert agent.run_options is agent.run_options  # a live dict, not a copy per read
        assert MockAgent.RESERVED_RUN_OPTIONS == {}

    def test_validate_rejects_a_reserved_key_naming_runner_agent_key_and_reason(self):
        class Reserving(MockAgent):
            RESERVED_RUN_OPTIONS = {"context": "populated from framework_context"}

        agent = Reserving("test-agent", MockRunner("test-runner"))

        with pytest.raises(ValueError) as exc:
            agent.validate_run_options({"context": {"k": 1}, "max_turns": 5})

        message = str(exc.value)
        assert "test-runner" in message
        assert "test-agent" in message
        assert "'context'" in message
        assert "populated from framework_context" in message
        assert "max_turns" not in message

    def test_validate_passes_unreserved_keys(self):
        class Reserving(MockAgent):
            RESERVED_RUN_OPTIONS = {"context": "populated from framework_context"}

        agent = Reserving("test-agent", MockRunner("test-runner"))

        agent.validate_run_options({"max_turns": 5, "hooks": object()})  # no raise

    def test_validate_names_every_reserved_key_in_sorted_order(self):
        class Reserving(MockAgent):
            RESERVED_RUN_OPTIONS = {"session": "the AK session", "context": "framework_context"}

        agent = Reserving("test-agent", MockRunner("test-runner"))

        with pytest.raises(ValueError) as exc:
            agent.validate_run_options({"session": 1, "context": 2})

        message = str(exc.value)
        assert message.index("'context'") < message.index("'session'")
        assert "the AK session" in message and "framework_context" in message


class TestAgentResolveRunOptions:
    """Agent.run_options_factory / Agent.resolve_run_options (spec #758, Agent section)."""

    STATIC = {"max_turns": 10, "keep": "static"}

    def _agent(self) -> MockAgent:
        agent = MockAgent("test-agent", MockRunner("test-runner"))
        agent.run_options.update(self.STATIC)
        return agent

    def test_run_options_factory_alias_is_exported_from_core_and_the_package(self):
        from agentkernel import RunOptionsFactory as top_level
        from agentkernel.core import RunOptionsFactory as core_level
        from agentkernel.core.base import RunOptionsFactory as base_level

        assert top_level is core_level is base_level

    def test_run_options_factory_defaults_to_none_and_is_settable(self):
        agent = MockAgent("test-agent", MockRunner("test-runner"))
        assert agent.run_options_factory is None

        def factory(agent, session, requests):
            return {}

        agent.run_options_factory = factory
        assert agent.run_options_factory is factory

        agent.run_options_factory = None
        assert agent.run_options_factory is None

    @pytest.mark.asyncio
    async def test_no_factory_resolves_to_an_equal_but_distinct_copy_of_the_static_dict(self):
        agent = self._agent()

        options = await agent.resolve_run_options(Session("test-session"), [AgentRequestText(prompt="hi")])

        assert options == self.STATIC
        assert options is not agent.run_options
        options["max_turns"] = 1
        assert agent.run_options == self.STATIC

    @pytest.mark.asyncio
    async def test_a_sync_factory_merges_over_the_static_dict_and_wins_per_key(self):
        agent = self._agent()
        agent.run_options_factory = lambda agent, session, requests: {"max_turns": 3, "extra": True}

        options = await agent.resolve_run_options(Session("test-session"), [])

        assert options == {"max_turns": 3, "keep": "static", "extra": True}
        assert agent.run_options == self.STATIC

    @pytest.mark.asyncio
    async def test_an_async_factory_merges_the_same_way(self):
        agent = self._agent()

        async def factory(agent, session, requests):
            return {"max_turns": 3, "extra": True}

        agent.run_options_factory = factory

        options = await agent.resolve_run_options(Session("test-session"), [])

        assert options == {"max_turns": 3, "keep": "static", "extra": True}
        assert agent.run_options == self.STATIC

    @pytest.mark.asyncio
    async def test_a_dict_valued_option_from_the_factory_replaces_the_static_one_wholesale(self):
        agent = self._agent()
        agent.run_options["config"] = {"recursion_limit": 5, "tags": ["static"]}
        agent.run_options_factory = lambda agent, session, requests: {"config": {"recursion_limit": 9}}

        options = await agent.resolve_run_options(Session("test-session"), [])

        assert options["config"] == {"recursion_limit": 9}  # top-level merge only, no deep merge
        assert agent.run_options["config"] == {"recursion_limit": 5, "tags": ["static"]}

    @pytest.mark.asyncio
    async def test_a_read_only_mapping_result_is_accepted(self):
        agent = self._agent()
        agent.run_options_factory = lambda agent, session, requests: MappingProxyType({"max_turns": 3})

        options = await agent.resolve_run_options(Session("test-session"), [])

        assert options == {"max_turns": 3, "keep": "static"}
        assert isinstance(options, dict)

    @pytest.mark.asyncio
    async def test_the_factory_receives_the_agent_session_and_requests_by_identity_once(self):
        agent = self._agent()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hi")]
        calls: list[tuple] = []

        def factory(*args):
            calls.append(args)
            return {}

        agent.run_options_factory = factory

        await agent.resolve_run_options(session, requests)

        assert len(calls) == 1
        seen_agent, seen_session, seen_requests = calls[0]
        assert seen_agent is agent
        assert seen_session is session
        assert seen_requests is requests

    @pytest.mark.asyncio
    async def test_a_non_mapping_result_raises_type_error_naming_the_agent_and_the_type(self):
        agent = self._agent()
        agent.run_options_factory = lambda agent, session, requests: [("max_turns", 3)]

        with pytest.raises(TypeError) as exc:
            await agent.resolve_run_options(Session("test-session"), [])

        assert "test-agent" in str(exc.value)
        assert "list" in str(exc.value)
        assert agent.run_options == self.STATIC

    @pytest.mark.asyncio
    async def test_a_reserved_key_from_the_factory_raises_the_same_value_error_as_declaration(self):
        class Reserving(MockAgent):
            RESERVED_RUN_OPTIONS = {"context": "populated from framework_context"}

        agent = Reserving("test-agent", MockRunner("test-runner"))
        agent.run_options.update(self.STATIC)
        agent.run_options_factory = lambda agent, session, requests: {"context": {"k": 1}, "max_turns": 3}

        with pytest.raises(ValueError) as exc:
            await agent.resolve_run_options(Session("test-session"), [])

        message = str(exc.value)
        assert "test-runner" in message
        assert "test-agent" in message
        assert "'context'" in message
        assert "populated from framework_context" in message
        assert "max_turns" not in message
        assert agent.run_options == self.STATIC

    @pytest.mark.asyncio
    async def test_a_raising_factory_propagates_its_exception_unchanged(self):
        agent = self._agent()

        def factory(agent, session, requests):
            raise RuntimeError("factory boom")

        agent.run_options_factory = factory

        with pytest.raises(RuntimeError, match="factory boom"):
            await agent.resolve_run_options(Session("test-session"), [])

        assert agent.run_options == self.STATIC


class TestRunnerNativeKwargs:
    """Runner._native_kwargs (spec #754, Runner section): copy, then AK-owned keys written last."""

    def test_ak_owned_keys_are_written_last_over_a_copy_of_the_options(self):
        options = {"a": 1, "session": "caller"}

        kwargs = Runner._native_kwargs(options, session="ak", context=None)

        assert kwargs == {"a": 1, "session": "ak", "context": None}
        assert options == {"a": 1, "session": "caller"}  # the declared mapping is never mutated
        assert kwargs is not options
