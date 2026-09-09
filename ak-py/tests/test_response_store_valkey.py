import pytest

from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.core.response_store.factory import ResponseStoreFactory
from agentkernel.deployment.aws.core.response_store.valkey import ValkeyResponseStore


class FakeValkeyClient:
    """Minimal in-memory stand-in for a valkey string client."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_ex: dict[str, int] = {}

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.set_ex[key] = ex
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeValkeyClient()
    monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: client)
    return client


def _message(request_id="req-1", body=None):
    return {"request_id": request_id, "session_id": "s-1", "body": body or {"text": "hi"}}


def test_client_is_created_lazily_on_first_operation(monkeypatch):
    client = FakeValkeyClient()
    calls = {"n": 0}

    def from_url(*a, **k):
        calls["n"] += 1
        return client

    monkeypatch.setattr(valkey_driver_module.valkey, "from_url", from_url)
    store = ValkeyResponseStore(url="valkey://localhost:6379")
    assert calls["n"] == 0  # no eager connect in __init__
    store.add_message(_message("abc"))
    assert calls["n"] == 1


def test_get_record_returns_the_full_record(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379")
    store.add_message({"request_id": "r-1", "session_id": "s-1", "status_code": 500, "body": {"error": "boom"}})

    record = store.get_record("r-1")
    assert record["status_code"] == 500
    assert record["body"] == {"error": "boom"}

    assert store.get_record("r-1", get_and_delete=True) is not None
    assert store.get_record("r-1") is None


def test_add_message_stores_under_prefixed_key(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:", ttl=0)
    store.add_message(_message("abc"))
    assert "ak:resp:abc" in fake_client.store
    # ttl == 0 disables expiry (no ex passed to SET)
    assert "ak:resp:abc" not in fake_client.set_ex


def test_add_message_applies_ttl_when_positive(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:", ttl=120)
    store.add_message(_message("abc"))
    # TTL is applied atomically via SET ... EX
    assert fake_client.set_ex["ak:resp:abc"] == 120


def test_get_message_miss_returns_none(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379")
    assert store.get_message("nope") is None


def test_get_message_returns_body(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:")
    store.add_message(_message("abc", body={"answer": 42}))
    assert store.get_message("abc") == {"answer": 42}


def test_get_and_delete_removes_key(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:")
    store.add_message(_message("abc", body={"answer": 42}))
    assert store.get_message("abc", get_and_delete=True) == {"answer": 42}
    assert "ak:resp:abc" not in fake_client.store


def _handler_cfg(valkey_block):
    class FakeCfg:
        class execution:
            class response_store:
                type = "valkey"
                valkey = valkey_block
                redis = None
                dynamodb = None

    return FakeCfg


class _ValkeyCfg:
    url = "valkey://localhost:6379"
    prefix = "ak:responses:"
    ttl = 0


def test_factory_selects_valkey_store(fake_client, monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _handler_cfg(_ValkeyCfg)))
    assert isinstance(ResponseStoreFactory.create(), ValkeyResponseStore)


def test_factory_missing_valkey_block_raises(monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _handler_cfg(None)))
    with pytest.raises(AKConfigError, match="no valid response store"):
        ResponseStoreFactory.create()
