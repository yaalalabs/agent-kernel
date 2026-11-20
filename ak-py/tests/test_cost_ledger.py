"""Spend ledger (spec §12): the SpendLedgerContract on the in-memory ledger, and SpendLedgerFactory."""

import logging

import pytest

import agentkernel.cost as cost
from agentkernel.core.config import _CostLedgerConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.cost import BudgetPeriod, InMemorySpendLedger, SpendLedger, SpendLedgerFactory
from agentkernel.cost.testing import SpendLedgerContract


class TestInMemorySpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return InMemorySpendLedger(list(BudgetPeriod), clock=clock)


class TestSpendLedger:
    def test_a_ledger_needs_a_period(self):
        with pytest.raises(ValueError, match="at least one budget"):
            InMemorySpendLedger([])


class TestSpendLedgerFactory:
    def test_no_ledger_block_is_in_memory_with_a_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="ak.cost.ledger.factory")

        ledger = SpendLedgerFactory.create(None, [BudgetPeriod.MONTHLY])

        assert isinstance(ledger, InMemorySpendLedger)
        assert "per process and lost on restart" in caplog.text

    @pytest.mark.parametrize("type_", ["in_memory", "IN_MEMORY"])
    def test_in_memory(self, type_):
        assert isinstance(SpendLedgerFactory.create(_CostLedgerConfig(type=type_), [BudgetPeriod.DAILY]), InMemorySpendLedger)

    def test_a_dotted_path_gets_the_periods(self):
        ledger = SpendLedgerFactory.create(_CostLedgerConfig(type="agentkernel.cost.ledger.in_memory.InMemorySpendLedger"), [BudgetPeriod.WEEKLY])

        assert isinstance(ledger, InMemorySpendLedger) and ledger._periods == [BudgetPeriod.WEEKLY]

    @pytest.mark.parametrize(
        ("type_", "message"), [("sqlite", "unknown cost.budgets.ledger.type"), ("datetime.datetime", "not a SpendLedger subclass")]
    )
    def test_refused_types(self, type_, message):
        with pytest.raises(AKConfigError, match=message):
            SpendLedgerFactory.create(_CostLedgerConfig(type=type_), [BudgetPeriod.DAILY])

    def test_exported(self):
        assert {"InMemorySpendLedger", "LedgerDocument", "SpendLedger", "SpendLedgerFactory"} <= set(cost.__all__)


# Shared-storage backends over fakes of their native handles. Each fake honours the condition its backend relies on,
# and is locked so concurrent asyncio.to_thread calls see the atomic behaviour the real store gives.

import itertools
import math
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError, ServiceRequestError
from botocore.exceptions import ClientError
from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound, ServiceUnavailable

from agentkernel.core.config import (
    _CostLedgerCosmosDBConfig,
    _CostLedgerDynamoDBConfig,
    _CostLedgerFirestoreConfig,
    _CostLedgerRedisConfig,
    _CostLedgerValkeyConfig,
)
from agentkernel.core.util.driver import redis_like as redis_like_driver
from agentkernel.cost import LedgerError, SpendCursor
from agentkernel.cost.ledger.cosmosdb import CosmosDBSpendLedger
from agentkernel.cost.ledger.dynamodb import DynamoDBSpendLedger
from agentkernel.cost.ledger.firestore import FirestoreSpendLedger
from agentkernel.cost.ledger.redis import RedisSpendLedger
from agentkernel.cost.ledger.valkey import ValkeySpendLedger
from agentkernel.cost.testing import _row

_NOW = datetime(2026, 1, 28, 12, 0, tzinfo=timezone.utc)
_EXPIRES = datetime(2026, 3, 1, tzinfo=timezone.utc)  # the latest end of the period after now, over all three


class _FakeRedis:
    """GET and the compare-and-set script, with EX expiry on the shared clock."""

    def __init__(self, clock) -> None:
        self._clock = clock
        self.values: dict[str, tuple[bytes, datetime | None]] = {}
        self.ttls: list[int] = []
        self.failure: Exception | None = None
        self.lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def _live(self, key: str) -> bytes | None:
        entry = self.values.get(key)
        if entry is not None and entry[1] is not None and self._clock() >= entry[1]:
            del self.values[key]
            return None
        return entry[0] if entry else None

    def get(self, key: str) -> bytes | None:
        if self.failure:
            raise self.failure
        with self.lock:
            return self._live(key)

    def eval(self, script, numkeys, key, expects_value, expected, value, ttl):
        assert script == redis_like_driver._COMPARE_AND_SET and numkeys == 1
        with self.lock:
            current = self._live(key)
            if (current != expected) if expects_value == "1" else (current is not None):
                return 0
            self.ttls.append(ttl)
            self.values[key] = (value, self._clock() + timedelta(seconds=ttl) if ttl > 0 else None)
            return 1


class _FakeDynamoTable:
    """get_item / put_item with the two condition expressions the ledger sends; expired items stay (lazy TTL)."""

    _CONDITIONS = ("version = :v", "attribute_not_exists(user_id) OR expiry_time <= :now")

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.reads: list[bool] = []
        self.failure: Exception | None = None
        self.lock = threading.Lock()

    def get_item(self, Key, ConsistentRead):  # noqa: N803 (boto3 keyword names)
        if self.failure:
            raise self.failure
        self.reads.append(ConsistentRead)
        item = self.items.get(Key["user_id"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression, ExpressionAttributeValues):  # noqa: N803
        assert ConditionExpression in self._CONDITIONS
        with self.lock:
            current = self.items.get(Item["user_id"])
            if ConditionExpression == "version = :v":
                ok = current is not None and current["version"] == ExpressionAttributeValues[":v"]
            else:
                ok = current is None or current["expiry_time"] <= ExpressionAttributeValues[":now"]
            if not ok:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "failed"}}, "PutItem")
            # DynamoDB returns numbers as Decimal.
            self.items[Item["user_id"]] = {k: Decimal(v) if isinstance(v, int) else v for k, v in Item.items()}


class _Entity(dict):
    metadata: dict


class _FakeCosmosTable:
    """get / create / update_entity with etags, raising the real azure exceptions."""

    def __init__(self) -> None:
        self.entities: dict[str, tuple[dict, str]] = {}
        self.failure: Exception | None = None
        self.lock = threading.Lock()

    def get_entity(self, partition_key, row_key):
        if self.failure:
            raise self.failure
        assert row_key == "ledger"
        with self.lock:
            if partition_key not in self.entities:
                raise ResourceNotFoundError("not found")
            data, etag = self.entities[partition_key]
        entity = _Entity(data)
        entity.metadata = {"etag": etag}
        return entity

    def create_entity(self, entity):
        with self.lock:
            if entity["PartitionKey"] in self.entities:
                raise ResourceExistsError("exists")
            self.entities[entity["PartitionKey"]] = (dict(entity), uuid.uuid4().hex)

    def update_entity(self, entity, mode, etag, match_condition):
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode

        assert mode is UpdateMode.REPLACE and match_condition is MatchConditions.IfNotModified
        with self.lock:
            if self.entities[entity["PartitionKey"]][1] != etag:
                raise ResourceModifiedError("modified")
            self.entities[entity["PartitionKey"]] = (dict(entity), uuid.uuid4().hex)

    def touch(self, user_id: str) -> None:
        """Another writer changes the entity."""
        data, _ = self.entities[user_id]
        self.entities[user_id] = (data, uuid.uuid4().hex)


class _Snapshot:
    def __init__(self, data: dict | None, update_time: datetime | None) -> None:
        self.exists = data is not None
        self._data = data or {}
        self.update_time = update_time

    def get(self, field: str):
        return self._data[field]


class _FakeFirestore:
    """A client whose documents carry update times; create / update honour the precondition, with real exceptions."""

    def __init__(self) -> None:
        self.docs: dict[str, tuple[dict, datetime]] = {}
        self.failure: Exception | None = None
        self.lock = threading.Lock()
        self._ticks = itertools.count(1)

    def collection(self, name: str) -> "_FakeFirestore":
        return self

    def document(self, user_id: str) -> "_FakeFirestoreRef":
        return _FakeFirestoreRef(self, user_id)

    def next_time(self) -> datetime:
        return datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=next(self._ticks))

    def touch(self, user_id: str) -> None:
        data, _ = self.docs[user_id]
        self.docs[user_id] = (data, self.next_time())


class _FakeFirestoreRef:
    def __init__(self, store: _FakeFirestore, user_id: str) -> None:
        self._store, self._id = store, user_id

    def get(self) -> _Snapshot:
        if self._store.failure:
            raise self._store.failure
        with self._store.lock:
            data, update_time = self._store.docs.get(self._id, (None, None))
        return _Snapshot(data, update_time)

    def create(self, data: dict) -> None:
        with self._store.lock:
            if self._id in self._store.docs:
                raise AlreadyExists("exists")
            self._store.docs[self._id] = (dict(data), self._store.next_time())

    def update(self, data: dict, option) -> None:
        with self._store.lock:
            if self._id not in self._store.docs:
                raise NotFound("missing")
            if self._store.docs[self._id][1] != option._last_update_time:
                raise FailedPrecondition("changed")
            self._store.docs[self._id] = (dict(data), self._store.next_time())


def _redis_ledger(clock, ledger_class=RedisSpendLedger, config_class=_CostLedgerRedisConfig):
    ledger = ledger_class(config_class(), list(BudgetPeriod), clock=clock)
    ledger.fake = _FakeRedis(clock)  # type: ignore[attr-defined]
    ledger._driver._client = ledger.fake
    return ledger


def _dynamodb_ledger(clock):
    ledger = DynamoDBSpendLedger(_CostLedgerDynamoDBConfig(), list(BudgetPeriod), clock=clock)
    ledger.fake = ledger._driver._table = _FakeDynamoTable()  # type: ignore[attr-defined]
    return ledger


def _cosmosdb_ledger(clock):
    config = _CostLedgerCosmosDBConfig(connection_string="UseDevelopmentStorage=true")
    ledger = CosmosDBSpendLedger(config, list(BudgetPeriod), clock=clock)
    ledger.fake = ledger._driver._table_client = _FakeCosmosTable()  # type: ignore[attr-defined]
    return ledger


def _firestore_ledger(clock):
    ledger = FirestoreSpendLedger(_CostLedgerFirestoreConfig(), list(BudgetPeriod), clock=clock)
    ledger.fake = ledger._driver._client = _FakeFirestore()  # type: ignore[attr-defined]
    return ledger


class TestRedisSpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return _redis_ledger(clock)


class TestValkeySpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return _redis_ledger(clock, ValkeySpendLedger, _CostLedgerValkeyConfig)


class TestDynamoDBSpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return _dynamodb_ledger(clock)


class TestCosmosDBSpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return _cosmosdb_ledger(clock)


class TestFirestoreSpendLedgerContract(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock) -> SpendLedger:
        return _firestore_ledger(clock)


def _first_add(ledger):
    return ledger.add("u1", [_row("r1", _NOW)], None, SpendCursor(timestamp=_NOW, ids_at_timestamp=frozenset({"r1"})))


class TestBackendDetails:
    @pytest.fixture
    def clock(self):
        from agentkernel.cost.testing import LedgerClock

        return LedgerClock(_NOW)

    @pytest.mark.asyncio
    async def test_redis_expires_each_write_by_ex(self, clock):
        ledger = _redis_ledger(clock)

        await _first_add(ledger)

        assert ledger.fake.ttls == [math.ceil((_EXPIRES - _NOW).total_seconds())]
        assert list(ledger.fake.values) == ["ak:cost:ledger:u1"]

    @pytest.mark.asyncio
    async def test_redis_refuses_when_the_value_changes_between_read_and_write(self, clock):
        ledger = _redis_ledger(clock)
        await _first_add(ledger)
        doc = await ledger.load("u1")
        original_get = ledger.fake.get

        def racing_get(key):
            raw = original_get(key)
            ledger.fake.values[key] = (raw + b" ", None)  # another writer lands after the version check
            return raw

        ledger.fake.get = racing_get
        assert await ledger.compare_and_set("u1", doc.version, doc.model_copy(update={"version": doc.version + 1}), _EXPIRES) is False

    @pytest.mark.asyncio
    async def test_dynamodb_item_shape_and_consistent_reads(self, clock):
        ledger = _dynamodb_ledger(clock)

        await _first_add(ledger)

        item = ledger.fake.items["u1"]
        assert set(item) == {"user_id", "doc", "version", "expiry_time"}
        assert item["expiry_time"] == int(_EXPIRES.timestamp()) and item["version"] == 1
        assert ledger.fake.reads and all(ledger.fake.reads)

    @pytest.mark.asyncio
    async def test_cosmosdb_refuses_when_the_etag_changes_between_read_and_write(self, clock):
        ledger = _cosmosdb_ledger(clock)
        await _first_add(ledger)
        doc = await ledger.load("u1")
        original_get = ledger.fake.get_entity

        def racing_get(partition_key, row_key):
            entity = original_get(partition_key=partition_key, row_key=row_key)
            ledger.fake.touch(partition_key)
            return entity

        ledger.fake.get_entity = racing_get
        assert await ledger.compare_and_set("u1", doc.version, doc.model_copy(update={"version": doc.version + 1}), _EXPIRES) is False

    @pytest.mark.asyncio
    async def test_firestore_refuses_when_the_update_time_changes_between_read_and_write(self, clock):
        ledger = _firestore_ledger(clock)
        await _first_add(ledger)
        doc = await ledger.load("u1")
        original_document = ledger.fake.document

        def racing_document(user_id):
            ref = original_document(user_id)
            original_get = ref.get

            def get():
                snapshot = original_get()
                ledger.fake.touch(user_id)
                return snapshot

            ref.get = get
            return ref

        ledger.fake.document = racing_document
        assert await ledger.compare_and_set("u1", doc.version, doc.model_copy(update={"version": doc.version + 1}), _EXPIRES) is False
        assert ledger.fake.docs["u1"][0]["expiry_time"] == _EXPIRES  # a datetime, for a Firestore TTL policy

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("build", "error"),
        [
            (_redis_ledger, redis.ConnectionError("down")),
            (_dynamodb_ledger, ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "GetItem")),
            (_cosmosdb_ledger, ServiceRequestError("down")),
            (_firestore_ledger, ServiceUnavailable("down")),
        ],
    )
    async def test_a_backend_failure_is_a_ledger_error(self, clock, build, error):
        ledger = build(clock)
        ledger.fake.failure = error

        with pytest.raises(LedgerError):
            await ledger.load("u1")


class TestBackendFactory:
    @pytest.mark.parametrize(
        ("type_", "block", "expected"),
        [
            ("redis", {"redis": {}}, RedisSpendLedger),
            ("valkey", {"valkey": {}}, ValkeySpendLedger),
            ("dynamodb", {"dynamodb": {}}, DynamoDBSpendLedger),
            ("cosmosdb", {"cosmosdb": {"connection_string": "UseDevelopmentStorage=true"}}, CosmosDBSpendLedger),
            ("firestore", {"firestore": {}}, FirestoreSpendLedger),
        ],
    )
    def test_each_backend_from_its_block(self, type_, block, expected):
        ledger = SpendLedgerFactory.create(_CostLedgerConfig(type=type_, **block), [BudgetPeriod.MONTHLY])

        assert type(ledger) is expected

    def test_a_backend_needs_its_block(self):
        with pytest.raises(AKConfigError, match="cost.budgets.ledger.dynamodb block"):
            SpendLedgerFactory.create(_CostLedgerConfig(type="dynamodb"), [BudgetPeriod.MONTHLY])

    def test_a_missing_extra_names_it(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.cost.ledger.firestore", None)

        with pytest.raises(ImportError, match="'gcp' extra"):
            SpendLedgerFactory.create(_CostLedgerConfig(type="firestore", firestore={}), [BudgetPeriod.MONTHLY])


@pytest.mark.skipif(not os.environ.get("AK_TEST_REDIS_URL"), reason="set AK_TEST_REDIS_URL to run against a real Redis")
class TestRedisSpendLedgerOnRedis(SpendLedgerContract):
    @pytest.fixture
    def ledger(self, clock):
        prefix = f"ak:test:ledger:{uuid.uuid4().hex}:"
        ledger = RedisSpendLedger(_CostLedgerRedisConfig(url=os.environ["AK_TEST_REDIS_URL"], prefix=prefix), list(BudgetPeriod), clock=clock)
        yield ledger
        ledger._driver.clear_prefix()

    def test_contract_an_expired_document_is_gone(self):
        pytest.skip("EX runs in real seconds; the fake clock cannot reach it")

    def test_contract_an_expired_document_is_replaced_from_scratch(self):
        pytest.skip("EX runs in real seconds; the fake clock cannot reach it")
