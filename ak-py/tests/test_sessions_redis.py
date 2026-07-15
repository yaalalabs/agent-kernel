import pytest
import redis

from agentkernel.core.session import redis as redis_module
from agentkernel.core.session.redis import RedisDriver


def _make_cfg():
    class FakeCfg:
        class session:
            type = "redis"

            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    return FakeCfg


def test_connect_raises_after_retries(monkeypatch):
    """The corrected RedisDriver re-raises the last error once retries are exhausted
    instead of leaving a None client that later fails with AttributeError."""
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _make_cfg()))
    # Avoid the 2-second back-off sleeps between the three attempts.
    monkeypatch.setattr(redis_module.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def always_fail(*a, **k):
        calls["n"] += 1
        raise redis.ConnectionError("boom")

    monkeypatch.setattr(redis_module.redis, "from_url", always_fail)

    driver = RedisDriver()
    with pytest.raises(redis.RedisError):
        _ = driver.client
    assert calls["n"] == 3
