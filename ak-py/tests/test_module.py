from typing import Any, List

import pytest

from agentkernel import Agent, PostHook, PreHook, Runner
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.module import Module
from agentkernel.core.runtime import Runtime


class DummyRunner(Runner):
    @property
    def supports_streaming(self) -> bool:
        return True

    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class FrameworkAgent:
    def __init__(self, name: str = None):
        self.name = name


class KernelWrappedAgent(Agent):

    def __init__(self, name, agent: FrameworkAgent = None):
        runner = DummyRunner("DummyRunner")
        super().__init__(name, runner)
        self._agent = agent
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def runner(self):
        return self._runner

    def get_a2a_card(self):
        pass

    def get_description(self):
        pass

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class SimpleModule(Module):

    def pre_hook(self, agent: Any, hooks: list[PreHook]) -> "Module":
        pass

    def post_hook(self, agent: Any, hooks: list[PostHook]) -> "Module":
        pass

    def __init__(self, agents: list[FrameworkAgent]):
        super().__init__()
        self.load(agents)

    def _wrap(self, agent: FrameworkAgent, agents: List[FrameworkAgent]) -> Agent:
        return KernelWrappedAgent(agent.name, agent)

    def load(self, agents: list[FrameworkAgent]):
        super().load(agents)


def test_module_add_updates_agents(monkeypatch):
    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    with Runtime(SessionStoreBuilder.build()) as runtime:
        # Initialize with one agent
        a1 = FrameworkAgent("agent1")
        mod = SimpleModule([a1])

        assert len(mod.agents) == 1
        assert mod.agents[0].name == "agent1"

        # Add a second agent and verify it appears in the module.agents list
        a2 = FrameworkAgent("agent2")
        mod.load([a1, a2])

        assert len(mod.agents) == 2
        assert mod.agents[-1].name == "agent2"
        assert {a.name for a in mod.agents} == {"agent1", "agent2"}

        # Verify runtime registration reflects the newly added agent
        assert "agent1" in runtime.agents()
        assert "agent2" in runtime.agents()

        # Verify unload
        mod.unload()
        assert len(mod.agents) == 0
        assert runtime.agents() == {}

        # Verify reload
        mod.load([a1])
        assert len(mod.agents) == 1
        assert mod.agents[0].name == "agent1"
        assert runtime.agents() == {"agent1": mod.agents[0]}

        # Handle duplicates
        a3 = FrameworkAgent("agent3")

        try:
            SimpleModule([a3, a1])
        except Exception as e:
            assert "Agent with name 'agent1' is already registered." in str(e)

        # Runtime should be intact after exception
        assert len(mod.agents) == 1
        assert runtime.agents() == {"agent1": mod.agents[0]}


def test_load_modules_with_unique_agent_names():
    with Runtime(SessionStoreBuilder.build()) as runtime:
        a1 = FrameworkAgent("agent1")
        SimpleModule([a1])
        assert len(runtime.agents()) == 1
        assert "agent1" in runtime.agents().keys()

        a2 = FrameworkAgent("agent2")
        a3 = FrameworkAgent("agent3")
        SimpleModule([a2, a3])
        assert len(runtime.agents()) == 3
        assert "agent1" in runtime.agents().keys()
        assert "agent2" in runtime.agents().keys()
        assert "agent3" in runtime.agents().keys()


def test_load_modules_with_duplicate_agent_names():
    with Runtime(SessionStoreBuilder.build()) as runtime:
        a1 = FrameworkAgent("agent1")
        mod1 = SimpleModule([a1])
        assert len(runtime.agents()) == 1
        assert "agent1" in runtime.agents().keys()

        a2 = FrameworkAgent("agent2")
        a1x = FrameworkAgent("agent1")
        try:
            SimpleModule([a2, a1x])
        except Exception as e:
            assert "Agent with name 'agent1' is already registered." in str(e)

        assert len(runtime.agents()) == 1
        assert runtime.agents() == {"agent1": mod1.agents[0]}


def test_load_modules_with_duplicate_agent_names_across_runtimes():
    runtime1 = Runtime(SessionStoreBuilder.build())
    with runtime1:
        a1 = FrameworkAgent("agent1")
        mod1 = SimpleModule([a1])
        assert len(runtime1.agents()) == 1
        assert runtime1.agents() == {"agent1": mod1.agents[0]}

    runtime2 = Runtime(SessionStoreBuilder.build())
    with runtime2:
        a1x = FrameworkAgent("agent1")
        a2 = FrameworkAgent("agent2")
        mod2 = SimpleModule([a1x, a2])
        assert len(runtime2.agents()) == 2
        assert runtime2.agents() == {"agent1": mod2.agents[0], "agent2": mod2.agents[1]}


class ReservingWrappedAgent(KernelWrappedAgent):
    RESERVED_RUN_OPTIONS = {"session": "the Agent Kernel session is passed by the runner"}


class ReservingModule(SimpleModule):
    def _wrap(self, agent: FrameworkAgent, agents: List[FrameworkAgent]) -> Agent:
        return ReservingWrappedAgent(agent.name, agent)


class RoleNamedFrameworkAgent:
    def __init__(self, role: str):
        self.role = role


class RoleNamedModule(SimpleModule):
    """A module whose native agents are named by `role`, the CrewAI shape."""

    def _wrap(self, agent: RoleNamedFrameworkAgent, agents: List[RoleNamedFrameworkAgent]) -> Agent:
        return KernelWrappedAgent(agent.role, agent)

    def _native_agent_name(self, agent: Any) -> str:
        return agent.role


class TestModuleRunOptions:
    """Module.run_options (spec #754, Module section)."""

    def test_repeated_calls_merge_with_the_later_call_winning_per_key(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            mod.run_options(a1, a=1, keep="yes")
            mod.run_options(a1, a=2, b=3)

            assert mod.get_agent("agent1").run_options == {"a": 2, "b": 3, "keep": "yes"}

    def test_chains_with_the_hook_methods_and_returns_the_module(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = BareModule([a1])  # the base-class hook methods return the module, so the chain needs no override

            result = mod.pre_hook(a1, []).run_options(a1, max_turns=25).post_hook(a1, []).run_options(a1, hooks="h")

            assert result is mod
            assert mod.get_agent("agent1").run_options == {"max_turns": 25, "hooks": "h"}

    def test_a_reserved_key_raises_and_writes_nothing(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = ReservingModule([a1])

            with pytest.raises(ValueError) as exc:
                mod.run_options(a1, session="mine", other=2)

            assert "'session'" in str(exc.value)
            assert "the Agent Kernel session is passed by the runner" in str(exc.value)
            assert mod.get_agent("agent1").run_options == {}  # not even 'other' was written

    def test_an_agent_not_loaded_in_the_module_raises_naming_it(self):
        with Runtime(SessionStoreBuilder.build()):
            mod = SimpleModule([FrameworkAgent("agent1")])

            with pytest.raises(ValueError) as exc:
                mod.run_options(FrameworkAgent("ghost"), a=1)

            assert "ghost" in str(exc.value)

    def test_resolves_the_agent_through_the_native_agent_name_override(self):
        with Runtime(SessionStoreBuilder.build()):
            native = RoleNamedFrameworkAgent("researcher")
            mod = RoleNamedModule([native])

            mod.run_options(native, max_rpm=30)

            assert mod.get_agent("researcher").run_options == {"max_rpm": 30}

    def test_simple_module_still_constructs_without_implementing_run_options(self):
        # run_options is concrete on Module (design amendment 1): a subclass that overrides the hook
        # methods but never mentions run_options must keep constructing.
        with Runtime(SessionStoreBuilder.build()):
            assert isinstance(SimpleModule([FrameworkAgent("agent1")]), Module)


def _factory(agent, session, requests):
    return {"max_turns": 3}


def _other_factory(agent, session, requests):
    return {"max_turns": 4}


class TestModuleRunOptionsFactory:
    """The positional-only factory parameter of Module.run_options (spec #758, Module section)."""

    def test_a_positional_factory_is_stored_on_the_agent_and_returns_the_module(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            result = mod.run_options(a1, _factory)

            assert result is mod
            assert mod.get_agent("agent1").run_options_factory is _factory
            assert mod.get_agent("agent1").run_options == {}

    def test_a_factory_and_keywords_in_one_call_store_both(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            mod.run_options(a1, _factory, max_turns=3)

            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is _factory
            assert wrapped.run_options == {"max_turns": 3}

    def test_a_later_factory_replaces_the_earlier_one_while_keywords_keep_merging(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            mod.run_options(a1, _factory, max_turns=3)
            mod.run_options(a1, _other_factory, hooks="h")

            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is _other_factory
            assert wrapped.run_options == {"max_turns": 3, "hooks": "h"}

    def test_keywords_alone_leave_an_earlier_factory_in_place(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            mod.run_options(a1, _factory)
            mod.run_options(a1, max_turns=3)

            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is _factory
            assert wrapped.run_options == {"max_turns": 3}

    def test_a_non_callable_factory_raises_type_error_and_stores_nothing(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            with pytest.raises(TypeError) as exc:
                mod.run_options(a1, {"max_turns": 3}, other=2)

            assert "agent1" in str(exc.value)
            assert "dict" in str(exc.value)
            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is None
            assert wrapped.run_options == {}  # not even 'other' was written

    def test_a_reserved_keyword_beside_a_factory_raises_and_stores_neither(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = ReservingModule([a1])

            with pytest.raises(ValueError) as exc:
                mod.run_options(a1, _factory, session="mine")

            assert "'session'" in str(exc.value)
            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is None
            assert wrapped.run_options == {}

    def test_a_call_with_neither_factory_nor_keywords_is_a_no_op_returning_the_module(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            result = mod.run_options(a1)

            assert result is mod
            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is None
            assert wrapped.run_options == {}

    def test_a_keyword_named_factory_is_a_run_option_not_the_factory(self):
        # The parameter is positional-only, so `factory=` lands in **options and shadows no native option name.
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = SimpleModule([a1])

            mod.run_options(a1, factory="a-native-option-value")

            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options == {"factory": "a-native-option-value"}
            assert wrapped.run_options_factory is None

    def test_an_agent_not_loaded_in_the_module_raises_naming_it(self):
        with Runtime(SessionStoreBuilder.build()):
            mod = SimpleModule([FrameworkAgent("agent1")])

            with pytest.raises(ValueError) as exc:
                mod.run_options(FrameworkAgent("ghost"), _factory)

            assert "ghost" in str(exc.value)

    def test_chains_with_the_hook_methods_and_returns_the_module(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = BareModule([a1])

            result = mod.pre_hook(a1, []).run_options(a1, _factory, max_turns=25).post_hook(a1, []).run_options(a1, hooks="h")

            assert result is mod
            wrapped = mod.get_agent("agent1")
            assert wrapped.run_options_factory is _factory
            assert wrapped.run_options == {"max_turns": 25, "hooks": "h"}


class BareModule(Module):
    """A module implementing only the abstract wrapping members: the hook methods come from the base class."""

    def __init__(self, agents: list[Any]):
        super().__init__()
        self.load(agents)

    def _wrap(self, agent: Any, agents: List[Any]) -> Agent:
        return KernelWrappedAgent(self._native_agent_name(agent), agent)

    def load(self, agents: list[Any]):
        super().load(agents)


class RoleNamedBareModule(BareModule):
    def _native_agent_name(self, agent: Any) -> str:
        return agent.role


class TestModuleHooksResolveThroughNativeAgentName:
    """pre_hook / post_hook are concrete on Module and resolve the agent the same way run_options does."""

    def test_a_module_implementing_only_wrap_and_load_constructs(self):
        with Runtime(SessionStoreBuilder.build()):
            assert isinstance(BareModule([FrameworkAgent("agent1")]), Module)

    def test_hooks_attach_to_the_wrapped_agent_and_chain_with_run_options(self):
        with Runtime(SessionStoreBuilder.build()):
            a1 = FrameworkAgent("agent1")
            mod = BareModule([a1])
            pre, post = object(), object()

            result = mod.pre_hook(a1, [pre]).run_options(a1, max_turns=3).post_hook(a1, [post])

            assert result is mod
            wrapped = mod.get_agent("agent1")
            assert wrapped.pre_hooks == [pre]
            assert wrapped.post_hooks == [post]
            assert wrapped.run_options == {"max_turns": 3}

    def test_hooks_resolve_through_the_native_agent_name_override(self):
        with Runtime(SessionStoreBuilder.build()):
            native = RoleNamedFrameworkAgent("researcher")
            mod = RoleNamedBareModule([native])
            hook = object()

            mod.pre_hook(native, [hook]).post_hook(native, [hook])

            assert mod.get_agent("researcher").pre_hooks == [hook]
            assert mod.get_agent("researcher").post_hooks == [hook]

    def test_an_agent_not_loaded_in_the_module_raises_naming_it(self):
        with Runtime(SessionStoreBuilder.build()):
            mod = BareModule([FrameworkAgent("agent1")])

            with pytest.raises(ValueError) as exc:
                mod.pre_hook(FrameworkAgent("ghost"), [])
            assert "ghost" in str(exc.value)
            with pytest.raises(ValueError):
                mod.post_hook(FrameworkAgent("ghost"), [])
