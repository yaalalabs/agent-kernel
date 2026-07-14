import pytest

from agentkernel.deployment.aws.core.response_store import valkey as valkey_module
from agentkernel.deployment.aws.core.response_store.handler import ResponseDBHandler
from agentkernel.deployment.aws.core.response_store.valkey import ValkeyResponseStore


class FakeValkeyClient:
    """Minimal in-memory stand-in for a valkey string client."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def expire(self, name, time):
        self.expirations[name] = time

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeValkeyClient()
    monkeypatch.setattr(valkey_module.valkey.Valkey, "from_url", classmethod(lambda cls, *a, **k: client))
    return client


def _message(request_id="req-1", body=None):
    return {"request_id": request_id, "session_id": "s-1", "body": body or {"text": "hi"}}


def test_add_message_stores_under_prefixed_key(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:", ttl=0)
    store.add_message(_message("abc"))
    assert "ak:resp:abc" in fake_client.store
    # ttl == 0 disables expiry
    assert "ak:resp:abc" not in fake_client.expirations


def test_add_message_applies_ttl_when_positive(fake_client):
    store = ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:resp:", ttl=120)
    store.add_message(_message("abc"))
    assert fake_client.expirations["ak:resp:abc"] == 120


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


def test_handler_selects_valkey_store(fake_client, monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _handler_cfg(_ValkeyCfg)))
    handler = ResponseDBHandler()
    assert isinstance(handler.get_store(), ValkeyResponseStore)


def test_handler_missing_valkey_block_raises(monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _handler_cfg(None)))
    with pytest.raises(ValueError):
        ResponseDBHandler()
