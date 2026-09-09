import pytest
import redis

from agentkernel.core.session.redis import RedisSessionStore
from agentkernel.core.util.driver import base as driver_base
from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.core.util.driver.redis import RedisDriver


def test_connect_raises_after_retries(monkeypatch):
    """The shared RedisDriver re-raises the last error once retries are exhausted
    instead of leaving a None client that later fails with AttributeError."""
    # Avoid the 2-second back-off sleeps between the three attempts.
    monkeypatch.setattr(driver_base.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def always_fail(*a, **k):
        calls["n"] += 1
        raise redis.ConnectionError("boom")

    monkeypatch.setattr(redis_driver_module.redis, "from_url", always_fail)

    driver = RedisDriver(url="redis://localhost:6379", prefix="ak:test:", ttl=60)
    with pytest.raises(redis.RedisError):
        _ = driver.client
    assert calls["n"] == 3


def test_missing_config_block_raises(monkeypatch):
    """A missing session.redis block raises a ValueError (matching the Valkey store)
    instead of an AttributeError from the config reads."""

    class FakeCfg:
        class session:
            type = "redis"
            redis = None

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))
    with pytest.raises(ValueError, match="session.redis config block is required"):
        RedisSessionStore()
