"""Unit tests for the shared database drivers in ``agentkernel.core.util.driver``."""

import decimal
import json
from unittest.mock import MagicMock

import pytest
import redis

from agentkernel.core.util.driver import base as driver_base
from agentkernel.core.util.driver import dynamodb as dynamodb_module
from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.core.util.driver.dynamodb import DynamoDBDriver
from agentkernel.core.util.driver.redis import RedisDriver


@pytest.fixture
def sleep_calls(monkeypatch):
    """Patch out the retry back-off sleeps, counting them."""
    calls = {"n": 0}

    def fake_sleep(*_):
        calls["n"] += 1

    monkeypatch.setattr(driver_base.time, "sleep", fake_sleep)
    return calls


def _driver(ttl: int = 0, prefix: str = "", client: MagicMock = None) -> RedisDriver:
    """Build a RedisDriver with an already-established mocked client."""
    driver = RedisDriver(url="redis://localhost:6379", prefix=prefix, ttl=ttl)
    driver._client = client if client is not None else MagicMock()
    return driver


class TestRetry:
    """Connection retry semantics (shared retry helper)."""

    def test_redis_connect_reraises_last_error_after_retries(self, sleep_calls, monkeypatch):
        calls = {"n": 0}

        def always_fail(*a, **k):
            calls["n"] += 1
            raise redis.ConnectionError("boom")

        monkeypatch.setattr(redis_driver_module.redis, "from_url", always_fail)
        driver = RedisDriver(url="redis://localhost:6379")
        with pytest.raises(redis.RedisError):
            _ = driver.client
        assert calls["n"] == 3
        assert sleep_calls["n"] == 2

    def test_redis_error_outside_scope_fails_fast(self, sleep_calls, monkeypatch):
        calls = {"n": 0}

        def bad_url(*a, **k):
            calls["n"] += 1
            raise ValueError("malformed URL")

        monkeypatch.setattr(redis_driver_module.redis, "from_url", bad_url)
        driver = RedisDriver(url="not-a-url")
        with pytest.raises(ValueError):
            _ = driver.client
        assert calls["n"] == 1
        assert sleep_calls["n"] == 0

    def test_dynamodb_connect_reraises_last_error_after_retries(self, sleep_calls, monkeypatch):
        calls = {"n": 0}

        def always_fail(*a, **k):
            calls["n"] += 1
            raise RuntimeError("no table")

        monkeypatch.setattr(dynamodb_module.boto3, "resource", always_fail)
        driver = DynamoDBDriver(table_name="t", partition_key="pk")
        with pytest.raises(RuntimeError):
            _ = driver.table
        assert calls["n"] == 3
        assert sleep_calls["n"] == 2


class TestDynamoDecimalCodec:
    """DynamoDB stores no floats and returns no ints; both halves of that are converted here."""

    def test_floats_become_decimals_recursively(self):
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        converted = DynamoDecimalCodec.to_dynamo({"price": 2.5, "nested": {"xs": [1.5, 2]}, "name": "x"})

        assert converted == {"price": decimal.Decimal("2.5"), "nested": {"xs": [decimal.Decimal("1.5"), 2]}, "name": "x"}

    def test_decimal_uses_the_printed_form_not_the_binary_expansion(self):
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        assert DynamoDecimalCodec.to_dynamo({"price": 0.1})["price"] == decimal.Decimal("0.1")

    def test_bools_are_not_treated_as_numbers(self):
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        converted = DynamoDecimalCodec.to_dynamo({"active": True, "off": False})

        assert converted == {"active": True, "off": False}
        assert isinstance(converted["active"], bool)

    def test_decimals_come_back_as_int_or_float(self):
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        restored = DynamoDecimalCodec.from_dynamo({"count": decimal.Decimal("3"), "price": decimal.Decimal("2.5")})

        assert restored == {"count": 3, "price": 2.5}
        assert isinstance(restored["count"], int)
        assert isinstance(restored["price"], float)

    def test_round_trip_leaves_a_payload_json_serialisable(self):
        """The point of converting on read: no consumer ever meets a Decimal."""
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        payload = {"price": 250.0, "count": 3, "coords": [1.5, -2.25], "label": "x", "ok": True}

        restored = DynamoDecimalCodec.from_dynamo(DynamoDecimalCodec.to_dynamo(payload))

        assert restored == payload
        assert json.loads(json.dumps(restored)) == payload

    def test_from_dynamo_passes_none_through(self):
        from agentkernel.core.util.driver.dynamodb import DynamoDecimalCodec

        assert DynamoDecimalCodec.from_dynamo(None) is None


class TestPingReconnect:
    """Health-check/reconnect on established Redis clients."""

    def test_failed_ping_reconnects(self, monkeypatch):
        stale = MagicMock()
        stale.ping.side_effect = redis.ConnectionError("gone")
        fresh = MagicMock()
        calls = {"n": 0}

        def from_url(*a, **k):
            calls["n"] += 1
            return fresh

        monkeypatch.setattr(redis_driver_module.redis, "from_url", from_url)
        driver = _driver(client=stale)
        assert driver.client is fresh
        assert calls["n"] == 1

    def test_healthy_ping_does_not_reconnect(self, monkeypatch):
        established = MagicMock()
        monkeypatch.setattr(redis_driver_module.redis, "from_url", MagicMock())
        driver = _driver(client=established)
        assert driver.client is established
        redis_driver_module.redis.from_url.assert_not_called()

    def test_ping_failure_outside_error_class_propagates(self, monkeypatch):
        broken = MagicMock()
        broken.ping.side_effect = TypeError("programming fault")
        from_url = MagicMock()
        monkeypatch.setattr(redis_driver_module.redis, "from_url", from_url)
        driver = _driver(client=broken)
        with pytest.raises(TypeError):
            _ = driver.client
        from_url.assert_not_called()

    def test_concurrent_failed_pings_connect_once(self, monkeypatch):
        stale = MagicMock()
        fresh = MagicMock()
        calls = {"n": 0}

        def from_url(*a, **k):
            calls["n"] += 1
            return fresh

        monkeypatch.setattr(redis_driver_module.redis, "from_url", from_url)
        driver = _driver(client=stale)
        # Two threads observed the same failed client; the first lock holder
        # reconnects, the second sees _client already replaced (identity compare
        # against the object whose ping failed) and skips.
        driver._ensure_connected(expected=stale)
        driver._ensure_connected(expected=stale)
        assert calls["n"] == 1
        assert driver._client is fresh

    def test_concurrent_first_use_connects_once(self, monkeypatch):
        fresh = MagicMock()
        calls = {"n": 0}

        def from_url(*a, **k):
            calls["n"] += 1
            return fresh

        monkeypatch.setattr(redis_driver_module.redis, "from_url", from_url)
        driver = RedisDriver(url="redis://localhost:6379")
        driver._ensure_connected(expected=None)
        driver._ensure_connected(expected=None)
        assert calls["n"] == 1


class TestRedisCommandSurface:
    """Command semantics of the shared Redis/Valkey surface."""

    def test_set_applies_ttl_only_when_positive(self):
        driver = _driver(ttl=60)
        driver.set("k", "v")
        driver._client.set.assert_called_once_with("k", "v", ex=60)

        driver = _driver(ttl=0)
        driver.set("k", "v")
        driver._client.set.assert_called_once_with("k", "v")

    def test_set_nx_returns_whether_applied(self):
        driver = _driver(ttl=60)
        driver._client.set.return_value = True
        assert driver.set("k", "v", nx=True) is True
        driver._client.set.assert_called_once_with("k", "v", ex=60, nx=True)

        driver._client.set.return_value = None  # SET NX lost the race
        assert driver.set("k", "v", nx=True) is False

    def test_expire_uses_configured_ttl(self):
        driver = _driver(ttl=60)
        driver.expire("k")
        driver._client.expire.assert_called_once_with(name="k", time=60)

    def test_expire_is_noop_when_ttl_disabled(self):
        # A raw EXPIRE key 0 would delete the key, so ttl <= 0 must never reach the client.
        driver = _driver(ttl=0)
        driver.expire("k")
        driver._client.expire.assert_not_called()

    def test_key_applies_prefix(self):
        driver = _driver(prefix="ak:test:")
        assert driver.key("s1:meta") == "ak:test:s1:meta"

    def test_clear_prefix_scans_and_deletes(self):
        driver = _driver(prefix="ak:test:")
        driver._client.scan_iter.return_value = [b"ak:test:a", b"ak:test:b"]
        driver.clear_prefix()
        driver._client.scan_iter.assert_called_once_with(match="ak:test:*", count=1000)
        driver._client.delete.assert_called_once_with(b"ak:test:a", b"ak:test:b")

    def test_smembers_and_scan_keys_decode_bytes(self):
        driver = _driver(prefix="ak:test:")
        driver._client.smembers.return_value = {b"s1", "s2"}
        assert driver.smembers("k") == {"s1", "s2"}
        driver._client.scan_iter.return_value = [b"ak:test:s1:meta"]
        assert driver.scan_keys("*:meta") == ["ak:test:s1:meta"]
        driver._client.scan_iter.assert_called_with(match="ak:test:*:meta")

    def test_lpop_decodes_bytes(self):
        driver = _driver()
        driver._client.lpop.return_value = b"a1"
        assert driver.lpop("k") == "a1"
        driver._client.lpop.return_value = None
        assert driver.lpop("k") is None


class TestDynamoDBDriver:
    """Item-dict semantics of the shared DynamoDB driver."""

    def _driver(self, sort_key="sk", ttl=0) -> DynamoDBDriver:
        driver = DynamoDBDriver(table_name="t", partition_key="pk", sort_key=sort_key, ttl=ttl)
        driver._table = MagicMock()
        return driver

    def test_put_attaches_expiry_time_only_when_ttl_positive(self):
        driver = self._driver(ttl=60)
        driver.put({"pk": "p", "sk": "s"})
        item = driver._table.put_item.call_args.kwargs["Item"]
        assert item["expiry_time"] > 0

        driver = self._driver(ttl=0)
        driver.put({"pk": "p", "sk": "s"})
        item = driver._table.put_item.call_args.kwargs["Item"]
        assert "expiry_time" not in item

    def test_put_does_not_mutate_caller_dict(self):
        driver = self._driver(ttl=60)
        message = {"pk": "p", "sk": "s"}
        driver.put(message)
        assert "expiry_time" not in message

    def test_get_returns_raw_item_or_none(self):
        driver = self._driver()
        driver._table.get_item.return_value = {"Item": {"pk": "p", "sk": "s", "value": b"x"}}
        assert driver.get("p", "s") == {"pk": "p", "sk": "s", "value": b"x"}
        driver._table.get_item.assert_called_once_with(Key={"pk": "p", "sk": "s"})

        driver._table.get_item.return_value = {}
        assert driver.get("p", "missing") is None

    def test_query_sort_keys_follows_pagination(self):
        driver = self._driver()
        driver._table.query.side_effect = [
            {"Items": [{"sk": "a"}, {"sk": "b"}], "LastEvaluatedKey": {"pk": "p", "sk": "b"}},
            {"Items": [{"sk": "c"}]},
        ]
        assert driver.query_sort_keys("p") == ["a", "b", "c"]
        assert driver._table.query.call_count == 2
        assert driver._table.query.call_args.kwargs["ExclusiveStartKey"] == {"pk": "p", "sk": "b"}

    def test_sort_key_less_mode(self):
        driver = self._driver(sort_key=None)
        driver._table.get_item.return_value = {"Item": {"pk": "p", "body": "b"}}
        assert driver.get("p") == {"pk": "p", "body": "b"}
        driver._table.get_item.assert_called_once_with(Key={"pk": "p"})
        driver.delete("p")
        driver._table.delete_item.assert_called_once_with(Key={"pk": "p"})
        with pytest.raises(ValueError):
            driver.query_sort_keys("p")
