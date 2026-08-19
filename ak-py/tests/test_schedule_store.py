"""Scheduled-task stores: the contract every backend satisfies, once per backend.

``TestInMemoryScheduleStore`` pins the contract; the redis-like and DynamoDB classes re-run it
against fakes standing in for their client libraries, so a backend that diverges from the contract
fails here rather than in a deployment. Valkey shares the redis body verbatim, so it is covered by
its config wiring plus a representative slice (the thread suite's reasoning).
"""

import fnmatch
import sys
from typing import Optional
from unittest.mock import MagicMock

import pytest
from boto3.dynamodb.conditions import Attr

from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.util.driver.valkey import ValkeyDriver
from agentkernel.core.util.factory import AKConfigError
from agentkernel.schedule.model import ScheduledTask, ScheduleStatus
from agentkernel.schedule.store.base import _BUILTIN_SCHEDULE_STORES, ScheduleStore, ScheduleStoreBuilder
from agentkernel.schedule.store.dynamodb import DynamoDBScheduleStore
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore
from agentkernel.schedule.store.redis import RedisScheduleStore
from agentkernel.schedule.store.redis_like import _RedisLikeScheduleStore
from agentkernel.schedule.store.valkey import ValkeyScheduleStore

PREFIX = "ak:schedule:"
TABLE_NAME = "ak-agent-schedules"


def _task(task_id: str, user_id: str = "u1", updated_at: str = "2030-01-01T00:00:00+00:00", **overrides) -> ScheduledTask:
    fields = {
        "task_id": task_id,
        "user_id": user_id,
        "prompt": "send the weekly report",
        "session_id": f"s-{task_id}",
        "spec": ScheduleSpec(cron="0 9 * * 1"),
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": updated_at,
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


class TestInMemoryScheduleStore:
    @pytest.fixture(autouse=True)
    def store(self):
        store = InMemoryScheduleStore()
        store.clear()
        yield store
        store.clear()

    def test_create_then_get_round_trips_the_record(self, store):
        store.create(_task("t1", agent="planner"))

        loaded = store.get("t1")
        assert loaded.user_id == "u1"
        assert loaded.agent == "planner"
        assert loaded.spec.cron == "0 9 * * 1"

    def test_get_unknown_task_returns_none(self, store):
        assert store.get("missing") is None

    def test_stored_records_are_isolated_from_the_caller(self, store):
        task = _task("t1")
        store.create(task)

        task.prompt = "mutated after storing"
        assert store.get("t1").prompt == "send the weekly report"

    def test_update_overwrites_the_whole_record(self, store):
        store.create(_task("t1"))

        store.update(_task("t1", prompt="new prompt", provider_ref="ref-1", status=ScheduleStatus.PAUSED))

        loaded = store.get("t1")
        assert loaded.prompt == "new prompt"
        assert loaded.provider_ref == "ref-1"
        assert loaded.status is ScheduleStatus.PAUSED

    def test_delete_removes_the_record_and_tolerates_a_missing_one(self, store):
        store.create(_task("t1"))

        store.delete("t1")
        store.delete("t1")

        assert store.get("t1") is None

    def test_list_returns_most_recently_updated_first(self, store):
        store.create(_task("old", updated_at="2030-01-01T00:00:00+00:00"))
        store.create(_task("new", updated_at="2030-02-01T00:00:00+00:00"))

        tasks, next_offset = store.list()

        assert [task.task_id for task in tasks] == ["new", "old"]
        assert next_offset is None

    def test_list_filters_by_owner(self, store):
        store.create(_task("mine", user_id="u1"))
        store.create(_task("theirs", user_id="u2"))

        tasks, _ = store.list(user_id="u1")

        assert [task.task_id for task in tasks] == ["mine"]

    def test_list_pages_with_offset_and_limit(self, store):
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-01-0{index + 1}T00:00:00+00:00"))

        first_page, next_offset = store.list(limit=2)
        second_page, final_offset = store.list(limit=2, offset=next_offset)

        assert [task.task_id for task in first_page] == ["t2", "t1"]
        assert next_offset == 2
        assert [task.task_id for task in second_page] == ["t0"]
        assert final_offset is None

    def test_record_trigger_advances_the_occurrence_fields(self, store):
        store.create(_task("t1"))

        store.record_trigger("t1", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=False)

        loaded = store.get("t1")
        assert loaded.trigger_count == 1
        assert loaded.last_triggered_at == "2030-03-01T09:00:00+00:00"
        assert loaded.last_request_id == "r1"
        # Recording is activity, so it restamps the record the listing orders by.
        assert loaded.updated_at != "2030-01-01T00:00:00+00:00"
        assert loaded.status is ScheduleStatus.ACTIVE

    def test_record_trigger_completes_a_final_occurrence(self, store):
        store.create(_task("t1", spec=ScheduleSpec(at="2030-03-01T09:00:00")))

        store.record_trigger("t1", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=True)

        assert store.get("t1").status is ScheduleStatus.COMPLETED

    def test_record_trigger_for_an_unknown_task_is_ignored(self, store):
        # A trigger can outlive the record it came from; it must not raise into the run.
        store.record_trigger("missing", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=False)

    def test_clear_removes_every_record(self, store):
        store.create(_task("t1"))

        store.clear()

        assert store.list() == ([], None)


class _FakeRedisLikeClient:
    """Minimal in-memory stand-in for the redis/valkey client the shared driver drives.

    Only the commands the store issues are implemented, so the real store body runs end to end
    while the assertions stay about the store rather than about a mock's call log.
    """

    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.sets: dict[str, set[str]] = {}
        self.expired: list[tuple[str, int]] = []

    def ping(self) -> bool:
        return True

    def set(self, key: str, value, ex: Optional[int] = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value.encode() if isinstance(value, str) else value
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
        self.expired.append((name, time))

    def scan_iter(self, match: str, count: Optional[int] = None):
        return [key for key in list(self.values) + list(self.sets) if fnmatch.fnmatch(key, match)]


class _FakeDynamoDBTable:
    """Stand-in for the boto3 Table, covering the paginated scan the store's listing uses."""

    def __init__(self, items: dict):
        self._items = items
        self.scan_calls: list[dict] = []
        self.page_size: Optional[int] = None

    def scan(self, **kwargs) -> dict:
        self.scan_calls.append(kwargs)
        items = list(self._items.values())
        start = items.index(kwargs["ExclusiveStartKey"]) if "ExclusiveStartKey" in kwargs else 0
        if self.page_size is None:
            return {"Items": items[start:]}
        page = items[start : start + self.page_size]
        response = {"Items": page}
        if start + self.page_size < len(items):
            response["LastEvaluatedKey"] = items[start + self.page_size]
        return response


class _FakeDynamoDBDriver:
    """Stand-in for DynamoDBDriver: the store's writes and reads against one item per task."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.table = _FakeDynamoDBTable(self.items)
        self.cleared = False

    def put(self, item: dict) -> None:
        self.items[item["task_id"]] = item

    def get(self, pk_value: str, sk_value=None) -> Optional[dict]:
        return self.items.get(pk_value)

    def delete(self, pk_value: str, sk_value=None) -> None:
        self.items.pop(pk_value, None)

    def clear_all(self) -> None:
        self.items.clear()
        self.cleared = True


def _configure_store(monkeypatch, **store_fields) -> None:
    """Point AKConfig at a schedule block carrying the given store configuration."""
    config = AKConfig.get().model_copy(update={"schedule": _ScheduleConfig.model_validate({"store": store_fields})})
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))


class TestRedisLikeScheduleStore:
    """The shared redis-protocol body, driven through RedisScheduleStore."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @pytest.fixture
    def make_store(self, monkeypatch):
        def _make(ttl: int = 0) -> RedisScheduleStore:
            _configure_store(monkeypatch, type="redis", redis={"ttl": ttl, "prefix": PREFIX})
            store = RedisScheduleStore()
            # Inject an established client so the driver never connects; its ping health-check passes.
            store._driver._client = _FakeRedisLikeClient()
            return store

        return _make

    @pytest.fixture
    def store(self, make_store):
        return make_store()

    @staticmethod
    def _client(store: RedisScheduleStore) -> _FakeRedisLikeClient:
        return store._driver._client

    def test_create_then_get_round_trips_the_record(self, store):
        store.create(_task("t1", agent="planner"))

        loaded = store.get("t1")
        assert loaded.user_id == "u1"
        assert loaded.agent == "planner"
        assert loaded.spec.cron == "0 9 * * 1"

    def test_records_are_keyed_under_the_configured_prefix(self, store):
        store.create(_task("t1"))

        assert f"{PREFIX}task:t1" in self._client(store).values
        assert self._client(store).sets[f"{PREFIX}index:user:u1"] == {"t1"}
        assert self._client(store).sets[f"{PREFIX}index:all"] == {"t1"}

    def test_get_unknown_task_returns_none(self, store):
        assert store.get("missing") is None

    def test_update_overwrites_the_whole_record(self, store):
        store.create(_task("t1"))

        store.update(_task("t1", prompt="new prompt", provider_ref="ref-1", status=ScheduleStatus.PAUSED))

        loaded = store.get("t1")
        assert loaded.prompt == "new prompt"
        assert loaded.provider_ref == "ref-1"
        assert loaded.status is ScheduleStatus.PAUSED

    def test_delete_removes_the_record_and_its_index_memberships(self, store):
        store.create(_task("t1"))

        store.delete("t1")

        assert store.get("t1") is None
        assert self._client(store).sets[f"{PREFIX}index:user:u1"] == set()
        assert self._client(store).sets[f"{PREFIX}index:all"] == set()
        # A dangling index member would keep every later listing skipping a task that is gone.
        assert store.list() == ([], None)

    def test_delete_tolerates_a_missing_record(self, store):
        store.delete("missing")

    def test_list_returns_most_recently_updated_first(self, store):
        store.create(_task("t1", updated_at="2030-01-01T00:00:00+00:00"))
        store.create(_task("t2", updated_at="2030-03-01T00:00:00+00:00"))

        tasks, next_offset = store.list()

        assert [task.task_id for task in tasks] == ["t2", "t1"]
        assert next_offset is None

    def test_list_filters_by_owner(self, store):
        store.create(_task("t1", user_id="u1"))
        store.create(_task("t2", user_id="u2"))

        tasks, _ = store.list(user_id="u2")

        assert [task.task_id for task in tasks] == ["t2"]

    def test_list_pages_with_offset_and_limit(self, store):
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-0{index + 1}-01T00:00:00+00:00"))

        first_page, next_offset = store.list(limit=2, offset=0)
        second_page, final_offset = store.list(limit=2, offset=next_offset)

        assert [task.task_id for task in first_page] == ["t2", "t1"]
        assert next_offset == 2
        assert [task.task_id for task in second_page] == ["t0"]
        assert final_offset is None

    def test_list_skips_index_members_whose_record_expired(self, store):
        store.create(_task("t1"))
        store.create(_task("t2"))
        self._client(store).values.pop(f"{PREFIX}task:t2")

        tasks, _ = store.list()

        assert [task.task_id for task in tasks] == ["t1"]

    def test_record_trigger_advances_the_occurrence_fields(self, store):
        store.create(_task("t1"))

        store.record_trigger("t1", request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False)

        loaded = store.get("t1")
        assert loaded.last_triggered_at == "2030-02-01T09:00:00+00:00"
        assert loaded.last_request_id == "r-1"
        assert loaded.trigger_count == 1
        assert loaded.status is ScheduleStatus.ACTIVE

    def test_record_trigger_completes_a_final_occurrence(self, store):
        store.create(_task("t1", spec=ScheduleSpec(at="2030-06-01T09:00:00")))

        store.record_trigger("t1", request_id="r-1", occurred_at="2030-06-01T09:00:00+00:00", completed=True)

        assert store.get("t1").status is ScheduleStatus.COMPLETED

    def test_record_trigger_for_an_unknown_task_is_ignored(self, store):
        store.record_trigger("missing", request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False)

    def test_clear_removes_every_record(self, store):
        store.create(_task("t1"))

        store.clear()

        assert store.list() == ([], None)

    def test_no_ttl_is_applied_by_default(self, store):
        store.create(_task("t1"))

        # Schedules must not silently expire, so the default configuration issues no EXPIRE at all.
        assert self._client(store).expired == []

    def test_a_configured_ttl_covers_the_record_and_both_indexes(self, make_store):
        store = make_store(ttl=60)

        store.create(_task("t1"))

        assert {key for key, _ in self._client(store).expired} == {
            f"{PREFIX}task:t1",
            f"{PREFIX}index:user:u1",
            f"{PREFIX}index:all",
        }

    def test_a_write_re_registers_index_membership(self, make_store):
        """Under a TTL an index set can expire while the record lives; a listing must not lose it."""
        store = make_store(ttl=60)
        store.create(_task("t1"))
        self._client(store).sets.pop(f"{PREFIX}index:all")

        store.update(_task("t1", prompt="amended"))

        assert [task.task_id for task in store.list()[0]] == ["t1"]

    def test_every_abstract_method_is_implemented(self):
        assert not (set(ScheduleStore.__abstractmethods__) - set(vars(_RedisLikeScheduleStore)))


class TestValkeyScheduleStore:
    """Valkey-specific wiring plus a slice proving the shared body runs through a Valkey driver."""

    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @pytest.fixture
    def store(self, monkeypatch):
        _configure_store(monkeypatch, type="valkey", valkey={"ttl": 0, "prefix": PREFIX})
        store = ValkeyScheduleStore()
        store._driver._client = _FakeRedisLikeClient()
        return store

    def test_builds_a_valkey_driver_from_the_valkey_block(self, store):
        assert isinstance(store._driver, ValkeyDriver)
        assert store._prefix == PREFIX

    def test_round_trips_a_record_through_the_shared_body(self, store):
        store.create(_task("t1"))

        assert store.get("t1").prompt == "send the weekly report"
        assert [task.task_id for task in store.list(user_id="u1")[0]] == ["t1"]

    def test_missing_config_block_is_rejected(self, monkeypatch):
        _configure_store(monkeypatch, type="valkey")

        with pytest.raises(ValueError, match="AKConfig.schedule.store.valkey must be set"):
            ValkeyScheduleStore()


class TestDynamoDBScheduleStore:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @pytest.fixture
    def store(self, monkeypatch):
        _configure_store(monkeypatch, type="dynamodb", dynamodb={"table_name": TABLE_NAME, "ttl": 0})
        store = DynamoDBScheduleStore()
        store._driver = _FakeDynamoDBDriver()
        return store

    def test_create_then_get_round_trips_the_record(self, store):
        store.create(_task("t1", agent="planner"))

        loaded = store.get("t1")
        assert loaded.agent == "planner"
        assert loaded.spec.cron == "0 9 * * 1"

    def test_an_item_carries_the_attributes_a_listing_needs(self, store):
        store.create(_task("t1", updated_at="2030-03-01T00:00:00+00:00"))

        item = store._driver.items["t1"]
        # Denormalized so a scan can filter and sort without deserializing every document.
        assert item["user_id"] == "u1"
        assert item["updated_at"] == "2030-03-01T00:00:00+00:00"
        assert '"task_id":"t1"' in item["data"]

    def test_get_unknown_task_returns_none(self, store):
        assert store.get("missing") is None

    def test_update_overwrites_the_whole_record(self, store):
        store.create(_task("t1"))

        store.update(_task("t1", prompt="new prompt", status=ScheduleStatus.PAUSED))

        loaded = store.get("t1")
        assert loaded.prompt == "new prompt"
        assert loaded.status is ScheduleStatus.PAUSED

    def test_delete_removes_the_record_and_tolerates_a_missing_one(self, store):
        store.create(_task("t1"))

        store.delete("t1")
        store.delete("t1")

        assert store.get("t1") is None

    def test_list_returns_most_recently_updated_first(self, store):
        store.create(_task("t1", updated_at="2030-01-01T00:00:00+00:00"))
        store.create(_task("t2", updated_at="2030-03-01T00:00:00+00:00"))

        tasks, next_offset = store.list()

        assert [task.task_id for task in tasks] == ["t2", "t1"]
        assert next_offset is None
        assert "FilterExpression" not in store._driver.table.scan_calls[0]

    def test_list_filters_by_owner_in_the_scan(self, store):
        store.create(_task("t1", user_id="u1"))

        store.list(user_id="u2")

        assert store._driver.table.scan_calls[0]["FilterExpression"] == Attr("user_id").eq("u2")

    def test_list_follows_the_scan_pagination(self, store):
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-0{index + 1}-01T00:00:00+00:00"))
        store._driver.table.page_size = 1

        tasks, _ = store.list()

        assert [task.task_id for task in tasks] == ["t2", "t1", "t0"]
        assert len(store._driver.table.scan_calls) == 3

    def test_list_pages_with_offset_and_limit(self, store):
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-0{index + 1}-01T00:00:00+00:00"))

        first_page, next_offset = store.list(limit=2, offset=0)

        assert [task.task_id for task in first_page] == ["t2", "t1"]
        assert next_offset == 2

    def test_only_the_returned_page_is_deserialized(self, store):
        """Ordering and paging run on the denormalized attributes, so a document outside the page
        is never parsed — which is what makes writing those attributes worth the item space."""
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-0{index + 1}-01T00:00:00+00:00"))
        store._driver.items["t0"]["data"] = "not a task document"

        tasks, _ = store.list(limit=2, offset=0)

        assert [task.task_id for task in tasks] == ["t2", "t1"]

    def test_record_trigger_advances_the_occurrence_fields(self, store):
        store.create(_task("t1"))

        store.record_trigger("t1", request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False)

        loaded = store.get("t1")
        assert loaded.last_triggered_at == "2030-02-01T09:00:00+00:00"
        assert loaded.last_request_id == "r-1"
        assert loaded.trigger_count == 1

    def test_record_trigger_completes_a_final_occurrence(self, store):
        store.create(_task("t1", spec=ScheduleSpec(at="2030-06-01T09:00:00")))

        store.record_trigger("t1", request_id="r-1", occurred_at="2030-06-01T09:00:00+00:00", completed=True)

        assert store.get("t1").status is ScheduleStatus.COMPLETED

    def test_record_trigger_for_an_unknown_task_is_ignored(self, store):
        store.record_trigger("missing", request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False)

    def test_clear_removes_every_record(self, store):
        store.create(_task("t1"))

        store.clear()

        assert store.list() == ([], None)
        assert store._driver.cleared

    def test_the_driver_is_built_for_a_single_key_table(self, monkeypatch):
        _configure_store(monkeypatch, type="dynamodb", dynamodb={"table_name": TABLE_NAME, "ttl": 90})
        driver_calls = {}
        monkeypatch.setattr(
            "agentkernel.schedule.store.dynamodb.DynamoDBDriver",
            lambda **kwargs: driver_calls.update(kwargs) or MagicMock(),
        )

        DynamoDBScheduleStore()

        assert driver_calls == {"table_name": TABLE_NAME, "partition_key": "task_id", "ttl": 90}

    def test_missing_table_name_is_rejected(self, monkeypatch):
        _configure_store(monkeypatch, type="dynamodb")

        with pytest.raises(ValueError, match="AKConfig.schedule.store.dynamodb.table_name must be set"):
            DynamoDBScheduleStore()

    def test_every_abstract_method_is_implemented(self):
        assert not (set(ScheduleStore.__abstractmethods__) - set(vars(DynamoDBScheduleStore)))


class _CustomScheduleStore(InMemoryScheduleStore):
    """Bring-your-own store used to pin dotted-path resolution."""


class TestScheduleStoreBuilder:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @staticmethod
    def _configure(monkeypatch, store_type: str, **store_fields) -> None:
        _configure_store(monkeypatch, type=store_type, **store_fields)

    def test_builds_the_in_memory_store(self, monkeypatch):
        self._configure(monkeypatch, "in_memory")

        assert isinstance(ScheduleStoreBuilder.build(), InMemoryScheduleStore)

    def test_builds_a_bring_your_own_store_from_a_dotted_path(self, monkeypatch):
        self._configure(monkeypatch, f"{_CustomScheduleStore.__module__}._CustomScheduleStore")

        assert isinstance(ScheduleStoreBuilder.build(), _CustomScheduleStore)

    def test_builds_the_redis_store(self, monkeypatch):
        self._configure(monkeypatch, "redis", redis={"prefix": PREFIX})

        assert isinstance(ScheduleStoreBuilder.build(), RedisScheduleStore)

    def test_builds_the_valkey_store(self, monkeypatch):
        self._configure(monkeypatch, "valkey", valkey={"prefix": PREFIX})

        assert isinstance(ScheduleStoreBuilder.build(), ValkeyScheduleStore)

    def test_builds_the_dynamodb_store(self, monkeypatch):
        self._configure(monkeypatch, "dynamodb", dynamodb={"table_name": TABLE_NAME})

        assert isinstance(ScheduleStoreBuilder.build(), DynamoDBScheduleStore)

    def test_a_missing_extra_points_at_the_pip_extra(self, monkeypatch):
        # Poisoning sys.modules with None makes the branch's import raise ImportError, which
        # require_extra rewrites with an install hint.
        monkeypatch.setitem(sys.modules, "agentkernel.schedule.store.valkey", None)
        self._configure(monkeypatch, "valkey")

        with pytest.raises(ImportError, match='pip install "agentkernel\\[valkey\\]"'):
            ScheduleStoreBuilder.build()

    def test_the_builtin_list_names_every_shipped_backend(self):
        # The unknown-type AKConfigError names this list, so it is user-facing.
        assert _BUILTIN_SCHEDULE_STORES == ["in_memory", "redis", "valkey", "dynamodb"]

    def test_unknown_short_name_is_a_config_error(self, monkeypatch):
        self._configure(monkeypatch, "postgres")

        with pytest.raises(AKConfigError, match="unknown schedule store type 'postgres'"):
            ScheduleStoreBuilder.build()

    def test_dotted_path_to_a_non_store_is_a_config_error(self, monkeypatch):
        self._configure(monkeypatch, "agentkernel.schedule.model.ScheduledTask")

        with pytest.raises(AKConfigError, match="not a ScheduleStore subclass"):
            ScheduleStoreBuilder.build()

    def test_unconfigured_capability_cannot_build_a_store(self, monkeypatch):
        config = AKConfig.get().model_copy(update={"schedule": None})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

        with pytest.raises(ValueError, match="Scheduling is not configured"):
            ScheduleStoreBuilder.build()

    def test_every_abstract_method_is_implemented_by_the_builtin(self):
        # A backend that silently inherits an abstract method would fail at first use, not at build.
        assert not (set(ScheduleStore.__abstractmethods__) - set(vars(InMemoryScheduleStore)))
