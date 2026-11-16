"""
The agent registry (spec `docs/specs/603-identity-rbac-registry/` section 6, iteration 13).

Runtime keeps its agents in an `AgentRegistry`, and every agent carries a descriptor: the catalog
entry the surfaces and the authorizer read in later iterations. This file covers the registry
contract over the in-memory backend, the descriptor an agent builds for itself, `Module.describe`
as the second descriptor source, and Runtime delegating to the registry. The store-backed backends
and the config overlay arrive with the registry config in a later iteration.
"""

import pytest

from agentkernel.core.base import Agent, Runner
from agentkernel.core.model import AgentDescriptor, AgentIdentitySpec, AgentReplyText, AgentRequestText, AgentSkillDescriptor
from agentkernel.core.module import Module
from agentkernel.core.registry import AgentDescriptorPage, AgentRegistrationError, AgentRegistry, AgentRegistryFactory, InMemoryAgentRegistry
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.pagination import DEFAULT_PAGE_SIZE


class StubRunner(Runner):
    """Answers every run and records the principal the session published for it."""

    def __init__(self, name: str = "stub", streaming: bool = True):
        super().__init__(name)
        self._streaming = streaming
        self.principals: list = []

    @property
    def supports_streaming(self) -> bool:
        return self._streaming

    async def run(self, agent, session, requests):
        self.principals.append(session.get_principal())
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class StubAgent(Agent):
    """An agent with no native framework behind it, so its descriptor is the base class's own."""

    def __init__(self, name: str, runner: Runner | None = None):
        super().__init__(name, runner or StubRunner())

    def get_description(self) -> str:
        return "the agent's instructions, which are never catalog text"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class ToolReportingAgent(StubAgent):
    """Holds its tools the way every adapter holds its native agent: assigned after the base constructor returns."""

    def __init__(self, name: str, tools: list[str]):
        super().__init__(name)
        self._tools = tools

    def get_tool_names(self) -> list[str]:
        return list(self._tools)


class NativeAgent:
    """Stands in for a framework's own agent object, which a module wraps."""

    def __init__(self, name: str):
        self.name = name


class StubModule(Module):
    def __init__(self, agents: list[NativeAgent]):
        super().__init__()
        self.load(agents)

    def _wrap(self, agent: NativeAgent, agents: list[NativeAgent]) -> Agent:
        return ToolReportingAgent(agent.name, ["search"])

    def load(self, agents: list[NativeAgent]) -> Module:
        return super().load(agents)


def _descriptor(id: str, **fields) -> AgentDescriptor:
    return AgentDescriptor(id=id, name=id, **fields)


def _ids(page: AgentDescriptorPage) -> list[str]:
    return [descriptor.id for descriptor in page.agents]


@pytest.fixture
def registry() -> InMemoryAgentRegistry:
    return InMemoryAgentRegistry()


@pytest.fixture
def runtime() -> Runtime:
    return Runtime(InMemorySessionStore())


class TestInMemoryAgentRegistry:
    def test_a_registered_agent_and_its_descriptor_are_readable_by_id(self, registry):
        agent = StubAgent("billing")
        descriptor = _descriptor("billing", description="Answers invoice questions")

        registry.register(descriptor, agent)

        assert registry.get("billing") is agent
        assert registry.descriptor("billing") == descriptor
        assert registry.agents() == {"billing": agent}
        assert registry.descriptors() == [descriptor]

    def test_an_unknown_id_reads_as_none(self, registry):
        assert registry.get("ghost") is None
        assert registry.descriptor("ghost") is None

    def test_a_different_agent_under_a_held_id_is_refused_and_the_first_is_kept(self, registry):
        first = StubAgent("billing")
        registry.register(_descriptor("billing", version="1.0.0"), first)

        with pytest.raises(AgentRegistrationError, match="'billing'"):
            registry.register(_descriptor("billing", version="2.0.0"), StubAgent("billing"))

        assert registry.get("billing") is first
        assert registry.descriptor("billing").version == "1.0.0"

    def test_registering_the_same_agent_again_replaces_its_descriptor(self, registry):
        agent = StubAgent("billing")
        registry.register(_descriptor("billing", version="1.0.0"), agent)

        registry.register(_descriptor("billing", version="2.0.0"), agent)

        assert registry.descriptor("billing").version == "2.0.0"
        assert registry.agents() == {"billing": agent}

    def test_deregister_removes_the_agent_and_its_descriptor_and_frees_the_id(self, registry):
        registry.register(_descriptor("billing"), StubAgent("billing"))
        registry.register(_descriptor("support"), StubAgent("support"))

        registry.deregister("billing")

        assert registry.get("billing") is None
        assert registry.descriptor("billing") is None
        assert [descriptor.id for descriptor in registry.descriptors()] == ["support"]
        replacement = StubAgent("billing")
        registry.register(_descriptor("billing"), replacement)
        assert registry.get("billing") is replacement

    def test_deregistering_an_unknown_id_changes_nothing(self, registry):
        agent = StubAgent("billing")
        registry.register(_descriptor("billing"), agent)

        registry.deregister("ghost")

        assert registry.agents() == {"billing": agent}

    def test_clear_removes_every_agent_and_descriptor(self, registry):
        registry.register(_descriptor("billing"), StubAgent("billing"))
        registry.register(_descriptor("support"), StubAgent("support"))

        registry.clear()

        assert registry.agents() == {}
        assert registry.descriptors() == []

    def test_list_orders_by_id_whatever_the_registration_order(self, registry):
        for id in ("support", "billing", "onboarding"):
            registry.register(_descriptor(id), StubAgent(id))

        page = registry.list()

        assert _ids(page) == ["billing", "onboarding", "support"]
        assert page.next_cursor is None

    def test_list_pages_with_the_cursor_of_the_page_before(self, registry):
        for id in ("a", "b", "c"):
            registry.register(_descriptor(id), StubAgent(id))

        first = registry.list(limit=2)
        second = registry.list(cursor=first.next_cursor, limit=2)

        assert _ids(first) == ["a", "b"]
        assert first.next_cursor is not None
        assert _ids(second) == ["c"]
        assert second.next_cursor is None

    def test_list_keeps_the_agents_carrying_every_requested_tag(self, registry):
        registry.register(_descriptor("a", tags=["billing", "internal"]), StubAgent("a"))
        registry.register(_descriptor("b", tags=["billing"]), StubAgent("b"))
        registry.register(_descriptor("c"), StubAgent("c"))

        assert _ids(registry.list(tags=["billing"])) == ["a", "b"]
        assert _ids(registry.list(tags=["billing", "internal"])) == ["a"]
        assert _ids(registry.list(tags=["unknown"])) == []
        assert _ids(registry.list(tags=[])) == ["a", "b", "c"]

    def test_list_without_a_limit_returns_one_default_sized_page(self, registry):
        for n in range(DEFAULT_PAGE_SIZE + 1):
            registry.register(_descriptor(f"agent-{n:03d}"), StubAgent(f"agent-{n:03d}"))

        page = registry.list()

        assert len(page.agents) == DEFAULT_PAGE_SIZE
        assert page.next_cursor is not None

    def test_list_refuses_a_malformed_cursor(self, registry):
        registry.register(_descriptor("a"), StubAgent("a"))

        with pytest.raises(ValueError):
            registry.list(cursor="not-a-cursor")


class TestAgentRegistryFactory:
    def test_each_build_is_a_separate_in_memory_registry(self):
        first = AgentRegistryFactory.build()
        second = AgentRegistryFactory.build()

        first.register(_descriptor("billing"), StubAgent("billing"))

        assert isinstance(first, InMemoryAgentRegistry)
        assert second.agents() == {}


class TestPackageExports:
    def test_the_registry_contract_and_its_error_are_importable_from_the_package(self):
        # What an application names: the base class of a registry of its own, and the error
        # Runtime.register raises.
        import agentkernel

        assert agentkernel.AgentRegistry is AgentRegistry
        assert agentkernel.AgentRegistrationError is AgentRegistrationError


class TestAgentDescriptor:
    def test_an_agent_describes_itself_from_its_name_and_runner(self):
        descriptor = StubAgent("billing", StubRunner("openai", streaming=False)).descriptor

        assert (descriptor.id, descriptor.name) == ("billing", "billing")
        assert descriptor.runner == "openai"
        assert descriptor.supports_streaming is False
        assert descriptor.tools == []
        assert descriptor.skills == []
        assert descriptor.description == ""  # catalog text is declared, never taken from get_description()

    def test_a_streaming_runner_is_described_as_streaming(self):
        assert StubAgent("billing", StubRunner(streaming=True)).descriptor.supports_streaming is True

    def test_the_tools_an_adapter_reports_become_the_tools_and_one_skill_each(self):
        # The adapter's state is assigned after the base constructor returns, so the descriptor
        # cannot be built inside it.
        descriptor = ToolReportingAgent("billing", ["lookup_invoice", "refund"]).descriptor

        assert descriptor.tools == ["lookup_invoice", "refund"]
        assert descriptor.skills == [
            AgentSkillDescriptor(id="lookup_invoice", name="lookup_invoice"),
            AgentSkillDescriptor(id="refund", name="refund"),
        ]

    def test_an_agent_reports_no_tools_and_no_ungated_tools_by_default(self):
        agent = StubAgent("billing")

        assert agent.get_tool_names() == []
        assert agent.ungated_tool_names() == []


class TestRuntimeDelegation:
    def test_register_stores_the_agent_under_its_descriptor(self, runtime):
        agent = ToolReportingAgent("billing", ["refund"])

        runtime.register(agent)

        assert runtime.registry.get("billing") is agent
        assert runtime.registry.descriptor("billing").tools == ["refund"]
        assert runtime.agents() == {"billing": agent}

    def test_a_second_agent_with_a_registered_name_raises_agent_registration_error(self, runtime):
        first = StubAgent("billing")
        runtime.register(first)

        with pytest.raises(AgentRegistrationError, match="'billing'"):
            runtime.register(StubAgent("billing"))

        assert runtime.agents() == {"billing": first}

    def test_deregister_removes_the_agent_and_its_descriptor(self, runtime):
        agent = StubAgent("billing")
        runtime.register(agent)

        runtime.deregister(agent)

        assert runtime.agents() == {}
        assert runtime.registry.descriptor("billing") is None

    def test_deregistering_an_agent_that_was_never_registered_does_not_raise(self, runtime):
        registered = StubAgent("billing")
        runtime.register(registered)

        runtime.deregister(StubAgent("support"))

        assert runtime.agents() == {"billing": registered}

    def test_a_runtime_uses_the_registry_it_is_given(self):
        registry = InMemoryAgentRegistry()
        runtime = Runtime(InMemorySessionStore(), registry=registry)
        agent = StubAgent("billing")

        runtime.register(agent)

        assert runtime.registry is registry
        assert registry.get("billing") is agent

    def test_two_runtimes_keep_separate_registries(self):
        first, second = Runtime(InMemorySessionStore()), Runtime(InMemorySessionStore())

        first.register(StubAgent("billing"))
        second.register(StubAgent("billing"))  # the same name is free in another runtime

        assert first.agents()["billing"] is not second.agents()["billing"]

    def test_the_mapping_agents_returns_follows_later_registrations(self, runtime):
        # Handlers read Runtime.agents() once and keep it; a copy would freeze what they see.
        held = runtime.agents()
        agent = StubAgent("billing")

        runtime.register(agent)

        assert held == {"billing": agent}


class TestModuleDescribe:
    def test_described_fields_reach_the_registry_and_keep_the_adapter_defaults(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            module.describe(native, description="Answers invoice questions", tags=["finance"], version="1.2.0")

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.description, descriptor.tags, descriptor.version) == ("Answers invoice questions", ["finance"], "1.2.0")
        assert (descriptor.id, descriptor.runner, descriptor.tools) == ("billing", "stub", ["search"])
        assert module.get_agent("billing").descriptor == descriptor

    def test_a_later_call_wins_per_field_and_keeps_the_fields_it_does_not_name(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            module.describe(native, tags=["finance"], owner="alice")
            module.describe(native, tags=["invoices"], version="2.0.0")

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.tags, descriptor.owner, descriptor.version) == (["invoices"], "alice", "2.0.0")

    def test_describe_returns_the_module_for_chaining(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            assert module.describe(native, owner="alice").describe(native, visibility="public") is module

        assert runtime.registry.descriptor("billing").visibility == "public"

    def test_an_agent_not_loaded_in_the_module_raises_naming_it(self, runtime):
        with runtime:
            module = StubModule([NativeAgent("billing")])

            with pytest.raises(ValueError, match="ghost"):
                module.describe(NativeAgent("ghost"), owner="alice")

    def test_a_field_the_descriptor_does_not_declare_raises_and_stores_nothing(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            with pytest.raises(ValueError, match="colour"):
                module.describe(native, owner="alice", colour="red")

        assert runtime.registry.descriptor("billing").owner is None  # not even the declared field was written

    def test_a_value_the_descriptor_refuses_raises_and_stores_nothing(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            with pytest.raises(ValueError, match="agent 'billing'.*visibility"):
                module.describe(native, owner="alice", visibility="secret")

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.owner, descriptor.visibility) == (None, "private")

    def test_the_id_cannot_be_described_away_from_the_registry_key(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            with pytest.raises(ValueError, match="id"):
                module.describe(native, id="invoices")

        assert list(runtime.agents()) == ["billing"]
        assert runtime.registry.descriptor("billing").id == "billing"

    def test_describing_outside_the_runtime_that_hosts_the_agent_raises_and_registers_nothing(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

        other = Runtime(InMemorySessionStore())
        with other:
            with pytest.raises(ValueError, match="billing"):
                module.describe(native, owner="alice")

        assert other.agents() == {}
        assert runtime.registry.descriptor("billing").owner is None

    @pytest.mark.asyncio
    async def test_a_described_identity_subject_is_the_actor_of_the_agents_runs(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])
            module.describe(native, identity={"subject": "svc-billing"})

        agent = module.get_agent("billing")
        assert agent.descriptor.identity == AgentIdentitySpec(subject="svc-billing")

        await runtime.run(agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")])

        actor = agent.runner.principals[0].actor
        assert (actor.kind, actor.subject, actor.provider) == ("agent", "svc-billing", "agentkernel")
