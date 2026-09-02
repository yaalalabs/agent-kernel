"""The #503 optional key-scan capability on ``ResponseStore``: default opt-out on the ABC,
and the four built-in implementations (in_memory real; redis/valkey/dynamodb over fake
drivers, the shared-driver test style)."""

import json
import types
from typing import Dict

import pytest

from agentkernel.pipeline.response_store.base import ResponseStore
from agentkernel.pipeline.response_store.dynamodb import DynamoDBResponseStore
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.response_store.redis import RedisResponseStore


class _MinimalStore(ResponseStore):
    """Bare concrete store: exercises the ABC's default (opted-out) scan capability."""

    def add_message(self, message: Dict) -> None:  # pragma: no cover - unused
        pass

    def get_message(self, request_id: str, get_and_delete: bool = False) -> Dict | None:  # pragma: no cover - unused
        return None

    def get_record(self, request_id: str, get_and_delete: bool = False) -> Dict | None:  # pragma: no cover - unused
        return None

    def delete_message(self, request_id: str) -> None:  # pragma: no cover - unused
        pass


class TestScanCapabilityDefault:
    def test_base_default_is_opted_out(self):
        store = _MinimalStore()
        assert store.supports_key_scan() is False
        with pytest.raises(NotImplementedError, match="does not support key scans"):
            store.scan_records("session:")


class TestInMemoryScan:
    @pytest.fixture(autouse=True)
    def _reset(self):
        InMemoryResponseStore.reset()
        yield
        InMemoryResponseStore.reset()

    def test_scan_returns_prefix_matches_as_copies(self):
        store = InMemoryResponseStore()
        store.add_message({"request_id": "session:a", "body": {"sandbox_id": "sb-a"}})
        store.add_message({"request_id": "session:b", "body": {"sandbox_id": "sb-b"}})
        store.add_message({"request_id": "task-1", "body": {}})
        assert store.supports_key_scan() is True
        records = store.scan_records("session:")
        assert sorted(record["request_id"] for record in records) == ["session:a", "session:b"]
        records[0]["mutated"] = True  # copies: scan results never alias the stored records
        assert "mutated" not in store.get_record(records[0]["request_id"])


class _FakeRedisLikeDriver:
    """The scan surface of the shared redis-like drivers: key(), client.scan_iter(), get()."""

    def __init__(self, prefix: str, data: dict):
        self._prefix = prefix
        self._data = data
        self.client = types.SimpleNamespace(scan_iter=self._scan_iter)

    def key(self, suffix: str) -> str:
        return f"{self._prefix}{suffix}"

    def _scan_iter(self, match: str):
        assert match.endswith("*")
        stem = match[:-1]
        return iter(sorted(key for key in self._data if key.startswith(stem)))

    def get(self, key: str):
        return self._data.get(key)


class TestRedisLikeScan:
    def test_scan_parses_matching_records(self):
        data = {
            "ak:responses:session:a": json.dumps({"request_id": "session:a", "body": {"sandbox_id": "sb-a"}}),
            "ak:responses:session:b": json.dumps({"request_id": "session:b", "body": {"sandbox_id": "sb-b"}}),
            "ak:responses:task-1": json.dumps({"request_id": "task-1", "body": {}}),
        }
        store = RedisResponseStore.__new__(RedisResponseStore)
        store._driver = _FakeRedisLikeDriver("ak:responses:", data)
        assert store.supports_key_scan() is True
        records = store.scan_records("session:")
        assert sorted(record["request_id"] for record in records) == ["session:a", "session:b"]

    def test_valkey_twin_matches(self):
        pytest.importorskip("valkey")
        from agentkernel.pipeline.response_store.valkey import ValkeyResponseStore

        store = ValkeyResponseStore.__new__(ValkeyResponseStore)
        store._driver = _FakeRedisLikeDriver("ak:responses:", {"ak:responses:session:a": json.dumps({"request_id": "session:a", "body": {}})})
        assert store.supports_key_scan() is True
        assert [record["request_id"] for record in store.scan_records("session:")] == ["session:a"]


class _FakeDynamoTable:
    """Two-page scan: exercises the LastEvaluatedKey pagination loop."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        index = len([call for call in self.calls if True]) - 1
        page = dict(self._pages[index])
        return page


class TestDynamoDBScan:
    def test_scan_paginates_and_filters(self):
        pytest.importorskip("boto3")
        table = _FakeDynamoTable(
            pages=[
                {"Items": [{"request_id": "session:a", "body": {}}], "LastEvaluatedKey": {"request_id": "session:a"}},
                {"Items": [{"request_id": "session:b", "body": {}}]},
            ]
        )
        store = DynamoDBResponseStore.__new__(DynamoDBResponseStore)
        store._driver = types.SimpleNamespace(table=table)
        assert store.supports_key_scan() is True
        records = store.scan_records("session:")
        assert [record["request_id"] for record in records] == ["session:a", "session:b"]
        assert len(table.calls) == 2
        assert "FilterExpression" in table.calls[0]
        assert table.calls[1]["ExclusiveStartKey"] == {"request_id": "session:a"}
