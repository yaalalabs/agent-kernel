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
from agentkernel.core.registry import (
    AgentDescriptorPage,
    AgentNotFoundError,
    AgentRegistrationError,
    AgentRegistry,
    AgentRegistryFactory,
    InMemoryAgentRegistry,
)
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


class NativelyDescribedAgent(StubAgent):
    """An adapter whose framework gives an agent a description of its own, apart from its instructions."""

    def __init__(self, name: str, native_description: str):
        super().__init__(name)
        self._native = native_description

    def _native_description(self) -> str:
        return self._native


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


class _FakeRedisLikePipeline:
    """A MULTI/EXEC block of the fake client: commands are queued and applied together, or not at all."""

    def __init__(self, client: "_FakeRedisLikeClient"):
        self._client = client
        self._commands: list[tuple[str, tuple]] = []

    def set(self, key: str, value) -> "_FakeRedisLikePipeline":
        self._commands.append(("set", (key, value)))
        return self

    def sadd(self, key: str, member: str) -> "_FakeRedisLikePipeline":
        self._commands.append(("sadd", (key, member)))
        return self

    def delete(self, *keys: str) -> "_FakeRedisLikePipeline":
        self._commands.append(("delete", keys))
        return self

    def srem(self, key: str, member: str) -> "_FakeRedisLikePipeline":
        self._commands.append(("srem", (key, member)))
        return self

    def execute(self) -> None:
        if self._client.unreachable:
            raise ConnectionError("the store is unreachable")
        self._client.transactions.append([name for name, _ in self._commands])
        for name, arguments in self._commands:
            getattr(self._client, name)(*arguments)


class _FakeRedisLikeClient:
    """Minimal in-memory stand-in for the redis/valkey client the shared driver drives.

    Only the commands the registry issues are implemented, so the real registry body runs end to
    end while the assertions stay about the registry rather than about a mock's call log.
    """

    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}
        self.transactions: list[list[str]] = []
        self.reads: list[str] = []
        self.unreachable = False

    def ping(self) -> bool:
        return True

    def pipeline(self) -> _FakeRedisLikePipeline:
        return _FakeRedisLikePipeline(self)

    def set(self, key: str, value, ex: int | None = None, nx: bool = False) -> bool:
        self.values[key] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key: str):
        self.reads.append(key)
        return self.values.get(key)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.sets.pop(key, None)

    def exists(self, key: str) -> int:
        return int(key in self.values or key in self.sets)

    def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(member)

    def srem(self, key: str, member: str) -> None:
        members = self.sets.get(key, set())
        members.discard(member)
        if not members:
            self.sets.pop(key, None)  # as Redis does: a set that lost its last member is gone

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
        def _make() -> RedisAgentRegistry:
            registry = RedisAgentRegistry(url="redis://unused:6379", prefix=PREFIX)
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
        assert client.sets == {}

    def test_nothing_ever_expires(self, registry, client):
        # Nothing registers a hosted agent again while its process runs, so a record that expired would drop
        # a running agent from every listing. The registry takes no TTL at all.
        registry.register(_descriptor("billing"), StubAgent("billing"))

        assert client.expirations == {}
        assert registry._driver.ttl == 0

    def test_the_document_and_its_index_membership_are_written_in_one_transaction(self, registry, client):
        # Two separate commands could leave a descriptor a peer resolves by id and never lists.
        registry.register(_descriptor("billing"), StubAgent("billing"))

        assert client.transactions == [["set", "sadd"]]

    def test_the_document_and_its_index_membership_are_removed_in_one_transaction(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))

        registry.deregister("billing")

        assert client.transactions[-1] == ["delete", "srem"]

    def test_a_listing_checks_for_any_agent_without_reading_a_document(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))
        client.reads.clear()

        assert registry.is_empty() is False
        assert client.reads == []

    def test_an_index_member_without_a_document_does_not_make_the_registry_look_populated(self, registry, client):
        # Emptiness must agree with the listing: a member left behind when its document was deleted by hand would
        # otherwise admit a request naming no agent with nothing to run it, and silence the no-agents warning.
        registry.register(_descriptor("billing"), StubAgent("billing"))
        del client.values["ak:registry:agent:billing"]

        assert registry.descriptors() == []
        assert registry.is_empty() is True

    def test_an_index_member_without_a_document_is_not_listed(self, registry, client):
        registry.register(_descriptor("billing"), StubAgent("billing"))
        registry.register(_descriptor("support"), StubAgent("support"))
        del client.values["ak:registry:agent:billing"]  # removed by hand, without its index membership

        assert registry.descriptor("billing") is None
        assert [descriptor.id for descriptor in registry.descriptors()] == ["support"]

    def test_an_agent_is_not_hosted_when_its_descriptor_cannot_be_stored(self, registry, client):
        client.unreachable = True

        with pytest.raises(ConnectionError):
            registry.register(_descriptor("billing"), StubAgent("billing"))

        assert registry.get("billing") is None
        assert registry.agents() == {}
        assert (client.values, client.sets) == ({}, {})

    def test_an_agent_stays_hosted_when_its_record_cannot_be_removed_so_a_retry_removes_it(self, registry, peer, client):
        # Dropped locally first, a retry would find nothing to deregister and peers would keep advertising it.
        agent = StubAgent("billing")
        registry.register(_descriptor("billing"), agent)
        client.unreachable = True

        with pytest.raises(ConnectionError):
            registry.deregister("billing")

        assert registry.get("billing") is agent
        client.unreachable = False
        registry.deregister("billing")
        assert registry.get("billing") is None
        assert peer.descriptor("billing") is None


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
    """Stand-in for the boto3 Table, covering the paginated scan a listing follows.

    A page ends with the primary key of its last item, and the next scan starts after that key, as
    DynamoDB pages; `Limit` caps the items a scan returns.
    """

    def __init__(self, items: dict):
        self._items = items
        self.scan_calls: list[dict] = []
        self.page_size: int | None = None

    def scan(self, **kwargs) -> dict:
        self.scan_calls.append(kwargs)
        ids = sorted(self._items)
        start = ids.index(kwargs["ExclusiveStartKey"]["agent_id"]) + 1 if "ExclusiveStartKey" in kwargs else 0
        sizes = [size for size in (self.page_size, kwargs.get("Limit")) if size is not None]
        end = start + min(sizes) if sizes else len(ids)
        response = {"Items": [self._items[id] for id in ids[start:end]]}
        if end < len(ids):
            response["LastEvaluatedKey"] = {"agent_id": ids[end - 1]}
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
        if self.unreachable:
            raise ConnectionError("the store is unreachable")
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
        driver = DynamoDBAgentRegistry(table_name="agents")._driver

        # No TTL: a record that expired would drop a running agent from every listing.
        assert (driver._table_name, driver._partition_key, driver._sort_key, driver._ttl) == ("agents", "agent_id", None, 0)

    def test_a_listing_follows_the_scan_past_its_first_page(self, registry, driver):
        driver.table.page_size = 2
        for id in ("a", "b", "c", "d", "e"):
            registry.register(_descriptor(id), StubAgent(id))

        assert sorted(descriptor.id for descriptor in registry.descriptors()) == ["a", "b", "c", "d", "e"]
        assert [call.get("ExclusiveStartKey") for call in driver.table.scan_calls] == [None, {"agent_id": "b"}, {"agent_id": "d"}]

    def test_a_listing_reads_the_table_consistently(self, registry, driver):
        # A2A cards and MCP tools are built from one listing at mount: an eventually consistent scan could miss
        # an agent that registered a moment before, and it would stay unserved until the process restarts.
        driver.table.page_size = 1
        for id in ("a", "b"):
            registry.register(_descriptor(id), StubAgent(id))

        registry.descriptors()

        assert [call["ConsistentRead"] for call in driver.table.scan_calls] == [True, True]

    def test_checking_for_any_agent_reads_one_item_not_the_table(self, registry, driver):
        assert registry.is_empty() is True
        for id in ("a", "b", "c"):
            registry.register(_descriptor(id), StubAgent(id))
        driver.table.scan_calls.clear()

        assert registry.is_empty() is False
        assert driver.table.scan_calls == [{"Limit": 1, "ConsistentRead": True}]

    def test_an_agent_is_not_hosted_when_its_descriptor_cannot_be_stored(self, registry, driver):
        driver.unreachable = True

        with pytest.raises(ConnectionError):
            registry.register(_descriptor("billing"), StubAgent("billing"))

        assert registry.get("billing") is None
        assert registry.agents() == {}

    def test_an_agent_stays_hosted_when_its_record_cannot_be_removed_so_a_retry_removes_it(self, registry, peer, driver):
        agent = StubAgent("billing")
        registry.register(_descriptor("billing"), agent)
        driver.unreachable = True

        with pytest.raises(ConnectionError):
            registry.deregister("billing")

        assert registry.get("billing") is agent
        driver.unreachable = False
        registry.deregister("billing")
        assert registry.get("billing") is None
        assert peer.descriptor("billing") is None


class _CustomAgentRegistry(InMemoryAgentRegistry):
    """Bring-your-own registry used to pin dotted-path resolution."""


class _SharedStoreRegistry(InMemoryAgentRegistry):
    """A registry over a store another process already wrote into: it knows `RECORDS` and hosts none of them."""

    RECORDS: list[AgentDescriptor] = []

    def __init__(self) -> None:
        super().__init__()
        self._descriptors = {descriptor.id: descriptor for descriptor in self.RECORDS}


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
        _configure_registry(monkeypatch, type="redis", redis={"url": "redis://cache:6379", "prefix": "ak:reg:"})

        registry = AgentRegistryFactory.build()

        assert isinstance(registry, RedisAgentRegistry)
        assert (registry._driver._url, registry._driver.key("agent:billing"), registry._driver.ttl) == (
            "redis://cache:6379",
            "ak:reg:agent:billing",
            0,
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
        _configure_registry(monkeypatch, type="dynamodb", dynamodb={"table_name": "agents"})

        registry = AgentRegistryFactory.build()

        assert isinstance(registry, DynamoDBAgentRegistry)
        assert (registry._driver._table_name, registry._driver._ttl) == ("agents", 0)

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

    def test_an_overlaid_description_wins_over_the_native_one_and_an_empty_one_withholds_it(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"description": "Refunds and invoices"}, support={"description": ""})

        runtime.register(NativelyDescribedAgent("billing", "Answers invoice questions"))
        runtime.register(NativelyDescribedAgent("support", "Written for a sibling agent, not for publication"))
        runtime.register(NativelyDescribedAgent("search", "Searches the knowledge base"))

        described = {descriptor.id: descriptor.description for descriptor in runtime.registry.descriptors()}
        assert described == {"billing": "Refunds and invoices", "support": "", "search": "Searches the knowledge base"}

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

    def test_an_overlaid_identity_keeps_the_fields_the_code_declared_and_the_overlay_leaves_out(self, monkeypatch):
        # A field left out of the overlay keeps the value the code gave it. That holds inside `identity` too:
        # naming the subject in configuration must not drop the client credential the code declared.
        runtime = self._runtime(monkeypatch, billing={"identity": {"subject": "svc-billing"}})

        with runtime:
            native = NativeAgent("billing")
            StubModule([native]).describe(
                native, identity={"subject": "billing", "client_id": "billing-client", "client_secret_key": "BILLING_SECRET"}
            )

        expected = AgentIdentitySpec(subject="svc-billing", client_id="billing-client", client_secret_key="BILLING_SECRET")
        assert runtime.registry.descriptor("billing").identity == expected
        assert runtime.agents()["billing"].descriptor.identity == expected

    def test_an_identity_read_from_another_process_is_overlaid_field_by_field_too(self, monkeypatch):
        stored = _descriptor("billing", identity={"subject": "billing", "client_id": "billing-client"})
        registry = self._serving_registry(monkeypatch, [stored], billing={"identity": {"subject": "svc-billing"}})

        assert registry.descriptor("billing").identity == AgentIdentitySpec(subject="svc-billing", client_id="billing-client")

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

    def _serving_registry(self, monkeypatch, records: list[AgentDescriptor], **agents) -> AgentRegistry:
        """The registry of a process that serves agents another process registered, with its own overlay."""
        monkeypatch.setattr(_SharedStoreRegistry, "RECORDS", records)
        _configure_registry(monkeypatch, type=f"{_SharedStoreRegistry.__module__}._SharedStoreRegistry", agents=agents)
        return AgentRegistryFactory.build()

    def test_a_process_reads_an_agent_it_does_not_host_through_its_own_overlay(self, monkeypatch):
        # The removed a2a.agents / mcp.agents / agui.agents lists were read by the process that mounts the surface.
        # Their replacement has to hold there too, or a restriction set in that process's configuration is not one.
        registry = self._serving_registry(monkeypatch, [_descriptor("billing"), _descriptor("support")], billing={"surfaces": ["rest"]})

        read = registry.descriptor("billing")

        assert registry.get("billing") is None  # hosted elsewhere: nothing registered here
        assert read.surfaces == ["rest"]
        assert (read.exposed_on("rest"), read.exposed_on("a2a"), read.exposed_on("mcp")) == (True, False, False)
        assert {descriptor.id: descriptor.surfaces for descriptor in registry.descriptors()} == {"billing": ["rest"], "support": None}

    def test_the_overlay_on_read_keeps_what_the_record_carries_for_the_fields_it_does_not_name(self, monkeypatch):
        stored = _descriptor("billing", description="Answers invoice questions", tools=["refund"], surfaces=["rest", "a2a"])
        registry = self._serving_registry(monkeypatch, [stored], billing={"surfaces": ["rest"], "version": "2.0.0"})

        read = registry.descriptor("billing")

        assert (read.description, read.tools) == ("Answers invoice questions", ["refund"])
        assert (read.surfaces, read.version) == (["rest"], "2.0.0")

    def test_a_listing_filters_on_the_tags_the_overlay_sets(self, monkeypatch):
        registry = self._serving_registry(monkeypatch, [_descriptor("billing"), _descriptor("support")], billing={"tags": ["finance"]})

        assert _ids(registry.list(tags=["finance"])) == ["billing"]

    def test_an_unknown_id_still_reads_as_none_under_an_overlay_that_names_it(self, monkeypatch):
        registry = self._serving_registry(monkeypatch, [], billing={"surfaces": ["rest"]})

        assert registry.descriptor("billing") is None
        assert registry.descriptors() == []
        assert registry.is_empty() is True

    def test_an_overlay_keyed_in_another_case_applies(self, monkeypatch):
        # An environment variable lowercases the id (AK_REGISTRY__AGENTS__Billing__SURFACES arrives as `billing`).
        # Matched exactly only, the restriction would be dropped without a word.
        runtime = self._runtime(monkeypatch, billing={"surfaces": ["rest"]})
        agent = StubAgent("Billing")

        runtime.register(agent)

        assert agent.descriptor.surfaces == ["rest"]
        assert runtime.registry.descriptor("Billing").surfaces == ["rest"]

    def test_a_restriction_set_through_the_environment_reaches_an_agent_with_a_mixed_case_id(self, monkeypatch):
        """End to end, from the variable: the environment source lowercases the id on the way in."""
        monkeypatch.setenv("AK_REGISTRY__AGENTS__Billing__SURFACES", '["rest"]')
        AKConfig._reset()
        assert list(AKConfig.get().registry.agents) == ["billing"]  # how the id arrives
        runtime = Runtime(InMemorySessionStore())
        agent = StubAgent("Billing")

        runtime.register(agent)

        read = runtime.registry.descriptor("Billing")
        assert read.surfaces == ["rest"]
        assert (read.exposed_on("rest"), read.exposed_on("mcp"), read.exposed_on("a2a")) == (True, False, False)
        assert agent.descriptor.surfaces == ["rest"]

    def test_an_exact_overlay_key_wins_over_one_in_another_case(self, monkeypatch):
        runtime = self._runtime(monkeypatch, billing={"version": "1.0.0"}, Billing={"version": "2.0.0"})

        runtime.register(StubAgent("Billing"))
        runtime.register(StubAgent("billing"))

        assert runtime.registry.descriptor("Billing").version == "2.0.0"
        assert runtime.registry.descriptor("billing").version == "1.0.0"


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

    def test_the_description_is_seeded_from_the_native_agents_own_description(self):
        descriptor = NativelyDescribedAgent("billing", "Answers invoice questions").descriptor

        assert descriptor.description == "Answers invoice questions"

    def test_the_instructions_never_seed_the_description(self):
        # StubAgent.get_description() returns its instructions, as most adapters' does; nothing reads it.
        assert StubAgent("billing").descriptor.description == ""
        assert StubAgent("billing")._native_description() == ""

    @pytest.mark.parametrize("native", [None, "", "   "])
    def test_a_native_description_that_says_nothing_seeds_nothing(self, native):
        assert NativelyDescribedAgent("billing", native).descriptor.description == ""

    def test_a_declared_description_wins_over_the_native_one(self, runtime):
        runtime.register(NativelyDescribedAgent("billing", "Answers invoice questions"))
        agent = runtime.agents()["billing"]

        agent._set_descriptor(agent.descriptor.model_copy(update={"description": "Refunds and invoices"}))
        runtime.register(agent)

        assert runtime.registry.descriptor("billing").description == "Refunds and invoices"

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

    def test_an_adapter_that_still_builds_its_own_card_is_told_once_that_nothing_calls_it(self, caplog):
        class _LegacyAgent(StubAgent):
            """An adapter from before the registry: it builds its own A2A card."""

            def get_a2a_card(self):
                return "a hand-built card"

        with caplog.at_level("WARNING", logger="ak.core.agent"):
            _LegacyAgent("billing").descriptor
            _LegacyAgent("support").descriptor

        warnings = [record.getMessage() for record in caplog.records]
        assert len(warnings) == 1  # per class, not per agent
        assert "_LegacyAgent" in warnings[0] and "get_a2a_card" in warnings[0] and "Module.describe" in warnings[0]

    def test_an_adapter_without_the_removed_method_is_not_warned_about(self, caplog):
        with caplog.at_level("WARNING", logger="ak.core.agent"):
            StubAgent("billing").descriptor

        assert [record.getMessage() for record in caplog.records] == []


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

    def test_a_described_description_replaces_the_native_one(self, runtime):
        class NativelyDescribedModule(StubModule):
            def _wrap(self, agent: NativeAgent, agents: list[NativeAgent]) -> Agent:
                return NativelyDescribedAgent(agent.name, "Answers invoice questions")

        with runtime:
            native = NativeAgent("billing")
            module = NativelyDescribedModule([native])
            assert runtime.registry.descriptor("billing").description == "Answers invoice questions"

            module.describe(native, description="Refunds and invoices")

        assert runtime.registry.descriptor("billing").description == "Refunds and invoices"
        assert module.get_agent("billing").descriptor.description == "Refunds and invoices"

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

    @pytest.mark.parametrize(
        "field, value",
        [("tools", ["read_only_lookup"]), ("runner", "openai"), ("supports_streaming", True), ("updated_at", "2026-01-01T00:00:00+00:00")],
    )
    def test_what_the_adapter_the_runner_and_the_registry_report_cannot_be_described(self, runtime, field, value):
        # A descriptor that says its runner streams while the runner does not opens an AG-UI stream that can only fail,
        # and a tool list that is not the agent's names tools it cannot call to whoever writes a policy from it.
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])
            before = runtime.registry.descriptor("billing")

            with pytest.raises(ValueError, match=field):
                module.describe(native, owner="alice", **{field: value})

        assert runtime.registry.descriptor("billing") == before

    def test_the_name_and_the_skills_stay_declarable(self, runtime):
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])

            module.describe(native, name="Billing desk", skills=[{"id": "refunds", "name": "Refunds", "description": "Refunds an invoice"}])

        descriptor = runtime.registry.descriptor("billing")
        assert (descriptor.id, descriptor.name, descriptor.tools) == ("billing", "Billing desk", ["search"])
        assert [skill.id for skill in descriptor.skills] == ["refunds"]

    def test_the_agent_does_not_carry_the_described_fields_while_the_registry_is_still_writing_them(self):
        """A run on another thread during a slow store write must not act as something no reader can see yet:
        the agent takes the new descriptor once the registry has it, never before."""
        seen_during_the_write = []

        class _Observing(InMemoryAgentRegistry):
            def register(self, descriptor, agent):
                seen_during_the_write.append(agent.descriptor.identity.subject)
                super().register(descriptor, agent)

        runtime = Runtime(InMemorySessionStore(), registry=_Observing())
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])
            module.describe(native, identity={"subject": "svc-old"})

            module.describe(native, identity={"subject": "svc-new"})

        # The load, the first describe and the second: at each write the agent still carried what it had before.
        assert seen_during_the_write == [None, None, "svc-old"]
        assert module.get_agent("billing").descriptor.identity.subject == "svc-new"

    def test_a_registration_the_registry_refuses_leaves_the_agent_as_it_was_described(self):
        class _FailingStore(InMemoryAgentRegistry):
            """Accepts the first registration and then loses its store."""

            unreachable = False

            def register(self, descriptor, agent):
                if self.unreachable:
                    raise ConnectionError("the store is unreachable")
                super().register(descriptor, agent)

        registry = _FailingStore()
        runtime = Runtime(InMemorySessionStore(), registry=registry)
        with runtime:
            native = NativeAgent("billing")
            module = StubModule([native])
            module.describe(native, identity={"subject": "svc-old"})
            registry.unreachable = True

            with pytest.raises(ConnectionError):
                module.describe(native, identity={"subject": "svc-new"})

        # The agent would otherwise act as `svc-new` while every other process still reads `svc-old`.
        assert module.get_agent("billing").descriptor.identity.subject == "svc-old"
        assert registry.descriptor("billing").identity.subject == "svc-old"

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


class TestModuleLoadRollback:
    """A load that fails part way deregisters what it registered. With a shared registry that cleanup can fail too."""

    class _FailingStore(InMemoryAgentRegistry):
        """Refuses to register `support`, and cannot remove `billing` while its store is down."""

        def __init__(self):
            super().__init__()
            self.down = True

        def register(self, descriptor, agent):
            if descriptor.id == "support":
                raise ConnectionError("the store went down while registering support")
            super().register(descriptor, agent)

        def deregister(self, id):
            if id == "billing" and self.down:
                raise TimeoutError("the store is still down")
            super().deregister(id)

    def _failed_load(self):
        registry = self._FailingStore()
        runtime = Runtime(InMemorySessionStore(), registry=registry)
        with runtime:
            module = StubModule([])
            with pytest.raises(Exception) as raised:
                module.load([NativeAgent("billing"), NativeAgent("search"), NativeAgent("support")])
        return runtime, registry, module, raised.value

    def test_the_error_that_failed_the_load_is_the_one_raised_whatever_the_cleanup_does(self):
        _, _, _, error = self._failed_load()

        assert isinstance(error, ConnectionError) and "registering support" in str(error)

    def test_every_registered_agent_is_cleaned_up_even_after_one_cleanup_fails(self):
        _, registry, _, _ = self._failed_load()

        # `search` comes after `billing`, whose removal failed: it is still deregistered.
        assert list(registry.agents()) == ["billing"]

    def test_the_agents_that_could_not_be_removed_are_kept_so_unload_can_finish_the_cleanup(self):
        runtime, registry, module, _ = self._failed_load()
        assert [agent.name for agent in module.agents] == ["billing"]
        registry.down = False

        with runtime:
            module.unload()
            module.load([NativeAgent("billing"), NativeAgent("search")])

        assert sorted(registry.agents()) == ["billing", "search"]


class TestAgentNotFoundError:
    """The one error for an agent a request named and cannot have: unknown now, hidden once the access gate lands."""

    def test_it_names_the_agent_in_one_fixed_text(self):
        error = AgentNotFoundError("billing")

        assert (str(error), error.agent) == ("Agent 'billing' not found", "billing")

    def test_it_is_a_lookup_error_a_surface_cannot_mistake_for_a_missing_key(self):
        # A KeyError or an IndexError raised by a run is a failure (500), and a schedule route reads a KeyError as a
        # missing schedule: a surface maps this class alone to 404.
        assert issubclass(AgentNotFoundError, LookupError)
        assert not issubclass(AgentNotFoundError, (KeyError, IndexError))
        assert not isinstance(KeyError("billing"), AgentNotFoundError)

    def test_it_survives_a_copy_with_its_text_unchanged(self):
        import copy
        import pickle

        error = AgentNotFoundError("billing")

        assert str(pickle.loads(pickle.dumps(error))) == str(copy.copy(error)) == "Agent 'billing' not found"

    def test_it_is_exported_beside_the_registry(self):
        import agentkernel.core as core

        assert core.AgentNotFoundError is AgentNotFoundError


class TestAvailability:
    """`AgentService.ensure_agent_available` asks the registry, so a process answers for agents it does not host."""

    def test_a_named_agent_the_registry_knows_is_available_without_being_hosted(self, descriptor_only_registry):
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            AgentService.ensure_agent_available("billing")

    def test_a_named_agent_the_registry_does_not_know_is_not_found(self, descriptor_only_registry):
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            with pytest.raises(AgentNotFoundError, match="^Agent 'support' not found$"):
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

    def test_an_unnamed_request_asks_whether_any_agent_is_known_without_listing_them(self, descriptor_only_registry):
        class _Unlistable(descriptor_only_registry):
            """Fails on a listing: every request with no agent named would otherwise read the whole store."""

            def descriptors(self):
                raise AssertionError("every descriptor was read to learn whether one exists")

            def is_empty(self):
                return False

        with Runtime(InMemorySessionStore(), registry=_Unlistable([])):
            AgentService.ensure_agent_available(None)

    def test_a_process_that_runs_the_agent_itself_needs_it_hosted(self, descriptor_only_registry):
        # Direct execution: an agent another process hosts cannot be selected here, so the request must fail before
        # anything is written for it (a thread message, a session).
        with Runtime(InMemorySessionStore(), registry=descriptor_only_registry([_descriptor("billing")])):
            # Named, it answers as an agent that does not exist would: this process cannot serve it either way.
            with pytest.raises(AgentNotFoundError, match="^Agent 'billing' not found$"):
                AgentService.ensure_agent_available("billing", hosted=True)
            # Unnamed, there is no name to hide and no agent to default to.
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available(None, hosted=True)

    def test_an_unknown_named_agent_and_no_agent_at_all_are_different_errors(self):
        # A name the registry does not know is the 404 a hidden agent gets; a request naming none is a 400.
        with Runtime(InMemorySessionStore()):
            with pytest.raises(AgentNotFoundError):
                AgentService.ensure_agent_available("support")
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available(None)

    def test_a_hosted_agent_satisfies_the_hosted_check_without_reading_the_store(self):
        class _HostedOnly(InMemoryAgentRegistry):
            def descriptor(self, id):
                raise AssertionError("the registry's store was read for an agent this process hosts")

            def is_empty(self):
                raise AssertionError("the registry's store was read while this process hosts an agent")

        runtime = Runtime(InMemorySessionStore(), registry=_HostedOnly())
        runtime.register(StubAgent("billing"))

        with runtime:
            AgentService.ensure_agent_available("billing", hosted=True)
            AgentService.ensure_agent_available(None, hosted=True)


def _hosted(runtime: Runtime, name: str, surfaces: list[str] | None = None) -> StubAgent:
    """Registers an agent served on the given surfaces: every surface when None, none when empty."""
    agent = StubAgent(name)
    agent._set_descriptor(agent.descriptor.model_copy(update={"surfaces": surfaces}))
    runtime.register(agent)
    return agent


class TestAvailabilityOnASurface:
    """A request carries the surface it entered by, and the availability check answers for that surface (design
    refinement 13): an agent kept off it is, to that request, an agent that does not exist."""

    @pytest.mark.parametrize("hosted", [False, True], ids=["registry-wide", "hosted"])
    def test_a_named_agent_kept_off_the_surface_is_not_found(self, hosted):
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "internal", ["a2a", "mcp"])

        with runtime:
            # The unknown agent's error and text: the answer does not say the name exists on another surface.
            with pytest.raises(AgentNotFoundError, match="^Agent 'internal' not found$"):
                AgentService.ensure_agent_available("internal", hosted=hosted, surface="rest")

    @pytest.mark.parametrize("hosted", [False, True], ids=["registry-wide", "hosted"])
    def test_it_is_available_to_a_request_from_a_surface_it_is_on(self, hosted):
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "internal", ["a2a", "mcp"])

        with runtime:
            AgentService.ensure_agent_available("internal", hosted=hosted, surface="a2a")
            AgentService.ensure_agent_available("internal", hosted=hosted, surface="mcp")

    def test_an_agent_with_no_surfaces_list_is_on_every_surface(self):
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "public")

        with runtime:
            for surface in ("rest", "a2a", "mcp", "agui"):
                AgentService.ensure_agent_available("public", hosted=True, surface=surface)

    def test_a_request_with_no_surface_is_not_governed_by_surfaces(self):
        # Messaging, the CLI and a scheduled occurrence enter by none of the four surfaces.
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "nowhere", [])

        with runtime:
            AgentService.ensure_agent_available("nowhere")
            AgentService.ensure_agent_available("nowhere", hosted=True)
            AgentService.ensure_agent_available(None, hosted=True)

    def test_an_agent_another_process_hosts_is_checked_against_the_surfaces_the_registry_holds(self, descriptor_only_registry):
        registry = descriptor_only_registry([_descriptor("internal", surfaces=["a2a"]), _descriptor("public")])

        with Runtime(InMemorySessionStore(), registry=registry):
            with pytest.raises(AgentNotFoundError, match="^Agent 'internal' not found$"):
                AgentService.ensure_agent_available("internal", surface="rest")
            AgentService.ensure_agent_available("internal", surface="a2a")
            AgentService.ensure_agent_available("public", surface="rest")

    def test_a_hosted_agent_is_checked_against_the_surface_without_reading_the_store(self):
        class _HostedOnly(InMemoryAgentRegistry):
            def descriptor(self, id):
                raise AssertionError("the registry's store was read for an agent this process hosts")

            def descriptors(self):
                raise AssertionError("the registry's store was read while this process hosts an agent")

            def is_empty(self):
                raise AssertionError("the registry's store was read while this process hosts an agent")

        runtime = Runtime(InMemorySessionStore(), registry=_HostedOnly())
        _hosted(runtime, "internal", ["a2a"])
        _hosted(runtime, "public")

        with runtime:
            AgentService.ensure_agent_available("public", surface="rest")
            AgentService.ensure_agent_available(None, surface="rest")
            with pytest.raises(AgentNotFoundError):
                AgentService.ensure_agent_available("internal", surface="rest")

    def test_an_unnamed_request_needs_a_hosted_agent_on_the_surface_where_the_agent_runs(self):
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "internal", ["a2a"])

        with runtime:
            # No name to hide: there is simply no agent to default to on this surface.
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available(None, hosted=True, surface="rest")
            AgentService.ensure_agent_available(None, hosted=True, surface="a2a")

            _hosted(runtime, "public")
            AgentService.ensure_agent_available(None, hosted=True, surface="rest")

    def test_an_unnamed_request_at_an_edge_still_asks_only_whether_any_agent_is_known(self, descriptor_only_registry):
        # The default is the running process's to pick, and it applies the surface there. An edge that read every
        # descriptor to second-guess it would list the whole store on each request that names no agent.
        class _Unlistable(descriptor_only_registry):
            def descriptors(self):
                raise AssertionError("every descriptor was read to learn whether one is on the surface")

            def is_empty(self):
                return not self._descriptors

        with Runtime(InMemorySessionStore(), registry=_Unlistable([_descriptor("internal", surfaces=["a2a"])])):
            AgentService.ensure_agent_available(None, surface="rest")

        with Runtime(InMemorySessionStore(), registry=_Unlistable([])):
            with pytest.raises(ValueError, match="No agent available"):
                AgentService.ensure_agent_available(None, surface="rest")


class TestSelectionOnASurface:
    """`AgentService.select` follows the availability check's rule: the default is the first hosted agent on the
    request's surface, and an agent kept off it is not selected."""

    @pytest.fixture
    def runtime(self) -> Runtime:
        runtime = Runtime(InMemorySessionStore())
        _hosted(runtime, "internal", ["a2a"])
        _hosted(runtime, "public")
        return runtime

    @staticmethod
    def _selected(runtime: Runtime, name: str | None = None, **surface) -> tuple[str | None, bool]:
        with runtime:
            service = AgentService()
            service.select("s1", name, **surface)
            return (service.agent.name if service.agent else None), service.session is not None

    def test_an_unnamed_request_defaults_to_the_first_hosted_agent_on_its_surface(self, runtime):
        assert self._selected(runtime, surface="rest") == ("public", True)
        assert self._selected(runtime, surface="a2a") == ("internal", True)

    def test_an_unnamed_request_with_no_surface_defaults_to_the_first_agent_as_before(self, runtime):
        assert self._selected(runtime) == ("internal", True)
        assert self._selected(runtime, surface=None) == ("internal", True)

    def test_a_named_agent_kept_off_the_surface_is_not_selected_and_no_session_is_created(self, runtime):
        assert self._selected(runtime, "internal", surface="rest") == (None, False)

    def test_a_named_agent_is_selected_on_a_surface_it_is_on_and_with_no_surface(self, runtime):
        assert self._selected(runtime, "internal", surface="a2a") == ("internal", True)
        assert self._selected(runtime, "internal") == ("internal", True)
        assert self._selected(runtime, "public", surface="rest") == ("public", True)

    def test_no_agent_on_the_surface_selects_nothing(self, runtime):
        assert self._selected(runtime, surface="agui") == ("public", True)
        runtime.deregister(runtime.agents()["public"])

        assert self._selected(runtime, surface="agui") == (None, False)
