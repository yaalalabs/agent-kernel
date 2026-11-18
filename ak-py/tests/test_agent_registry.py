"""
The agent registry (spec `docs/specs/603-identity-rbac-registry/` section 6, iterations 13 to 15).

Runtime keeps its agents in an `AgentRegistry`, and every agent carries a descriptor: the catalog
entry the surfaces and the authorizer read. This file runs the registry contract over every
backend (in-memory, and the redis-like and DynamoDB ones over fakes standing in for their client
libraries), and covers what sits around it: the descriptor an agent builds for itself,
`Module.describe` as the second descriptor source, the `registry.agents` overlay as the third, the
factory that selects a backend from configuration, and Runtime delegating to the registry.
"""

import fnmatch
import json
import sys
from datetime import datetime

import pytest

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _RegistryConfig
from agentkernel.core.model import AgentDescriptor, AgentIdentitySpec, AgentReplyText, AgentRequestText, AgentSkillDescriptor
from agentkernel.core.module import Module
from agentkernel.core.registry import AgentDescriptorPage, AgentRegistrationError, AgentRegistry, AgentRegistryFactory, InMemoryAgentRegistry
from agentkernel.core.runtime import Runtime
from agentkernel.core.service import AgentService
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.driver.valkey import ValkeyDriver
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.registry.dynamodb import DynamoDBAgentRegistry
from agentkernel.identity.registry.redis import RedisAgentRegistry
from agentkernel.identity.registry.testing import AgentRegistryContract
from agentkernel.identity.registry.valkey import ValkeyAgentRegistry

PREFIX = "ak:registry:"
TABLE_NAME = "ak-agent-registry"


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

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class ToolReportingAgent(StubAgent):
    """Holds its tools the way every adapter holds its native agent: assigned after the base constructor returns."""

    def __init__(self, name: str, tools: list[str], descriptions: dict[str, str] | None = None):
        super().__init__(name)
        self._tools = tools
        self._descriptions = descriptions or {}

    def get_tool_names(self) -> list[str]:
        return list(self._tools)

    def _tool_descriptions(self) -> dict[str, str]:
        return dict(self._descriptions)


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
def runtime() -> Runtime:
    return Runtime(InMemorySessionStore())


class TestInMemoryAgentRegistry(AgentRegistryContract):
    @pytest.fixture
    def registry(self) -> InMemoryAgentRegistry:
        return InMemoryAgentRegistry()

    def test_the_descriptor_handed_in_is_the_one_kept(self, registry):
        # Nothing leaves the process, so there is nothing to stamp or copy.
        descriptor = _descriptor("billing")

        registry.register(descriptor, StubAgent("billing"))

        assert registry.descriptor("billing") is descriptor
        assert descriptor.updated_at is None


class _FakeRedisLikeClient:
    """Minimal in-memory stand-in for the redis/valkey client the shared driver drives.

    Only the commands the registry issues are implemented, so the real registry body runs end to
    end while the assertions stay about the registry rather than about a mock's call log.
    """

    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}
        self.unreachable = False

    def ping(self) -> bool:
        return True

    def set(self, key: str, value, ex: int | None = None, nx: bool = False) -> bool:
        if self.unreachable:
            raise ConnectionError("the store is unreachable")
        self.values[key] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key: str):
        return self.values.get(key)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.sets.pop(key, None)

    def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(member)

    def srem(self, key: str, member: str) -> None:
        self.sets.get(key, set()).discard(member)

    def smembers(self, key: str) -> set:
        return {member.encode() for member in self.sets.get(key, set())}

    def expire(self, name: str, time: int) -> None:
        self.expirations[name] = time

    def scan_iter(self, match: str, count: int | None = None):
        return [key for key in list(self.values) + list(self.sets) if fnmatch.fnmatch(key, match)]


class TestRedisAgentRegistry(AgentRegistryContract):
    """The shared redis-protocol body, driven through RedisAgentRegistry over a fake client."""

    @pytest.fixture
    def client(self) -> _FakeRedisLikeClient:
        return _FakeRedisLikeClient()

    @pytest.fixture
    def make_registry(self, client):
        def _make(ttl: int = 0) -> RedisAgentRegistry:
            registry = RedisAgentRegistry(url="redis://unused:6379", prefix=PREFIX, ttl=ttl)
            # An established client, so the driver never connects; its ping health-check passes.
            registry._driver._client = client
            return registry

        return _make

    @pytest.fixture
    def registry(self, make_registry) -> RedisAgentRegistry:
        return make_registry()

    @pytest.fixture
    def peer(self, make_registry) -> RedisAgentRegistry:
        return make_registry()

    def test_a_descriptor_is_one_document_under_the_prefix_and_a_member_of_the_index(self, registry, client):
        registry.register(_descriptor("billing", version="1.2.0"), StubAgent("billing"))

        assert set(client.values) == {"ak:registry:agent:billing"}
        assert json.loads(client.values["ak:registry:agent:billing"])["version"] == "1.2.0"
        assert client.sets == {"ak:registry:index:all": {"billing"}}

    def test_the_stored_descriptor_is_stamped_and_the_one_handed_in_is_left_alone(self, registry):
        descriptor = _descriptor("billing")

        registry.register(descriptor, StubAgent("billing"))

        assert descriptor.updated_at is None
        assert datetime.fromisoformat(registry.descriptor("billing").updated_at).utcoffset() is not None

    def test_the_stored_descriptor_keeps_the_identity_the_catalog_leaves_out(self, registry, peer):
        """Left out of what is published, not of what is stored: the process that hosts the agent reads it back."""
        identity = {"subject": "svc-billing", "client_id": "billing-client", "client_secret_key": "BILLING_CLIENT_SECRET"}

        registry.register(_descriptor("billing", identity=identity), StubAgent("billing"))

        stored = peer.descriptor("billing")
        assert stored.identity == AgentIdentitySpec(**identity)
        assert "identity" not in stored.catalog_entry()
        assert stored.catalog_entry()["id"] == "billing"

    def test_deregister_deletes_the_document_and_its_index_membership(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))

        registry.deregister("billing")

        assert client.values == {}
        assert client.sets == {"ak:registry:index:all": set()}

    def test_nothing_expires_by_default(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))

        assert client.expirations == {}

    def test_a_configured_ttl_covers_the_document_and_the_index(self, make_registry, client):
        make_registry(ttl=60).register(_descriptor("billing"), StubAgent("billing"))

        assert client.expirations == {"ak:registry:agent:billing": 60, "ak:registry:index:all": 60}

    def test_an_index_member_whose_document_expired_is_not_listed(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))
        registry.register(_descriptor("support"), StubAgent("support"))
        del client.values["ak:registry:agent:billing"]  # its TTL elapsed ahead of the index set

        assert registry.descriptor("billing") is None
        assert [descriptor.id for descriptor in registry.descriptors()] == ["support"]

    def test_an_agent_is_not_hosted_when_its_descriptor_cannot_be_stored(self, registry, client):
        client.unreachable = True

        with pytest.raises(ConnectionError):
            registry.register(_descriptor("billing"), StubAgent("billing"))

        assert registry.get("billing") is None
        assert registry.agents() == {}


class TestValkeyAgentRegistry:
    """Valkey shares the redis body verbatim, so its own wiring plus one round trip covers it."""

    def test_it_runs_the_shared_body_through_a_valkey_driver_under_its_prefix(self):
        registry = ValkeyAgentRegistry(url="valkey://unused:6379", prefix=PREFIX)
        client = _FakeRedisLikeClient()
        registry._driver._client = client

        registry.register(_descriptor("billing", version="1.2.0"), StubAgent("billing"))

        assert isinstance(registry._driver, ValkeyDriver)
        assert set(client.values) == {"ak:registry:agent:billing"}
        assert registry.descriptor("billing").version == "1.2.0"


class _FakeDynamoDBTable:
    """Stand-in for the boto3 Table, covering the paginated scan a listing follows."""

    def __init__(self, items: dict):
        self._items = items
        self.scan_calls: list[dict] = []
        self.page_size: int | None = None

    def scan(self, **kwargs) -> dict:
        self.scan_calls.append(kwargs)
        items = list(self._items.values())
        start = items.index(kwargs["ExclusiveStartKey"]) if "ExclusiveStartKey" in kwargs else 0
        if self.page_size is None:
            return {"Items": items[start:]}
        response = {"Items": items[start : start + self.page_size]}
        if start + self.page_size < len(items):
            response["LastEvaluatedKey"] = items[start + self.page_size]
        return response


class _FakeDynamoDBDriver:
    """Stand-in for DynamoDBDriver: the registry's writes and reads against one item per agent."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.table = _FakeDynamoDBTable(self.items)
        self.unreachable = False

    def put(self, item: dict) -> None:
        if self.unreachable:
            raise ConnectionError("the store is unreachable")
        self.items[item["agent_id"]] = item

    def get(self, pk_value: str, sk_value=None) -> dict | None:
        return self.items.get(pk_value)

    def delete(self, pk_value: str, sk_value=None) -> None:
        self.items.pop(pk_value, None)


class TestDynamoDBAgentRegistry(AgentRegistryContract):
    @pytest.fixture
    def driver(self) -> _FakeDynamoDBDriver:
        return _FakeDynamoDBDriver()

    @pytest.fixture
    def make_registry(self, driver):
        def _make() -> DynamoDBAgentRegistry:
            registry = DynamoDBAgentRegistry(table_name=TABLE_NAME)
            registry._driver = driver
            return registry

        return _make

    @pytest.fixture
    def registry(self, make_registry) -> DynamoDBAgentRegistry:
        return make_registry()

    @pytest.fixture
    def peer(self, make_registry) -> DynamoDBAgentRegistry:
        return make_registry()

    def test_a_descriptor_is_one_item_keyed_by_agent_id_with_its_timestamp_beside_it(self, registry, driver):
        registry.register(_descriptor("billing", version="1.2.0"), StubAgent("billing"))

        [item] = driver.items.values()
        assert set(item) == {"agent_id", "data", "updated_at"}
        assert item["agent_id"] == "billing"
        stored = json.loads(item["data"])
        assert stored["version"] == "1.2.0"
        assert item["updated_at"] == stored["updated_at"] is not None

    def test_the_driver_is_built_for_the_configured_table_keyed_by_agent_id(self):
        driver = DynamoDBAgentRegistry(table_name="agents", ttl=120)._driver

        assert (driver._table_name, driver._partition_key, driver._sort_key, driver._ttl) == ("agents", "agent_id", None, 120)

    def test_a_listing_follows_the_scan_past_its_first_page(self, registry, driver):
        driver.table.page_size = 2
        for id in ("a", "b", "c", "d", "e"):
            registry.register(_descriptor(id), StubAgent(id))

        assert sorted(descriptor.id for descriptor in registry.descriptors()) == ["a", "b", "c", "d", "e"]
        assert len(driver.table.scan_calls) == 3

    def test_an_agent_is_not_hosted_when_its_descriptor_cannot_be_stored(self, registry, driver):
        driver.unreachable = True

        with pytest.raises(ConnectionError):
            registry.register(_descriptor("billing"), StubAgent("billing"))

        assert registry.get("billing") is None
        assert registry.agents() == {}


class _CustomAgentRegistry(InMemoryAgentRegistry):
    """Bring-your-own registry used to pin dotted-path resolution."""


def _configure_registry(monkeypatch, **fields) -> None:
    """Point AKConfig at a registry block carrying the given fields."""
    config = AKConfig.get().model_copy(update={"registry": _RegistryConfig.model_validate(fields)})
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))


@pytest.fixture
def _default_config(monkeypatch):
    """The configuration with no file behind it, reloaded afterwards so nothing here leaks into another test."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    yield
    AKConfig._reset()


@pytest.mark.usefixtures("_default_config")
class TestAgentRegistryFactory:
    def test_with_no_registry_block_each_build_is_a_separate_in_memory_registry(self):
        first = AgentRegistryFactory.build()
        second = AgentRegistryFactory.build()

        first.register(_descriptor("billing"), StubAgent("billing"))

        assert isinstance(first, InMemoryAgentRegistry)
        assert second.agents() == {}

    def test_the_in_memory_type_builds_the_in_memory_registry(self, monkeypatch):
        _configure_registry(monkeypatch, type="in_memory")

        assert isinstance(AgentRegistryFactory.build(), InMemoryAgentRegistry)

    def test_a_config_object_with_no_registry_attribute_builds_the_in_memory_registry(self, monkeypatch):
        class _Bare:
            """A configuration stub from before the registry block existed."""

        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: _Bare))

        assert isinstance(AgentRegistryFactory.build(), InMemoryAgentRegistry)

    def test_the_redis_type_builds_a_redis_registry_from_its_block(self, monkeypatch):
        _configure_registry(monkeypatch, type="redis", redis={"url": "redis://cache:6379", "prefix": "ak:reg:", "ttl": 30})

        registry = AgentRegistryFactory.build()

        assert isinstance(registry, RedisAgentRegistry)
        assert (registry._driver._url, registry._driver.key("agent:billing"), registry._driver.ttl) == (
            "redis://cache:6379",
            "ak:reg:agent:billing",
            30,
        )

    def test_the_valkey_type_builds_a_valkey_registry_from_its_block(self, monkeypatch):
        _configure_registry(monkeypatch, type="valkey", valkey={"url": "valkey://cache:6379"})

        registry = AgentRegistryFactory.build()

        assert isinstance(registry, ValkeyAgentRegistry)
        assert (registry._driver._url, registry._driver.key("agent:billing"), registry._driver.ttl) == (
            "valkey://cache:6379",
            "ak:registry:agent:billing",
            0,
        )

    def test_the_dynamodb_type_builds_a_dynamodb_registry_from_its_block(self, monkeypatch):
        _configure_registry(monkeypatch, type="dynamodb", dynamodb={"table_name": "agents", "ttl": 120})

        registry = AgentRegistryFactory.build()

        assert isinstance(registry, DynamoDBAgentRegistry)
        assert (registry._driver._table_name, registry._driver._ttl) == ("agents", 120)

    @pytest.mark.parametrize("backend", ["redis", "valkey", "dynamodb"])
    def test_a_store_type_without_its_block_is_a_config_error_naming_it(self, monkeypatch, backend):
        _configure_registry(monkeypatch, type=backend)

        with pytest.raises(AKConfigError, match=f"registry.{backend}"):
            AgentRegistryFactory.build()

    def test_a_dotted_path_builds_a_bring_your_own_registry(self, monkeypatch):
        _configure_registry(monkeypatch, type=f"{_CustomAgentRegistry.__module__}._CustomAgentRegistry")

        assert isinstance(AgentRegistryFactory.build(), _CustomAgentRegistry)

    def test_a_dotted_path_to_something_else_is_a_config_error(self, monkeypatch):
        _configure_registry(monkeypatch, type="agentkernel.core.model.AgentDescriptor")

        with pytest.raises(AKConfigError, match="not a AgentRegistry subclass"):
            AgentRegistryFactory.build()

    def test_an_unknown_type_is_a_config_error_naming_the_choices(self, monkeypatch):
        _configure_registry(monkeypatch, type="postgres")

        with pytest.raises(AKConfigError, match="unknown registry type 'postgres'.*in_memory.*redis.*valkey.*dynamodb"):
            AgentRegistryFactory.build()

    def test_a_missing_client_library_names_the_extra_that_ships_it(self, monkeypatch):
        _configure_registry(monkeypatch, type="redis", redis={})
        monkeypatch.setitem(sys.modules, "agentkernel.identity.registry.redis", None)  # as if `redis` were not installed

        with pytest.raises(ImportError, match="registry.type: redis requires the 'redis' extra"):
            AgentRegistryFactory.build()

    def test_no_overlay_means_the_backend_itself_is_the_registry(self, monkeypatch):
        _configure_registry(monkeypatch, type=f"{_CustomAgentRegistry.__module__}._CustomAgentRegistry", agents={"billing": {}})

        assert type(AgentRegistryFactory.build()) is _CustomAgentRegistry  # an entry that sets nothing adds nothing


@pytest.mark.usefixtures("_default_config")
class TestRegistryOverlay:
    """The `registry.agents.<id>` overlay: the third descriptor source, applied as the agent registers."""

    def _runtime(self, monkeypatch, **agents) -> Runtime:
        _configure_registry(monkeypatch, agents=agents)
        return Runtime(InMemorySessionStore())

    def test_overlaid_fields_replace_the_agents_own_and_the_rest_are_kept(self, monkeypatch):
        runtime = self._runtime(
            monkeypatch, billing={"description": "Answers invoice questions", "version": "2.0.0", "visibility": "public", "tags": ["finance"]}
        )

        runtime.register(ToolReportingAgent("billing", ["refund"]))

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.description, descriptor.version, descriptor.visibility, descriptor.tags) == (
            "Answers invoice questions",
            "2.0.0",
            "public",
            ["finance"],
        )
        assert (descriptor.id, descriptor.runner, descriptor.tools) == ("billing", "stub", ["refund"])

    def test_the_agent_carries_the_overlaid_descriptor_too(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"version": "2.0.0", "surfaces": ["rest"]})
        agent = StubAgent("billing")

        runtime.register(agent)

        assert (agent.descriptor.version, agent.descriptor.surfaces) == ("2.0.0", ["rest"])
        assert agent.descriptor == runtime.registry.descriptor("billing")

    def test_the_overlay_wins_over_module_describe_and_keeps_the_fields_it_does_not_name(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"version": "2.0.0"})

        with runtime:
            native = NativeAgent("billing")
            StubModule([native]).describe(native, version="9.9.9", owner="alice")

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.version, descriptor.owner) == ("2.0.0", "alice")

    def test_an_agent_the_overlay_does_not_name_is_left_as_declared(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"version": "2.0.0"})
        agent = StubAgent("support")
        declared = agent.descriptor

        runtime.register(agent)

        assert agent.descriptor is declared
        assert runtime.registry.descriptor("support").version == "0.0.0"

    @pytest.mark.asyncio
    async def test_an_overlaid_identity_subject_is_the_actor_of_the_agents_runs(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"identity": {"subject": "svc-billing"}})
        agent = StubAgent("billing")
        runtime.register(agent)

        await runtime.run(agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")])

        assert agent.runner.principals[0].actor.subject == "svc-billing"

    def test_a_refused_registration_leaves_the_agents_descriptor_as_it_was(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"version": "2.0.0"})
        runtime.register(StubAgent("billing"))
        refused = StubAgent("billing")
        declared = refused.descriptor

        with pytest.raises(AgentRegistrationError):
            runtime.register(refused)

        assert refused.descriptor is declared and declared.version == "0.0.0"

    def test_everything_but_registration_is_the_backends_own_answer(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"tags": ["finance"]})
        agent = StubAgent("billing")
        runtime.register(agent)

        assert runtime.agents() == {"billing": agent}
        assert runtime.registry.get("billing") is agent
        assert _ids(runtime.registry.list(tags=["finance"])) == ["billing"]
        assert [descriptor.id for descriptor in runtime.registry.descriptors()] == ["billing"]

        runtime.deregister(agent)

        assert runtime.agents() == {}
        assert runtime.registry.descriptor("billing") is None

    def test_clear_reaches_the_backend(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"tags": ["finance"]})
        runtime.register(StubAgent("billing"))

        runtime.registry.clear()

        assert runtime.agents() == {} and runtime.registry.descriptors() == []


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

    def test_a_skill_takes_the_description_the_adapter_reports_for_its_tool(self):
        agent = ToolReportingAgent("billing", ["lookup_invoice", "refund"], {"lookup_invoice": "Look up an invoice by id."})

        assert agent.descriptor.skills == [
            AgentSkillDescriptor(id="lookup_invoice", name="lookup_invoice", description="Look up an invoice by id."),
            AgentSkillDescriptor(id="refund", name="refund", description=""),  # no description reported for it
        ]

    def test_a_tool_reported_twice_is_listed_once_in_first_seen_order(self):
        descriptor = ToolReportingAgent("billing", ["refund", "lookup_invoice", "refund"]).descriptor

        assert descriptor.tools == ["refund", "lookup_invoice"]
        assert [skill.id for skill in descriptor.skills] == ["refund", "lookup_invoice"]

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


class TestAvailability:
    """`AgentService.ensure_agent_available` asks the registry, so a process answers for agents it does not host."""

    def test_a_named_agent_the_registry_knows_is_available_without_being_hosted(self, descriptor_only_registry):
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            AgentService.ensure_agent_available("billing")

    def test_a_named_agent_the_registry_does_not_know_is_not_available(self, descriptor_only_registry):
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available("support")

    def test_an_unnamed_request_needs_the_registry_to_know_some_agent(self, descriptor_only_registry):
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([])):
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available(None)

        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            AgentService.ensure_agent_available(None)

    def test_an_agent_this_process_hosts_is_available_without_reading_the_store(self):
        class _HostedOnly(InMemoryAgentRegistry):
            """Fails on a store read: a hosted agent must be answered from the process's own agents."""

            def descriptor(self, id):
                raise AssertionError("the registry's store was read for an agent this process hosts")

            def descriptors(self):
                raise AssertionError("the registry's store was read while this process hosts an agent")

        runtime = Runtime(InMemorySessionStore(), registry=_HostedOnly())
        runtime.register(StubAgent("billing"))

        with runtime:
            AgentService.ensure_agent_available("billing")
            AgentService.ensure_agent_available(None)
