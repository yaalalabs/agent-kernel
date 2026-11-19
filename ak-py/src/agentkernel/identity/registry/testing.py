"""Public testing helpers for agent registries. Imports pytest, so import from test code only."""

import pytest

from ...core.base import Agent, Runner
from ...core.model import AgentDescriptor, AgentIdentitySpec, AgentReplyText, AgentSkillDescriptor
from ...core.registry import AgentRegistrationError, AgentRegistry
from ...core.util.pagination import DEFAULT_PAGE_SIZE


class ContractRunner(Runner):
    """The runner of a contract agent; a registry never runs the agents it holds."""

    def __init__(self):
        super().__init__("contract")

    async def run(self, agent, session, requests):  # pragma: no cover - never run
        return AgentReplyText(response="")

    async def stream(self, agent, session, requests):  # pragma: no cover - never run
        raise NotImplementedError()
        yield


class ContractAgent(Agent):
    """A minimal agent to register: a registry needs an object to host, nothing of what it does."""

    def __init__(self, name: str):
        super().__init__(name, ContractRunner())

    def get_description(self) -> str:
        return ""

    def override_system_prompt(self, prompt: str) -> None:
        pass

    def attach_tool(self, tool) -> None:
        pass


class AgentRegistryContract:
    """Conformance suite every AgentRegistry subclasses. Override the ``registry`` fixture.

    Not prefixed ``Test`` so pytest does not collect it on its own. A registry that keeps its
    descriptors in a store other processes share also overrides ``peer`` with a second registry over
    the same store; the cases that need one are skipped for a registry that shares nothing.

    A store-backed registry may stamp ``updated_at`` on what it stores, so descriptors are compared
    with that field left out.
    """

    @pytest.fixture
    def registry(self) -> AgentRegistry:
        """The registry under contract, empty; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `registry` fixture")

    @pytest.fixture
    def peer(self, registry) -> AgentRegistry | None:
        """A second registry over the same store as ``registry``, standing in for another process.

        None, the default, is right for a registry that keeps everything in its own process.
        """
        return None

    @staticmethod
    def descriptor(id: str, **fields) -> AgentDescriptor:
        return AgentDescriptor(id=id, name=id, **fields)

    @staticmethod
    def stored(descriptor: AgentDescriptor | None) -> dict | None:
        """A descriptor as the contract compares it: every field but the store's own ``updated_at``."""
        return None if descriptor is None else descriptor.model_dump(exclude={"updated_at"})

    @classmethod
    def ids(cls, descriptors) -> list[str]:
        return [descriptor.id for descriptor in descriptors]

    def _shared(self, peer: AgentRegistry | None) -> AgentRegistry:
        if peer is None:
            pytest.skip("this registry shares no store with another process")
        return peer

    def test_contract_a_registered_agent_and_its_descriptor_are_readable_by_id(self, registry):
        agent = ContractAgent("billing")
        descriptor = self.descriptor("billing", description="Answers invoice questions", tags=["finance"])
        expected = self.stored(descriptor)  # taken first: a registry that changed the descriptor it was handed would otherwise pass

        registry.register(descriptor, agent)

        assert registry.get("billing") is agent
        assert registry.agents() == {"billing": agent}
        assert self.stored(registry.descriptor("billing")) == expected
        assert [self.stored(found) for found in registry.descriptors()] == [expected]

    @pytest.mark.parametrize("surfaces", [[], ["rest"]], ids=["no-surface", "rest-only"])
    def test_contract_every_field_of_a_descriptor_survives_the_registry(self, registry, surfaces):
        """`surfaces` is the exposure boundary: `[]` (on no surface) must not come back as None (on every surface),
        and a list that names some must come back naming the same ones."""
        descriptor = self.descriptor(
            "billing",
            version="1.2.0",
            description="Answers invoice questions",
            owner="finance-platform",
            tags=["finance"],
            visibility="internal",
            surfaces=surfaces,
            skills=[AgentSkillDescriptor(id="refund", name="refund", description="Refunds an invoice")],
            tools=["refund"],
            runner="contract",
            supports_streaming=False,
            identity=AgentIdentitySpec(subject="svc-billing"),
        )
        expected = self.stored(descriptor)

        registry.register(descriptor, ContractAgent("billing"))

        read = registry.descriptor("billing")
        assert self.stored(read) == expected
        assert read.surfaces == surfaces
        assert (read.exposed_on("rest"), read.exposed_on("mcp")) == ("rest" in surfaces, False)
        assert read.identity == AgentIdentitySpec(subject="svc-billing")
        assert [self.stored(found) for found in registry.descriptors()] == [expected]

    def test_contract_a_registry_is_empty_until_an_agent_registers_and_again_once_it_is_removed(self, registry):
        assert registry.is_empty() is True

        registry.register(self.descriptor("billing"), ContractAgent("billing"))
        assert registry.is_empty() is False

        registry.deregister("billing")
        assert registry.is_empty() is True

    def test_contract_an_unknown_id_reads_as_none(self, registry):
        assert registry.get("ghost") is None
        assert registry.descriptor("ghost") is None

    def test_contract_a_different_agent_under_a_held_id_is_refused_and_the_first_is_kept(self, registry):
        first = ContractAgent("billing")
        registry.register(self.descriptor("billing", version="1.0.0"), first)

        with pytest.raises(AgentRegistrationError):
            registry.register(self.descriptor("billing", version="2.0.0"), ContractAgent("billing"))

        assert registry.get("billing") is first
        assert registry.descriptor("billing").version == "1.0.0"

    def test_contract_registering_the_same_agent_again_replaces_its_descriptor(self, registry):
        agent = ContractAgent("billing")
        registry.register(self.descriptor("billing", version="1.0.0"), agent)

        registry.register(self.descriptor("billing", version="2.0.0"), agent)

        assert registry.descriptor("billing").version == "2.0.0"
        assert self.ids(registry.descriptors()) == ["billing"]
        assert registry.agents() == {"billing": agent}

    def test_contract_deregister_removes_the_agent_and_its_descriptor_and_frees_the_id(self, registry):
        registry.register(self.descriptor("billing"), ContractAgent("billing"))
        registry.register(self.descriptor("support"), ContractAgent("support"))

        registry.deregister("billing")

        assert registry.get("billing") is None
        assert registry.descriptor("billing") is None
        assert self.ids(registry.descriptors()) == ["support"]
        replacement = ContractAgent("billing")
        registry.register(self.descriptor("billing"), replacement)
        assert registry.get("billing") is replacement

    def test_contract_deregistering_an_unknown_id_changes_nothing(self, registry):
        agent = ContractAgent("billing")
        registry.register(self.descriptor("billing"), agent)

        registry.deregister("ghost")

        assert registry.agents() == {"billing": agent}
        assert self.ids(registry.descriptors()) == ["billing"]

    def test_contract_clear_removes_every_hosted_agent_and_its_descriptor(self, registry):
        registry.register(self.descriptor("billing"), ContractAgent("billing"))
        registry.register(self.descriptor("support"), ContractAgent("support"))

        registry.clear()

        assert registry.agents() == {}
        assert registry.descriptors() == []

    def test_contract_the_agents_mapping_follows_later_registrations(self, registry):
        held = registry.agents()
        agent = ContractAgent("billing")

        registry.register(self.descriptor("billing"), agent)

        assert held == {"billing": agent}

    def test_contract_list_orders_by_id_whatever_the_registration_order(self, registry):
        for id in ("support", "billing", "onboarding"):
            registry.register(self.descriptor(id), ContractAgent(id))

        page = registry.list()

        assert self.ids(page.agents) == ["billing", "onboarding", "support"]
        assert page.next_cursor is None

    def test_contract_list_pages_with_the_cursor_of_the_page_before(self, registry):
        for id in ("a", "b", "c"):
            registry.register(self.descriptor(id), ContractAgent(id))

        first = registry.list(limit=2)
        second = registry.list(cursor=first.next_cursor, limit=2)

        assert self.ids(first.agents) == ["a", "b"]
        assert first.next_cursor is not None
        assert self.ids(second.agents) == ["c"]
        assert second.next_cursor is None

    def test_contract_list_keeps_the_agents_carrying_every_requested_tag(self, registry):
        registry.register(self.descriptor("a", tags=["billing", "internal"]), ContractAgent("a"))
        registry.register(self.descriptor("b", tags=["billing"]), ContractAgent("b"))
        registry.register(self.descriptor("c"), ContractAgent("c"))

        assert self.ids(registry.list(tags=["billing"]).agents) == ["a", "b"]
        assert self.ids(registry.list(tags=["billing", "internal"]).agents) == ["a"]
        assert self.ids(registry.list(tags=["unknown"]).agents) == []
        assert self.ids(registry.list(tags=[]).agents) == ["a", "b", "c"]

    def test_contract_list_without_a_limit_returns_one_default_sized_page(self, registry):
        for n in range(DEFAULT_PAGE_SIZE + 1):
            registry.register(self.descriptor(f"agent-{n:03d}"), ContractAgent(f"agent-{n:03d}"))

        page = registry.list()

        assert len(page.agents) == DEFAULT_PAGE_SIZE
        assert page.next_cursor is not None

    def test_contract_list_refuses_a_malformed_cursor(self, registry):
        registry.register(self.descriptor("a"), ContractAgent("a"))

        with pytest.raises(ValueError):
            registry.list(cursor="not-a-cursor")

    def test_contract_a_descriptor_registered_by_one_instance_is_read_by_another(self, registry, peer):
        peer = self._shared(peer)
        descriptor = self.descriptor("billing", description="Answers invoice questions", version="1.2.0")

        registry.register(descriptor, ContractAgent("billing"))

        assert self.stored(peer.descriptor("billing")) == self.stored(descriptor)
        assert self.ids(peer.descriptors()) == ["billing"]
        assert self.ids(peer.list().agents) == ["billing"]
        # The other process knows the agent and does not host it.
        assert peer.get("billing") is None
        assert peer.agents() == {}

    def test_contract_two_instances_may_host_the_same_id(self, registry, peer):
        peer = self._shared(peer)
        ours, theirs = ContractAgent("billing"), ContractAgent("billing")
        registry.register(self.descriptor("billing", version="1.0.0"), ours)

        peer.register(self.descriptor("billing", version="2.0.0"), theirs)  # a replica of the same agent, not a duplicate

        assert (registry.get("billing"), peer.get("billing")) == (ours, theirs)
        assert (registry.descriptor("billing").version, peer.descriptor("billing").version) == ("2.0.0", "2.0.0")
        assert self.ids(registry.descriptors()) == ["billing"]

    def test_contract_a_deregistration_by_one_instance_is_seen_by_the_other(self, registry, peer):
        peer = self._shared(peer)
        registry.register(self.descriptor("billing"), ContractAgent("billing"))

        registry.deregister("billing")

        assert peer.descriptor("billing") is None
        assert peer.descriptors() == []
        assert peer.is_empty() is True

    def test_contract_clear_leaves_the_agents_only_another_instance_hosts(self, registry, peer):
        """`clear` removes what this process hosts, not the store: flushing it would withdraw every other process's agents."""
        peer = self._shared(peer)
        registry.register(self.descriptor("billing"), ContractAgent("billing"))
        peer.register(self.descriptor("support"), ContractAgent("support"))

        registry.clear()

        assert registry.agents() == {}
        assert self.ids(registry.descriptors()) == ["support"]
        assert peer.descriptor("support") is not None
        assert peer.get("support") is not None

    def test_contract_a_record_removed_by_one_host_returns_when_the_other_registers_again(self, registry, peer):
        """One record per id: either host's deregistration removes it, and the host still running restores it by registering."""
        peer = self._shared(peer)
        ours, theirs = ContractAgent("billing"), ContractAgent("billing")
        registry.register(self.descriptor("billing"), ours)
        peer.register(self.descriptor("billing"), theirs)

        registry.deregister("billing")

        assert peer.descriptor("billing") is None  # the record is gone for everyone
        assert peer.get("billing") is theirs  # while the other process still hosts its agent
        peer.register(self.descriptor("billing"), theirs)
        assert self.ids(registry.descriptors()) == ["billing"]
        assert registry.get("billing") is None
