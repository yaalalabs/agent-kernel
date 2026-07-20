import pytest
import valkey

from agentkernel.core.session.valkey import ValkeySessionStore
from agentkernel.core.util.driver import base as driver_base
from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.core.util.driver.valkey import ValkeyDriver


class FakeValkeyClient:
    """Minimal in-memory stand-in for a valkey client (hash-per-key)."""

    def __init__(self):
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.expirations: dict[str, int] = {}

    def ping(self):
        return True

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def hkeys(self, name):
        return [k.encode("utf-8") for k in self.hashes.get(name, {}).keys()]

    def exists(self, key):
        return 1 if key in self.hashes else 0

    def expire(self, name, time):
        self.expirations[name] = time

    def scan_iter(self, match=None, count=None):
        prefix = match[:-1] if match and match.endswith("*") else (match or "")
        return [k for k in self.hashes if k.startswith(prefix)]

    def delete(self, *keys):
        for k in keys:
            self.hashes.pop(k, None)


def _make_cfg(ttl: int = 60):
    class FakeCfg:
        class session:
            type = "valkey"

            class valkey:
                url = "valkey://localhost:6379"
                prefix = "ak:test:"

    FakeCfg.session.valkey.ttl = ttl
    return FakeCfg


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeValkeyClient()
    monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: client)
    return client


def _store(monkeypatch, ttl: int = 60):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _make_cfg(ttl)))
    return ValkeySessionStore()


def test_new_creates_sentinel_and_applies_ttl(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    session = store.new("s1")
    assert session.id == "s1"
    key = "ak:test:s1"
    assert "__init__" in fake_client.hashes[key]
    assert fake_client.expirations[key] == 60


def test_new_skips_expire_when_ttl_zero(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=0)
    store.new("s-zero")
    assert "ak:test:s-zero" not in fake_client.expirations


def test_store_and_load_roundtrip(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    session = store.new("s2")
    session.set("greeting", "hello")
    session.set("count", 3)
    store.store(session)

    loaded = store.load("s2", strict=True)
    assert loaded.get("greeting") == "hello"
    assert loaded.get("count") == 3


def test_load_skips_init_sentinel(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    session = store.new("s3")
    session.set("k", "v")
    store.store(session)

    loaded = store.load("s3", strict=True)
    keys = [k for k, _ in loaded.get_all(volatile=False)]
    assert "__init__" not in keys
    assert "k" in keys


def test_load_missing_strict_raises(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    with pytest.raises(KeyError):
        store.load("missing", strict=True)


def test_load_missing_non_strict_creates(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    session = store.load("fresh", strict=False)
    assert session.id == "fresh"


def test_clear_removes_prefixed_keys(fake_client, monkeypatch):
    store = _store(monkeypatch, ttl=60)
    store.new("a")
    store.new("b")
    assert len(fake_client.hashes) == 2
    store.clear()
    assert fake_client.hashes == {}


def test_connect_raises_after_retries(monkeypatch):
    # Avoid the 2-second back-off sleeps between the three attempts.
    monkeypatch.setattr(driver_base.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def always_fail(*a, **k):
        calls["n"] += 1
        raise valkey.ConnectionError("boom")

    monkeypatch.setattr(valkey_driver_module.valkey, "from_url", always_fail)

    driver = ValkeyDriver(url="valkey://localhost:6379", prefix="ak:test:", ttl=60)
    with pytest.raises(valkey.ValkeyError):
        _ = driver.client
    # Three attempts, then the last error re-raised (not a None-client AttributeError).
    assert calls["n"] == 3
