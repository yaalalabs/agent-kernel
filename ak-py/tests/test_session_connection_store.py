"""The WebSocket connection store family (spec #495 §9): the WSConnectionStore contract over
every implementation, and SessionStore.get_connection_store on every built-in backend."""

import pytest

from agentkernel.core.session.base import WSConnectionStore
from agentkernel.core.session.dynamodb import DynamoDBSessionStore, DynamoDBWSConnectionStore
from agentkernel.core.session.in_memory import InMemorySessionStore, InMemoryWSConnectionStore
from agentkernel.core.session.redis_like import RedisLikeWSConnectionStore
from agentkernel.core.session.valkey import ValkeySessionStore
from agentkernel.core.util.driver.dynamodb import DynamoDBDriver
from agentkernel.core.util.factory import AKConfigError


@pytest.fixture(autouse=True)
def _reset_in_memory_connections():
    InMemoryWSConnectionStore.reset()
    yield
    InMemoryWSConnectionStore.reset()


class FakeRedisLikeClient:
    """Minimal stand-in for a redis/valkey client covering the connection store's command surface."""

    def __init__(self):
        self.store: dict = {}
        self.hashes: dict = {}
        self.expirations: dict = {}

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
            self.hashes.pop(key, None)

    def expire(self, name, time):
        self.expirations[name] = time
        return True

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def hdel(self, name, key):
        self.hashes.get(name, {}).pop(key, None)

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))


class FakeDynamoTable:
    """Minimal stand-in for a boto3 Table: pk user_id, sk connection_id, connection_id-index GSI."""

    def __init__(self):
        self.items: dict = {}  # (user_id, connection_id) -> item

    def load(self):
        return None

    def put_item(self, Item):
        self.items[(Item["user_id"], Item["connection_id"])] = dict(Item)

    def delete_item(self, Key):
        self.items.pop((Key["user_id"], Key["connection_id"]), None)

    def query(self, KeyConditionExpression=None, IndexName=None, ExclusiveStartKey=None, **kwargs):
        # boto3 conditions expose their operands; value lives in _values[1].
        value = KeyConditionExpression._values[1]
        if IndexName == DynamoDBWSConnectionStore.CONNECTION_ID_INDEX:
            found = [dict(item) for item in self.items.values() if item["connection_id"] == value]
        else:
            found = [dict(item) for item in self.items.values() if item["user_id"] == value]
        return {"Items": found}


def _redis_like_store(client=None) -> RedisLikeWSConnectionStore:
    from agentkernel.core.util.driver.valkey import ValkeyDriver

    driver = ValkeyDriver(url="valkey://localhost:6379", prefix="ak:ws_connections:", ttl=3600, decode_responses=True)
    driver._client = client or FakeRedisLikeClient()
    return RedisLikeWSConnectionStore(driver)


def _dynamodb_store(table=None) -> DynamoDBWSConnectionStore:
    driver = DynamoDBDriver(table_name="ak-ws-connections", partition_key="user_id", sort_key="connection_id", ttl=3600)
    driver._table = table or FakeDynamoTable()
    return DynamoDBWSConnectionStore(driver)


class _StoreContract:
    """Assertions every WSConnectionStore implementation must satisfy."""

    def make_store(self) -> WSConnectionStore:
        raise NotImplementedError

    def test_round_trip_with_endpoints(self):
        store = self.make_store()
        store.add_connection("u1", "c1", endpoint="http://gw1:8000")
        store.add_connection("u1", "c2", endpoint="http://gw2:8000")
        store.add_connection("u2", "c3", endpoint="http://gw1:8000")

        assert sorted(store.get_connections("u1")) == ["c1", "c2"]
        assert store.get_endpoints("u1") == {"c1": "http://gw1:8000", "c2": "http://gw2:8000"}
        assert store.get_endpoint("c2") == "http://gw2:8000"
        assert store.get_user_id("c3") == "u2"
        assert store.get_user_id("nope") is None
        assert store.get_endpoint("nope") is None
        assert store.get_endpoints("nobody") == {}

    def test_delete_connection_removes_both_directions(self):
        store = self.make_store()
        store.add_connection("u1", "c1", endpoint="local")
        store.delete_connection("u1", "c1")
        assert store.get_endpoints("u1") == {}
        assert store.get_user_id("c1") is None

    def test_delete_by_connection_id_resolves_the_user(self):
        store = self.make_store()
        store.add_connection("u1", "c1", endpoint="local")
        store.delete_by_connection_id("c1")
        assert store.get_connections("u1") == []

    def test_reconnect_overwrites_the_endpoint(self):
        store = self.make_store()
        store.add_connection("u1", "c1", endpoint="http://gw1:8000")
        store.add_connection("u1", "c1", endpoint="http://gw2:8000")
        assert store.get_endpoints("u1") == {"c1": "http://gw2:8000"}


class TestInMemoryWSConnectionStore(_StoreContract):
    def make_store(self) -> InMemoryWSConnectionStore:
        return InMemoryWSConnectionStore()

    def test_not_shared(self):
        assert self.make_store().shared is False

    def test_state_is_process_wide(self):
        """Every component asking for the store must see the same connections, however many
        SessionStore instances were built along the way (single-process co-hosting)."""
        first = InMemorySessionStore().get_connection_store()
        second = InMemorySessionStore().get_connection_store()
        first.add_connection("u1", "c1", endpoint="local")
        assert second.get_endpoints("u1") == {"c1": "local"}


class TestRedisLikeWSConnectionStore(_StoreContract):
    def make_store(self) -> RedisLikeWSConnectionStore:
        return _redis_like_store()

    def test_shared(self):
        assert self.make_store().shared is True

    def test_layout_and_ttl_refresh(self):
        store = self.make_store()
        store.add_connection("u1", "c1", endpoint="local")
        client = store._driver._client
        assert client.hashes["ak:ws_connections:user:u1"] == {"c1": "local"}
        assert "ak:ws_connections:conn:c1" in client.store
        assert client.expirations.get("ak:ws_connections:user:u1") == 3600, "HSET has no ex: the TTL is refreshed explicitly"

    def test_unreadable_record_is_dropped(self):
        client = FakeRedisLikeClient()
        store = _redis_like_store(client)
        client.store["ak:ws_connections:conn:c1"] = "not json"
        assert store.get_user_id("c1") is None
        assert "ak:ws_connections:conn:c1" not in client.store, "the poisoned record was cleaned up"


class TestDynamoDBWSConnectionStore(_StoreContract):
    def make_store(self) -> DynamoDBWSConnectionStore:
        return _dynamodb_store()

    def test_shared(self):
        assert self.make_store().shared is True

    def test_items_carry_the_expiry_time(self):
        """The driver stamps expiry_time on every put: DynamoDB TTL reaps mappings left behind
        by gateway pods that died uncleanly."""
        table = FakeDynamoTable()
        store = _dynamodb_store(table)
        store.add_connection("u1", "c1", endpoint="http://gw1:8000")
        item = table.items[("u1", "c1")]
        assert item["endpoint"] == "http://gw1:8000"
        assert item["expiry_time"] > 0

    def test_reverse_lookup_goes_through_the_gsi(self):
        table = FakeDynamoTable()
        queried = []
        original = table.query

        def spying_query(**kwargs):
            queried.append(kwargs.get("IndexName"))
            return original(**kwargs)

        table.query = spying_query
        store = _dynamodb_store(table)
        store.add_connection("u1", "c1", endpoint="local")
        assert store.get_user_id("c1") == "u1"
        assert DynamoDBWSConnectionStore.CONNECTION_ID_INDEX in queried


class TestSessionStoreBinding:
    @staticmethod
    def _connection_cfg(table_name=None, ttl=86400.0):
        class _ConnectionStore:
            pass

        _ConnectionStore.table_name = table_name
        _ConnectionStore.ttl = ttl
        return _ConnectionStore

    def test_valkey_store_builds_the_driver_backed_store_on_the_session_url(self, monkeypatch):
        class _Valkey:
            url = "valkey://sessions:6379"
            prefix = "ak:session:"
            ttl = 3600

        class _Cfg:
            class session:
                valkey = _Valkey

        _Cfg.session.connection_store = self._connection_cfg(ttl=7200.0)
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        store = ValkeySessionStore.get_connection_store(ValkeySessionStore.__new__(ValkeySessionStore))
        assert isinstance(store, RedisLikeWSConnectionStore)
        assert store._driver._url == "valkey://sessions:6379"
        assert store._driver.key("x") == "ak:ws_connections:x"
        assert store._driver.ttl == 7200, "the mapping TTL comes from session.connection_store.ttl"

    def test_dynamodb_store_builds_on_the_configured_table(self, monkeypatch):
        class _Cfg:
            class session:
                pass

        _Cfg.session.connection_store = self._connection_cfg(table_name="my-ws-connections", ttl=7200.0)
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        store = DynamoDBSessionStore.get_connection_store(DynamoDBSessionStore.__new__(DynamoDBSessionStore))
        assert isinstance(store, DynamoDBWSConnectionStore)
        assert store._driver._table_name == "my-ws-connections"
        assert store._driver._partition_key == "user_id"
        assert store._driver._sort_key == "connection_id"
        assert store._driver._ttl == 7200

    def test_dynamodb_without_a_table_name_raises_actionably(self, monkeypatch):
        class _Cfg:
            class session:
                pass

        _Cfg.session.connection_store = self._connection_cfg(table_name=None)
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        with pytest.raises(AKConfigError, match="session.connection_store.table_name"):
            DynamoDBSessionStore.get_connection_store(DynamoDBSessionStore.__new__(DynamoDBSessionStore))

    def test_store_less_backends_raise_actionably(self):
        from agentkernel.core.session.cosmosdb import CosmosDBSessionStore

        with pytest.raises(AKConfigError, match="cosmosdb.*dynamodb"):
            CosmosDBSessionStore.get_connection_store(CosmosDBSessionStore.__new__(CosmosDBSessionStore))

    def test_byo_store_default_raises_with_guidance(self):
        from agentkernel.core.session.base import SessionStore

        class LegacyByoStore(SessionStore):
            def new(self, session_id):
                pass

            def load(self, session_id, strict=False):
                pass

            def store(self, session):
                pass

            def clear(self):
                pass

        with pytest.raises(AKConfigError, match="LegacyByoStore.*get_connection_store"):
            LegacyByoStore().get_connection_store()
