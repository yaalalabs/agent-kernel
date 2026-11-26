"""The credentials capability (#603, spec section 5).

Iteration 24: the encrypted credential store. `CredentialCipher`, `CredentialStoreContract` run over the in-memory,
Redis, Valkey and DynamoDB backends (the redis-likes over a fake client at `store._driver._client`, DynamoDB over a
fake driver, the `test_schedule_store.py` pattern), and `CredentialStoreFactory`.

Iteration 25: exchange, the broker and retention. `TokenExchangerContract` over `passthrough` and a recording fake,
`TokenExchangerFactory`, `CredentialManager` (retain, release, forget), `CredentialBroker`, `ToolContext.credentials`,
and the inbound credential deleted when its run ends on the direct and the queued paths, with no token in a queue
body or a log record.
"""

import asyncio
import base64
import fnmatch
import json
import logging
import math
import os
import sys
import time

import pytest
import pytest_asyncio
from boto3.dynamodb.types import Binary

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import _CredentialsConfig, _ExchangerConfig
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentReplyText, AgentRequestText, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.core.util.driver.valkey import ValkeyDriver
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.credential.broker import CredentialBroker
from agentkernel.identity.credential.dynamodb import DynamoDBCredentialStore
from agentkernel.identity.credential.exchange import IssuedToken, PassthroughTokenExchanger, TokenExchanger, TokenExchangerFactory
from agentkernel.identity.credential.in_memory import InMemoryCredentialStore
from agentkernel.identity.credential.manager import CredentialManager
from agentkernel.identity.credential.redis import RedisCredentialStore
from agentkernel.identity.credential.store import CredentialCipher, CredentialStore, CredentialStoreFactory
from agentkernel.identity.credential.testing import TOKEN, CredentialStoreContract, TokenExchangerContract
from agentkernel.identity.credential.valkey import ValkeyCredentialStore
from agentkernel.identity.errors import CredentialError

KEY_NAME = "AK_CREDENTIAL_KEY"


def _cipher() -> CredentialCipher:
    return CredentialCipher(os.urandom(CredentialCipher.KEY_BYTES))


def _encoded(key: bytes, padding: bool = False) -> str:
    text = base64.urlsafe_b64encode(key).decode()
    return text if padding else text.rstrip("=")


# --- the cipher ---------------------------------------------------------------------------------------


class TestCredentialCipher:
    def test_a_value_decrypts_to_what_was_encrypted(self):
        cipher = _cipher()

        assert cipher.decrypt(cipher.encrypt(TOKEN, "ref-1"), "ref-1") == TOKEN

    def test_the_ciphertext_is_a_nonce_then_the_sealed_value(self):
        sealed = _cipher().encrypt(TOKEN, "ref-1")

        assert len(sealed) == CredentialCipher.NONCE_BYTES + len(TOKEN) + 16  # 16 is the GCM tag
        assert TOKEN not in sealed

    def test_each_encryption_takes_a_fresh_nonce(self):
        cipher = _cipher()

        first, second = cipher.encrypt(TOKEN, "ref-1"), cipher.encrypt(TOKEN, "ref-1")

        assert first[: CredentialCipher.NONCE_BYTES] != second[: CredentialCipher.NONCE_BYTES]
        assert first != second

    def test_another_key_cannot_decrypt(self):
        sealed = _cipher().encrypt(TOKEN, "ref-1")

        with pytest.raises(CredentialError, match="could not be decrypted"):
            _cipher().decrypt(sealed, "ref-1")

    def test_a_value_sealed_for_one_reference_cannot_be_opened_as_another(self):
        cipher = _cipher()

        with pytest.raises(CredentialError):
            cipher.decrypt(cipher.encrypt(TOKEN, "ref-1"), "ref-2")

    def test_a_changed_byte_is_detected(self):
        cipher = _cipher()
        sealed = bytearray(cipher.encrypt(TOKEN, "ref-1"))
        sealed[-1] ^= 0x01

        with pytest.raises(CredentialError):
            cipher.decrypt(bytes(sealed), "ref-1")

    def test_a_value_shorter_than_a_nonce_is_refused(self):
        with pytest.raises(CredentialError):
            _cipher().decrypt(b"short", "ref-1")

    @pytest.mark.parametrize("size", [16, 31, 33])
    def test_a_key_that_is_not_32_bytes_is_refused(self, size):
        with pytest.raises(ValueError, match="32"):
            CredentialCipher(os.urandom(size))


class TestTheCipherFromConfiguration:
    def test_no_encryption_key_is_no_cipher(self):
        assert CredentialCipher.from_config(_CredentialsConfig()) is None

    @pytest.mark.parametrize("padding", [False, True])
    def test_the_key_is_read_through_the_secret_capability_and_base64url_decoded(self, monkeypatch, padding):
        key = os.urandom(32)
        monkeypatch.setenv(KEY_NAME, _encoded(key, padding))

        cipher = CredentialCipher.from_config(_CredentialsConfig(encryption_key=KEY_NAME))

        assert CredentialCipher(key).decrypt(cipher.encrypt(TOKEN, "ref-1"), "ref-1") == TOKEN

    def test_a_key_the_secret_capability_does_not_have_is_a_configuration_error(self, monkeypatch):
        monkeypatch.delenv(KEY_NAME, raising=False)

        with pytest.raises(AKConfigError, match=f"identity.credentials.encryption_key: secret '{KEY_NAME}' not found"):
            CredentialCipher.from_config(_CredentialsConfig(encryption_key=KEY_NAME))

    def test_a_key_name_that_is_not_a_secret_key_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="identity.credentials.encryption_key: 'ak-key' is not a secret key"):
            CredentialCipher.from_config(_CredentialsConfig(encryption_key="ak-key"))

    @pytest.mark.parametrize("size", [16, 24, 48])
    def test_a_key_of_the_wrong_length_is_a_configuration_error(self, monkeypatch, size):
        monkeypatch.setenv(KEY_NAME, _encoded(os.urandom(size)))

        with pytest.raises(AKConfigError, match=f"decodes to {size} bytes; it must be 32"):
            CredentialCipher.from_config(_CredentialsConfig(encryption_key=KEY_NAME))

    def test_a_value_that_is_not_base64url_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv(KEY_NAME, "not base64 at all!")

        with pytest.raises(AKConfigError, match="is not base64url"):
            CredentialCipher.from_config(_CredentialsConfig(encryption_key=KEY_NAME))

    def test_the_key_never_appears_in_an_error(self, monkeypatch):
        value = _encoded(os.urandom(24))
        monkeypatch.setenv(KEY_NAME, value)

        with pytest.raises(AKConfigError) as refused:
            CredentialCipher.from_config(_CredentialsConfig(encryption_key=KEY_NAME))

        assert value not in str(refused.value)


# --- the backends -------------------------------------------------------------------------------------


class _FakeRedisLikeClient:
    """In-memory stand-in for the redis/valkey client: the commands the credential store issues, expiry included.

    It honours `px` against the clock, as the server does, so the contract's expired-entry case runs for real.
    """

    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.expiries: dict[str, float] = {}
        self.px: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value, ex: int | None = None, px: int | None = None, nx: bool = False) -> bool:
        self.values[key] = value
        self.expiries.pop(key, None)
        if px is not None:
            self.px[key] = px
            self.expiries[key] = time.time() + px / 1000
        return True

    def get(self, key: str):
        if key in self.expiries and self.expiries[key] <= time.time():
            self.values.pop(key, None)
            self.expiries.pop(key, None)
        return self.values.get(key)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.expiries.pop(key, None)

    _clock = staticmethod(time.time)  # the parameter redis names `time` hides the module inside `expire`

    def expire(self, name: str, time: int) -> bool:
        # As EXPIRE does: only a key that still exists gets the new expiry.
        if self.get(name) is None:
            return False
        self.expiries[name] = self._clock() + time
        return True

    def scan_iter(self, match: str, count: int | None = None):
        return [key for key in list(self.values) if fnmatch.fnmatch(key, match)]


class _FakeDynamoDBTable:
    """The boto3 Table calls the store makes itself: a conditional update that only extends a live item."""

    def __init__(self, items: dict):
        self._items = items
        self.updates: list[dict] = []

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        from botocore.exceptions import ClientError

        self.updates.append({"Key": Key, "ConditionExpression": ConditionExpression})
        item = self._items.get(Key["credential_key"])
        if item is None or float(item["expires_at"]) <= float(ExpressionAttributeValues[":now"]):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "the item is gone"}}, "UpdateItem")
        item["expires_at"] = float(ExpressionAttributeValues[":expires_at"])
        item["expiry_time"] = int(ExpressionAttributeValues[":expiry_time"])


class _FakeDynamoDBDriver:
    """Stand-in for DynamoDBDriver, one item per credential. Like DynamoDB it removes nothing when an item expires."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.table = _FakeDynamoDBTable(self.items)
        self.reads: list[bool] = []

    def put(self, item: dict) -> None:
        self.items[item["credential_key"]] = dict(item)

    def get(self, pk_value: str, sk_value=None, consistent: bool = False) -> dict | None:
        self.reads.append(consistent)
        item = self.items.get(pk_value)
        return None if item is None else dict(item)

    def delete(self, pk_value: str, sk_value=None) -> None:
        self.items.pop(pk_value, None)

    def clear_all(self) -> None:
        self.items.clear()


class TestInMemoryCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def make_store(self):
        return lambda cipher: InMemoryCredentialStore(cipher)

    def test_it_is_kept_in_this_process_only(self):
        assert InMemoryCredentialStore.shared is False

    def test_without_a_key_it_keeps_credentials_as_they_came_and_says_so(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ak.identity.credential.in_memory"):
            store = InMemoryCredentialStore(None)
        store.put("ref-1", TOKEN, time.time() + 60)

        assert (store.get("ref-1"), store._read("ref-1")) == (TOKEN, TOKEN)
        assert "unencrypted" in caplog.text
        store.clear()

    def test_an_expired_credential_is_dropped_when_it_is_read(self):
        store = InMemoryCredentialStore(_cipher())
        store.put("ref-1", TOKEN, time.time() + 0.1)
        time.sleep(0.2)

        assert store.get("ref-1") is None
        assert "ref-1" not in InMemoryCredentialStore._entries


class TestTheInMemoryReadAndARenewal:
    def test_a_read_that_finds_an_entry_expired_never_deletes_one_renewed_since(self, monkeypatch):
        # Another thread renews between the read's lookup and its expiry check: the renewal must stand.
        import agentkernel.identity.credential.in_memory as module

        store = InMemoryCredentialStore(None)
        store.clear()
        store.put("conn:ref", TOKEN, time.time() + 60)
        InMemoryCredentialStore._entries["conn:ref"] = (TOKEN, 100.0)  # as if it expired at t=100
        renewed = []

        class _Clock:
            @staticmethod
            def time():
                if not renewed:  # the read's expiry check: the renewal lands first, at t=99.9
                    renewed.append(True)
                    InMemoryCredentialStore._entries["conn:ref"] = (TOKEN, 220.0)
                return 100.1

        monkeypatch.setattr(module, "time", _Clock)

        store.get("conn:ref")

        assert InMemoryCredentialStore._entries.get("conn:ref") == (TOKEN, 220.0)
        store.clear()


class TestRedisCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def client(self) -> _FakeRedisLikeClient:
        return _FakeRedisLikeClient()

    @pytest.fixture
    def make_store(self, client):
        def _make(cipher):
            store = RedisCredentialStore(url="redis://unused:6379", prefix="ak:cred:", cipher=cipher)
            # An established client, so the driver never connects; its ping health-check passes.
            store._driver._client = client
            return store

        return _make

    def test_a_credential_sits_under_the_prefix_and_expires_with_it(self, store, client):
        expires_at = time.time() + 90

        store.put("ref-1", TOKEN, expires_at)

        assert set(client.values) == {"ak:cred:ref-1"}
        assert 89_000 < client.px["ak:cred:ref-1"] <= 90_000
        assert store._driver.ttl == 0  # no store-wide expiry

    def test_without_a_key_it_refuses_to_be_built(self):
        with pytest.raises(AKConfigError, match="identity.credentials.encryption_key"):
            RedisCredentialStore(url="redis://unused:6379", prefix="ak:cred:", cipher=None)


class TestValkeyCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def make_store(self):
        client = _FakeRedisLikeClient()

        def _make(cipher):
            store = ValkeyCredentialStore(url="valkey://unused:6379", prefix="ak:cred:", cipher=cipher)
            store._driver._client = client
            return store

        return _make

    def test_it_runs_on_the_valkey_driver(self):
        assert isinstance(ValkeyCredentialStore(url="valkey://unused:6379", prefix="ak:cred:", cipher=_cipher())._driver, ValkeyDriver)

    def test_without_a_key_it_refuses_to_be_built(self):
        with pytest.raises(AKConfigError, match="identity.credentials.encryption_key"):
            ValkeyCredentialStore(url="valkey://unused:6379", prefix="ak:cred:", cipher=None)


class TestDynamoDBCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def driver(self) -> _FakeDynamoDBDriver:
        return _FakeDynamoDBDriver()

    @pytest.fixture
    def make_store(self, driver):
        def _make(cipher):
            store = DynamoDBCredentialStore(table_name="ak-credentials", cipher=cipher)
            store._driver = driver
            return store

        return _make

    def test_a_credential_is_one_item_carrying_its_expiry_for_dynamodb_ttl(self, store, driver):
        expires_at = time.time() + 90

        store.put("ref-1", TOKEN, expires_at)

        item = driver.items["ref-1"]
        assert set(item) == {"credential_key", "value", "expires_at", "expiry_time"}
        assert item["expiry_time"] == math.ceil(expires_at)  # what DynamoDB's own TTL reads: whole epoch seconds
        assert TOKEN not in item["value"]

    def test_an_item_dynamodb_has_not_removed_yet_is_not_returned_once_expired(self, store, driver):
        # DynamoDB removes an expired item when it gets to it, which can be long after; the read checks itself.
        store.put("ref-1", TOKEN, time.time() + 60)
        driver.items["ref-1"]["expires_at"] = time.time() - 1

        assert store.get("ref-1") is None

    def test_a_value_boto3_hands_back_as_binary_is_read(self, store, driver):
        store.put("ref-1", TOKEN, time.time() + 60)
        driver.items["ref-1"]["value"] = Binary(driver.items["ref-1"]["value"])

        assert store.get("ref-1") == TOKEN

    def test_without_a_key_it_refuses_to_be_built(self):
        with pytest.raises(AKConfigError, match="identity.credentials.encryption_key"):
            DynamoDBCredentialStore(table_name="ak-credentials", cipher=None)

    def test_a_credential_is_read_with_a_strongly_consistent_read(self, store, driver):
        # The process that runs the agent reads what another process wrote a moment earlier.
        store.put("ref-1", TOKEN, time.time() + 60)

        store.get("ref-1")

        assert driver.reads == [True]

    def test_touch_extends_the_item_only_on_condition_that_it_is_still_live(self, store, driver):
        store.put("ref-1", TOKEN, time.time() + 60)

        store.touch("ref-1", time.time() + 120)

        [update] = driver.table.updates
        assert "attribute_exists(credential_key)" in update["ConditionExpression"] and ":now" in update["ConditionExpression"]

    def test_touch_raises_any_error_but_the_failed_condition(self, store, driver, monkeypatch):
        # Only "the item is gone" is an answer; a throttled or refused update is the store failing.
        from botocore.exceptions import ClientError

        store.put("ref-1", TOKEN, time.time() + 60)

        def throttled(**kwargs):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}}, "UpdateItem")

        monkeypatch.setattr(driver.table, "update_item", throttled)

        with pytest.raises(ClientError):
            store.touch("ref-1", time.time() + 120)


# --- the factory --------------------------------------------------------------------------------------


class _VaultCredentialStore(CredentialStore):
    """A bring-your-own store that reads a setting of its own from the store block."""

    shared = False

    def __init__(self, cipher, mount: str):
        super().__init__(cipher)
        self.mount = mount

    @classmethod
    def from_config(cls, config, cipher):
        return cls(cipher, mount=config.model_extra["mount"])

    def _write(self, key, data, expires_at):
        pass

    def _read(self, key):
        return None

    def _touch(self, key, expires_at):
        pass

    def _remove(self, key):
        pass

    def _clear(self):
        pass


class _SharedVaultCredentialStore(_VaultCredentialStore):
    """The same bring-your-own store, declared shared between processes."""

    shared = True


class TestCredentialStoreFactory:
    @pytest.fixture
    def key(self, monkeypatch):
        monkeypatch.setenv(KEY_NAME, _encoded(os.urandom(32)))
        return KEY_NAME

    def test_the_default_is_the_in_memory_store(self):
        assert isinstance(CredentialStoreFactory.create(_CredentialsConfig()), InMemoryCredentialStore)

    def test_with_a_key_the_in_memory_store_encrypts(self, key):
        store = CredentialStoreFactory.create(_CredentialsConfig(encryption_key=key))
        store.put("ref-1", TOKEN, time.time() + 60)

        assert TOKEN not in store._read("ref-1")
        store.clear()

    @pytest.mark.parametrize(
        "type_, block, expected",
        [
            ("redis", {"redis": {"url": "redis://cache:6379", "prefix": "app:cred:"}}, RedisCredentialStore),
            ("valkey", {"valkey": {"url": "valkey://cache:6379"}}, ValkeyCredentialStore),
            ("DynamoDB", {"dynamodb": {"table_name": "app-credentials"}}, DynamoDBCredentialStore),
        ],
    )
    def test_each_shared_store_is_built_from_its_block(self, key, type_, block, expected):
        store = CredentialStoreFactory.create(_CredentialsConfig(encryption_key=key, store={"type": type_, **block}))

        assert isinstance(store, expected)

    def test_the_redis_store_takes_the_prefix_of_its_block(self, key):
        store = CredentialStoreFactory.create(_CredentialsConfig(encryption_key=key, store={"type": "redis", "redis": {"prefix": "app:cred:"}}))

        assert store._driver.key("ref-1") == "app:cred:ref-1"

    @pytest.mark.parametrize("type_", ["redis", "valkey", "dynamodb"])
    def test_a_shared_store_without_its_block_is_a_configuration_error(self, key, type_):
        with pytest.raises(AKConfigError, match=f"identity.credentials.store.{type_} must be set"):
            CredentialStoreFactory.create(_CredentialsConfig(encryption_key=key, store={"type": type_}))

    def test_a_shared_store_without_an_encryption_key_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="identity.credentials.encryption_key"):
            CredentialStoreFactory.create(_CredentialsConfig(store={"type": "redis", "redis": {}}))

    def test_an_unknown_short_name_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="unknown credential store type 'memcached'"):
            CredentialStoreFactory.create(_CredentialsConfig(store={"type": "memcached"}))

    def test_a_dotted_path_builds_a_store_of_your_own_from_its_block(self, key):
        store = CredentialStoreFactory.create(
            _CredentialsConfig(encryption_key=key, store={"type": f"{__name__}._VaultCredentialStore", "mount": "kv/ak"})
        )

        assert isinstance(store, _VaultCredentialStore)
        assert store.mount == "kv/ak"

    def test_a_dotted_path_to_something_else_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="is not a CredentialStore subclass"):
            CredentialStoreFactory.create(_CredentialsConfig(store={"type": "agentkernel.core.config._CredentialsConfig"}))

    def test_a_missing_client_library_names_the_extra(self, key, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.identity.credential.redis", None)  # as if `redis` were not installed

        with pytest.raises(ImportError, match="'redis' extra"):
            CredentialStoreFactory.create(_CredentialsConfig(encryption_key=key, store={"type": "redis", "redis": {}}))


# --- exports ------------------------------------------------------------------------------------------


class TestExports:
    def test_the_identity_package_exports_the_credential_store_names(self):
        import agentkernel.identity as identity

        assert identity.CredentialError is CredentialError
        assert identity.CredentialCipher is CredentialCipher
        assert identity.CredentialStore is CredentialStore
        assert identity.CredentialStoreFactory is CredentialStoreFactory
        assert identity.InMemoryCredentialStore is InMemoryCredentialStore
        assert "CredentialStoreContract" not in identity.__all__

    def test_the_identity_package_exports_the_exchange_and_broker_names(self):
        import agentkernel.identity as identity

        assert identity.TokenExchanger is TokenExchanger
        assert identity.IssuedToken is IssuedToken
        assert identity.PassthroughTokenExchanger is PassthroughTokenExchanger
        assert identity.TokenExchangerFactory is TokenExchangerFactory
        assert identity.CredentialBroker is CredentialBroker
        assert identity.CredentialManager is CredentialManager
        assert "TokenExchangerContract" not in identity.__all__

    def test_importing_the_package_loads_no_credential_store(self):
        import subprocess

        loaded = subprocess.run(
            [sys.executable, "-c", "import sys, agentkernel.identity; print([m for m in sys.modules if '.credential' in m])"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        assert loaded == "[]"


# --- iteration 25: exchange -------------------------------------------------------------------------


def _jwt(**claims) -> str:
    """A token shaped like a JWT: what passthrough reads ``exp`` from. Nothing here checks its signature."""

    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


AUDIENCE = "https://api.billing.example"


class TestPassthroughExchanger(TokenExchangerContract):
    @pytest.fixture
    def exchanger(self):
        return PassthroughTokenExchanger(_ExchangerConfig(audience=self.AUDIENCE), inbound_ttl=300)

    @pytest.fixture
    def inbound(self):
        return _jwt(sub="alice", exp=int(time.time()) + 120)

    @pytest.mark.asyncio
    async def test_the_inbound_token_is_forwarded_as_it_came(self, exchanger, inbound):
        assert (await exchanger.exchange(inbound, self.AUDIENCE, [], None)).access_token == inbound

    def test_what_it_issues_is_never_cached(self, exchanger):
        # It is the user's token: a cached copy would outlive the run it was kept for.
        assert (PassthroughTokenExchanger.cacheable, TokenExchanger.cacheable) == (False, True)

    @pytest.mark.asyncio
    async def test_it_expires_with_the_inbound_token(self, exchanger):
        exp = int(time.time()) + 120

        issued = await exchanger.exchange(_jwt(exp=exp), self.AUDIENCE, [], None)

        assert issued.expires_at == exp

    @pytest.mark.asyncio
    async def test_it_is_never_kept_longer_than_an_inbound_credential(self, exchanger):
        # A cached copy of the inbound token must not outlive what inbound_ttl allows the inbound credential.
        issued = await exchanger.exchange(_jwt(exp=int(time.time()) + 3600), self.AUDIENCE, [], None)

        assert issued.expires_at <= time.time() + 300

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["opaque-token", "a.b.c", _jwt(sub="alice"), _jwt(exp="soon")])
    async def test_a_token_whose_expiry_cannot_be_read_gets_the_inbound_ttl(self, exchanger, token):
        issued = await exchanger.exchange(token, self.AUDIENCE, [], None)

        assert time.time() + 299 <= issued.expires_at <= time.time() + 300

    def test_it_says_at_startup_that_it_is_for_development(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ak.identity.credential.exchange"):
            PassthroughTokenExchanger(_ExchangerConfig(audience=AUDIENCE), inbound_ttl=300)

        assert f"passthrough exchanger configured for {AUDIENCE}: the inbound token is forwarded as-is; dev only" in caplog.text


class _RecordingExchanger(TokenExchanger):
    """A bring-your-own exchanger that records what it was asked and issues a token of its own."""

    def __init__(self, config):
        super().__init__(config)
        self.calls: list[tuple] = []
        self.realm = config.model_extra.get("realm")
        self.lifetime = 600.0
        self.failure: Exception | None = None

    async def exchange(self, inbound, audience, scopes, actor):
        self.calls.append((inbound, audience, list(scopes), actor))
        if self.failure is not None:
            raise self.failure
        return IssuedToken(access_token=f"issued-{len(self.calls)}", expires_at=time.time() + self.lifetime)


class TestAFakeExchanger(TokenExchangerContract):
    @pytest.fixture
    def exchanger(self):
        return _RecordingExchanger(_ExchangerConfig(audience=self.AUDIENCE))

    @pytest.fixture
    def inbound(self):
        return "inbound-token"

    @pytest.mark.asyncio
    async def test_the_actor_reaches_the_exchanger(self, exchanger, inbound, actor):
        await exchanger.exchange(inbound, self.AUDIENCE, ["read"], actor)

        assert exchanger.calls == [(inbound, self.AUDIENCE, ["read"], actor)]


class TestTokenExchangerFactory:
    def test_passthrough_is_the_default(self):
        exchanger = TokenExchangerFactory.create(_ExchangerConfig(audience=AUDIENCE), inbound_ttl=300)

        assert isinstance(exchanger, PassthroughTokenExchanger)
        assert (exchanger.audience, exchanger.scopes) == (AUDIENCE, [])

    def test_an_exchanger_keeps_the_scopes_it_asks_for_by_default(self):
        exchanger = TokenExchangerFactory.create(_ExchangerConfig(audience=AUDIENCE, scopes=["invoices.read"]), inbound_ttl=300)

        assert exchanger.scopes == ["invoices.read"]

    def test_a_dotted_path_builds_an_exchanger_of_your_own_from_its_block(self):
        config = _ExchangerConfig.model_validate({"audience": AUDIENCE, "type": f"{__name__}._RecordingExchanger", "realm": "corp"})

        exchanger = TokenExchangerFactory.create(config, inbound_ttl=300)

        assert isinstance(exchanger, _RecordingExchanger)
        assert exchanger.realm == "corp"

    @pytest.mark.parametrize("name", ["rfc8693", "entra_obo", "id_jag", "RFC8693"])
    def test_a_name_reserved_for_a_later_release_fails_loudly(self, name):
        with pytest.raises(AKConfigError, match=f"identity.credentials.exchangers\\[\\].type: {name.lower()} is not shipped yet; use a dotted path"):
            TokenExchangerFactory.create(_ExchangerConfig(audience=AUDIENCE, type=name), inbound_ttl=300)

    def test_an_unknown_short_name_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="unknown token exchanger type 'oauth'"):
            TokenExchangerFactory.create(_ExchangerConfig(audience=AUDIENCE, type="oauth"), inbound_ttl=300)

    def test_every_exchanger_is_built_by_its_audience(self):
        config = _CredentialsConfig(exchangers=[{"audience": AUDIENCE}, {"audience": "https://api.crm.example"}])

        assert sorted(TokenExchangerFactory.create_all(config)) == [AUDIENCE, "https://api.crm.example"]

    def test_two_exchangers_for_one_audience_are_a_configuration_error(self):
        config = _CredentialsConfig(exchangers=[{"audience": AUDIENCE}, {"audience": AUDIENCE}])

        with pytest.raises(AKConfigError, match=f"two exchangers for audience '{AUDIENCE}'"):
            TokenExchangerFactory.create_all(config)


# --- iteration 25: retention ------------------------------------------------------------------------


def _alice(**claims) -> Principal:
    return Principal(subject="alice", provider="oidc", namespace="https://issuer.example", claims=claims)


class TestCredentialManager:
    def test_without_a_credentials_block_there_is_none(self, monkeypatch):
        from agentkernel.core.config import AKConfig

        monkeypatch.setattr(AKConfig.get(), "identity", None)
        CredentialManager.reset()

        assert CredentialManager.get() is None

    def test_it_is_built_once_for_the_process(self, credentials):
        first = credentials()

        assert CredentialManager.get() is first
        CredentialManager.reset()
        assert CredentialManager.get() is not first

    def test_a_bad_exchanger_fails_when_it_is_built(self, credentials):
        with pytest.raises(AKConfigError, match="not shipped yet"):
            credentials(exchangers=[{"audience": AUDIENCE, "type": "entra_obo"}])

    @pytest.mark.asyncio
    async def test_a_retained_credential_is_kept_under_a_fresh_reference(self, credentials):
        manager = credentials()

        retained = await manager.retain(_alice(), TOKEN.decode())

        assert retained.credential_ref and len(retained.credential_ref) == 32
        assert manager.store.get(retained.credential_ref) == TOKEN
        assert (await manager.retain(_alice(), TOKEN.decode())).credential_ref != retained.credential_ref

    @pytest.mark.asyncio
    async def test_the_principal_carries_the_reference_never_the_credential(self, credentials):
        retained = await credentials().retain(_alice(), TOKEN.decode())

        assert TOKEN.decode() not in retained.model_dump_json()

    @pytest.mark.asyncio
    async def test_it_is_kept_for_the_inbound_ttl_at_most(self, credentials, monkeypatch):
        manager = credentials(inbound_ttl=120)
        kept = []
        monkeypatch.setattr(manager.store, "put", lambda key, value, expires_at: kept.append(expires_at))

        await manager.retain(_alice(exp=int(time.time()) + 3600), "token")
        await manager.retain(_alice(), "token")
        soon = int(time.time()) + 30
        await manager.retain(_alice(exp=soon), "token")

        assert [round(at - time.time()) for at in kept[:2]] == [120, 120]
        assert kept[2] == soon

    @pytest.mark.asyncio
    async def test_a_token_that_has_already_expired_is_not_kept(self, credentials, caplog):
        manager = credentials()

        with caplog.at_level(logging.ERROR, logger="ak.identity.credential.manager"):
            retained = await manager.retain(_alice(exp=int(time.time()) - 5), "token")

        assert retained.credential_ref is None
        assert [r for r in caplog.records if r.name == "ak.identity.credential.manager"] == []  # nothing to keep is no failure

    @pytest.mark.asyncio
    async def test_the_anonymous_principal_keeps_nothing(self, credentials):
        assert (await credentials().retain(Principal.anonymous(), "token")).credential_ref is None

    @pytest.mark.asyncio
    async def test_a_connection_keeps_its_credential_as_long_as_the_token_lasts(self, credentials, monkeypatch):
        manager = credentials(inbound_ttl=120)
        kept = []
        monkeypatch.setattr(manager.store, "put", lambda key, value, expires_at: kept.append((key, expires_at)))
        exp = int(time.time()) + 3600

        retained = await manager.retain(_alice(exp=exp), "token", connection=True)
        await manager.retain(_alice(), "token", connection=True)

        assert retained.credential_ref.startswith("conn:")
        assert kept[0][1] == exp  # not capped: inbound_ttl bounds a credential outliving its request
        assert round(kept[1][1] - time.time()) == 120  # no exp: the inbound ttl

    @pytest.mark.asyncio
    async def test_release_deletes_a_run_credential_and_leaves_a_connection_one(self, credentials):
        manager = credentials()
        run = await manager.retain(_alice(), "run-token")
        connection = await manager.retain(_alice(), "connection-token", connection=True)

        manager.release(run)
        manager.release(connection)

        assert manager.store.get(run.credential_ref) is None
        assert manager.store.get(connection.credential_ref) == b"connection-token"

    @pytest.mark.asyncio
    async def test_forget_deletes_a_connection_credential_and_leaves_a_run_one(self, credentials):
        manager = credentials()
        run = await manager.retain(_alice(), "run-token")
        connection = await manager.retain(_alice(), "connection-token", connection=True)

        manager.forget(connection)
        manager.forget(run)

        assert manager.store.get(connection.credential_ref) is None
        assert manager.store.get(run.credential_ref) == b"run-token"

    def test_a_principal_without_a_reference_releases_nothing(self, credentials):
        manager = credentials()

        manager.release(_alice())
        manager.release(None)
        manager.forget(None)

    @pytest.mark.asyncio
    async def test_a_store_that_fails_on_release_is_logged_not_raised(self, credentials, monkeypatch, caplog):
        manager = credentials()
        retained = await manager.retain(_alice(), "run-token")

        def unreachable(key):
            # A client's error can quote its connection URL, password and all, or the key it was given.
            raise ConnectionError(f"redis://:hunter2@cache:6379 refused DEL {key}")

        monkeypatch.setattr(manager.store, "delete", unreachable)
        with caplog.at_level(logging.WARNING, logger="ak.identity.credential.manager"):
            manager.release(retained)

        assert "could not be deleted" in caplog.text and "ConnectionError" in caplog.text
        assert "hunter2" not in caplog.text and retained.credential_ref not in caplog.text

    @pytest.mark.asyncio
    async def test_a_store_that_fails_on_retain_leaves_the_run_without_a_credential(self, credentials, monkeypatch, caplog):
        manager = credentials()

        def unreachable(key, value, expires_at):
            raise ConnectionError("the store is down")

        monkeypatch.setattr(manager.store, "put", unreachable)
        with caplog.at_level(logging.ERROR, logger="ak.identity.credential.manager"):
            retained = await manager.retain(_alice(), "a-very-secret-token")

        assert retained.credential_ref is None
        assert "could not be kept" in caplog.text and "a-very-secret-token" not in caplog.text


# --- iteration 25: the broker -----------------------------------------------------------------------


class TestCredentialBroker:
    @pytest.fixture
    def manager(self, credentials):
        return credentials(exchangers=[{"audience": AUDIENCE, "type": f"{__name__}._RecordingExchanger", "scopes": ["invoices.read"]}])

    @pytest.fixture
    def exchanger(self, manager) -> _RecordingExchanger:
        return manager.exchangers[AUDIENCE]

    @pytest_asyncio.fixture
    async def principal(self, manager) -> Principal:
        retained = await manager.retain(_alice(), "inbound-token")
        return retained.with_actor(Principal(kind="agent", subject="billing", provider="agentkernel"))

    @pytest.mark.asyncio
    async def test_a_token_is_exchanged_from_the_runs_inbound_credential(self, manager, exchanger, principal):
        token = await manager.broker(principal, "billing").token_for(AUDIENCE)

        assert token == "issued-1"
        assert exchanger.calls == [("inbound-token", AUDIENCE, ["invoices.read"], principal.actor)]

    @pytest.mark.asyncio
    async def test_the_scopes_a_tool_names_replace_the_default(self, manager, exchanger, principal):
        await manager.broker(principal, "billing").token_for(AUDIENCE, ["invoices.write"])

        assert exchanger.calls[0][2] == ["invoices.write"]

    @pytest.mark.asyncio
    async def test_an_issued_token_is_reused_until_it_nears_its_expiry(self, manager, exchanger, principal):
        broker = manager.broker(principal, "billing")

        first, second = await broker.token_for(AUDIENCE), await broker.token_for(AUDIENCE)

        assert first == second == "issued-1"
        assert len(exchanger.calls) == 1

    @pytest.mark.asyncio
    async def test_a_token_within_30_seconds_of_expiring_is_exchanged_again(self, manager, exchanger, principal):
        exchanger.lifetime = 20.0
        broker = manager.broker(principal, "billing")

        await broker.token_for(AUDIENCE)
        await broker.token_for(AUDIENCE)

        assert len(exchanger.calls) == 2

    @pytest.mark.asyncio
    async def test_a_cached_token_is_cached_per_principal_agent_audience_and_scopes(self, manager, exchanger, principal):
        bob = (await manager.retain(Principal(subject="bob", provider="oidc", namespace="https://issuer.example"), "bob-token")).with_actor(
            principal.actor
        )

        await manager.broker(principal, "billing").token_for(AUDIENCE, ["a", "b"])
        await manager.broker(principal, "billing").token_for(AUDIENCE, ["b", "a"])  # the same scopes, in another order
        await manager.broker(principal, "support").token_for(AUDIENCE, ["a", "b"])
        await manager.broker(principal, "billing").token_for(AUDIENCE, ["a"])
        await manager.broker(bob, "billing").token_for(AUDIENCE, ["a", "b"])

        assert len(exchanger.calls) == 4

    @pytest.mark.asyncio
    async def test_the_cache_key_names_no_one(self, manager, principal):
        key = manager.broker(principal, "billing")._cache_key(AUDIENCE, ["a"], b"inbound-token")

        assert key.startswith("cred:issued:") and "alice" not in key and AUDIENCE not in key and "inbound-token" not in key

    @pytest.mark.asyncio
    async def test_a_token_is_never_served_once_the_runs_own_credential_is_gone(self, manager, exchanger, principal):
        # A redelivered message keeps its reference, but the first attempt's release deleted the credential.
        broker = manager.broker(principal, "billing")
        await broker.token_for(AUDIENCE)

        manager.release(principal)

        with pytest.raises(CredentialError, match="no inbound credential for this run"):
            await broker.token_for(AUDIENCE)

    @pytest.mark.asyncio
    async def test_a_different_inbound_token_of_the_same_user_is_exchanged_afresh(self, manager, exchanger, principal):
        # Two tokens of one user can carry different claims: one's cached token must not carry its authority to the other.
        await manager.broker(principal, "billing").token_for(AUDIENCE)
        narrower = (await manager.retain(_alice(), "narrower-token")).with_actor(principal.actor)

        await manager.broker(narrower, "billing").token_for(AUDIENCE)

        assert [call[0] for call in exchanger.calls] == ["inbound-token", "narrower-token"]

    @pytest.mark.asyncio
    async def test_an_exchanger_that_is_not_cacheable_never_reads_the_cache(self, manager, exchanger, principal, monkeypatch):
        # A shared store can still hold what this audience's earlier, cacheable exchanger issued (a deploy that
        # moved it to passthrough); that token must not be served.
        broker = manager.broker(principal, "billing")
        await broker.token_for(AUDIENCE)
        monkeypatch.setattr(type(exchanger), "cacheable", False)

        assert await broker.token_for(AUDIENCE) == "issued-2"

    @pytest.mark.asyncio
    async def test_a_run_without_an_inbound_credential_gets_none(self, manager, principal):
        # A run started with no credential of its own (a scheduled occurrence) does not borrow an earlier run's.
        await manager.broker(principal, "billing").token_for(AUDIENCE)

        with pytest.raises(CredentialError, match="no inbound credential for this run"):
            await manager.broker(principal.with_credential_ref(None), "billing").token_for(AUDIENCE)

    @pytest.mark.asyncio
    async def test_an_inbound_credential_that_is_gone_is_an_error(self, manager, principal):
        manager.release(principal)

        with pytest.raises(CredentialError, match="no inbound credential for this run"):
            await manager.broker(principal, "billing").token_for(AUDIENCE)

    @pytest.mark.asyncio
    async def test_an_audience_with_no_exchanger_is_an_error(self, manager, principal):
        with pytest.raises(CredentialError, match="no exchanger configured for audience 'https://api.crm.example'"):
            await manager.broker(principal, "billing").token_for("https://api.crm.example")

    @pytest.mark.asyncio
    async def test_a_failed_exchange_is_a_credential_error_that_quotes_no_token(self, manager, exchanger, principal):
        exchanger.failure = RuntimeError("the token endpoint answered 500 for inbound-token")

        with pytest.raises(CredentialError, match="exchange for audience") as failed:
            await manager.broker(principal, "billing").token_for(AUDIENCE)

        assert "inbound-token" not in str(failed.value)

    @pytest.mark.asyncio
    async def test_a_store_that_cannot_be_reached_is_a_credential_error(self, manager, principal, monkeypatch):
        def unreachable(key):
            raise ConnectionError("the store is down")

        monkeypatch.setattr(manager.store, "get", unreachable)

        with pytest.raises(CredentialError, match="the credential store could not be reached: ConnectionError"):
            await manager.broker(principal, "billing").token_for(AUDIENCE)

    @pytest.mark.asyncio
    async def test_without_a_store_every_request_says_credentials_are_not_configured(self, principal):
        with pytest.raises(CredentialError, match="identity.credentials is not configured"):
            await CredentialBroker(principal, None, {}, "billing").token_for(AUDIENCE)


# --- iteration 25: what a tool reads ----------------------------------------------------------------


class _TokenAsker(Runner):
    """Asks ToolContext.credentials for a token while the run is in progress, as a tool would."""

    def __init__(self):
        super().__init__("token-asker")
        self.answers: list = []
        self.failure: Exception | None = None

    async def _ask(self, agent, session, requests):
        context = ToolContext(Runtime.current(), agent, session, requests).set()
        try:
            self.answers.append(await ToolContext.get().credentials.token_for(AUDIENCE))
        except CredentialError as error:
            self.answers.append(error)
        finally:
            context.reset()
        if self.failure is not None:
            raise self.failure

    async def run(self, agent, session, requests):
        await self._ask(agent, session, requests)
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        await self._ask(agent, session, requests)
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="ok")
        yield MessageEnd(message_id="m1")


class _Billing(Agent):
    def __init__(self, runner):
        super().__init__("billing", runner)

    def get_description(self):
        return ""

    def attach_tool(self, tool):
        pass

    def override_system_prompt(self, prompt):
        pass


class TestWhatAToolReads:
    @pytest.mark.asyncio
    async def test_without_a_credentials_block_the_broker_says_so_and_reading_it_costs_nothing(self, monkeypatch):
        from agentkernel.core.config import AKConfig

        monkeypatch.setattr(AKConfig.get(), "identity", None)
        CredentialManager.reset()
        runner = _TokenAsker()
        with Runtime(InMemorySessionStore()) as runtime:
            await runtime.run(_Billing(runner), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=_alice())

        assert isinstance(runner.answers[0], CredentialError) and "not configured" in str(runner.answers[0])

    @pytest.mark.asyncio
    async def test_a_tool_gets_a_token_from_the_inbound_credential_of_its_run(self, credentials):
        manager = credentials(exchangers=[{"audience": AUDIENCE}])
        inbound = _jwt(sub="alice", exp=int(time.time()) + 120)
        principal = await manager.retain(_alice(), inbound)
        runner = _TokenAsker()
        with Runtime(InMemorySessionStore()) as runtime:
            await runtime.run(_Billing(runner), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal)

        assert runner.answers == [inbound]

    def test_a_credentials_block_that_cannot_be_built_is_reported_when_used_not_when_read(self, credentials, monkeypatch):
        credentials()
        CredentialManager.reset()

        def broken(cls):
            raise AKConfigError("identity.credentials.encryption_key: secret 'AK_CREDENTIAL_KEY' not found")

        monkeypatch.setattr(CredentialManager, "get", classmethod(broken))

        broker = CredentialBroker.for_run(_alice(), "billing")

        with pytest.raises(CredentialError, match="credentials are unavailable: AKConfigError"):
            asyncio.run(broker.token_for(AUDIENCE))


# --- iteration 25: the credential ends with its run -------------------------------------------------


class _Answering(Runner):
    """Answers, or fails, without asking for anything."""

    def __init__(self, failure: Exception | None = None):
        super().__init__("answering")
        self.failure = failure

    async def run(self, agent, session, requests):
        if self.failure is not None:
            raise self.failure
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="ok")
        yield MessageEnd(message_id="m1")


class TestTheDirectPath:
    @pytest.mark.asyncio
    async def test_the_credential_is_deleted_when_the_run_ends(self, credentials):
        manager = credentials()
        principal = await manager.retain(_alice(), "inbound-token")
        with Runtime(InMemorySessionStore()) as runtime:
            await runtime.run(_Billing(_Answering()), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal)

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_also_when_the_run_fails(self, credentials):
        manager = credentials()
        principal = await manager.retain(_alice(), "inbound-token")
        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(RuntimeError):
                await runtime.run(
                    _Billing(_Answering(RuntimeError("down"))), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal
                )

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_also_when_a_streamed_run_ends(self, credentials):
        manager = credentials()
        principal = await manager.retain(_alice(), "inbound-token")
        with Runtime(InMemorySessionStore()) as runtime:
            async for _ in runtime.stream(_Billing(_Answering()), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal):
                pass

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_also_when_the_access_gate_refuses_the_run(self, credentials, authorization):
        manager = credentials()
        authorization(grants=[])
        principal = await manager.retain(_alice(), "inbound-token")
        with Runtime(InMemorySessionStore()) as runtime:
            with pytest.raises(LookupError):
                await runtime.run(_Billing(_Answering()), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal)

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_a_connections_credential_outlives_the_run(self, credentials):
        manager = credentials()
        principal = await manager.retain(_alice(), "connection-token", connection=True)
        with Runtime(InMemorySessionStore()) as runtime:
            await runtime.run(_Billing(_Answering()), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=principal)

        assert manager.store.get(principal.credential_ref) == b"connection-token"


class _ChatService:
    """Stands in for the runner's ChatService: records the body it is handed and answers, or fails."""

    def __init__(self, failure: Exception | None = None):
        self.bodies: list = []
        self.failure = failure

    def process_chat_request(self, req, requests=None):
        self.bodies.append(req)
        if self.failure is not None:
            raise self.failure
        return 200, {"result": "ok", "session_id": req.session_id}


class TestTheQueuedPath:
    @pytest.fixture
    def transport(self):
        from agentkernel.pipeline.transport.in_memory import InMemoryTransport

        InMemoryTransport.reset()
        yield InMemoryTransport()
        InMemoryTransport.reset()

    @staticmethod
    def _queued(transport, principal: Principal):
        from agentkernel.core.model import BaseRunRequest
        from agentkernel.pipeline.envelope import QueueName
        from agentkernel.pipeline.producer import RequestProducer

        RequestProducer(transport).enqueue(BaseRunRequest(prompt="hi", session_id="s1", principal=principal), request_id="r1", group_id="s1")
        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(batch_size=1, wait_seconds=1)
        consumer.ack(message)
        return message

    @pytest.mark.asyncio
    async def test_the_queue_carries_the_reference_never_the_credential(self, credentials, transport):
        principal = await credentials().retain(_alice(), "inbound-token")

        message = self._queued(transport, principal)

        assert "inbound-token" not in message.body
        assert json.loads(message.body)["principal"]["credential_ref"] == principal.credential_ref

    @pytest.mark.asyncio
    async def test_the_runner_deletes_the_credential_when_it_is_done_with_the_message(self, credentials, transport):
        from agentkernel.pipeline.agent_runner import AgentRunner

        manager = credentials()
        principal = await manager.retain(_alice(), "inbound-token")
        chat = _ChatService()

        AgentRunner(transport=transport, chat_service=chat).process(self._queued(transport, principal))

        assert chat.bodies[0].principal.credential_ref == principal.credential_ref
        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_also_when_the_run_raises_before_it_reaches_the_agent(self, credentials, transport):
        from agentkernel.pipeline.agent_runner import AgentRunner

        manager = credentials()
        principal = await manager.retain(_alice(), "inbound-token")

        with pytest.raises(RuntimeError):
            AgentRunner(transport=transport, chat_service=_ChatService(RuntimeError("down"))).process(self._queued(transport, principal))

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_a_connections_credential_outlives_the_message(self, credentials, transport):
        from agentkernel.pipeline.agent_runner import AgentRunner

        manager = credentials()
        principal = await manager.retain(_alice(), "connection-token", connection=True)

        AgentRunner(transport=transport, chat_service=_ChatService()).process(self._queued(transport, principal))

        assert manager.store.get(principal.credential_ref) == b"connection-token"


class TestTheStoreAcrossProcesses:
    """On a broker transport the process that keeps a credential is not the one that reads it."""

    @staticmethod
    def _config(store: dict):
        from types import SimpleNamespace

        identity = SimpleNamespace(credentials=_CredentialsConfig(store=store, encryption_key=KEY_NAME if store["type"] != "in_memory" else None))
        return SimpleNamespace(identity=identity)

    def test_an_in_memory_store_on_a_broker_is_refused(self):
        from agentkernel.pipeline.agent_runner import AgentRunner

        with pytest.raises(AKConfigError, match="identity.credentials.store.type in_memory .* sqs transport"):
            AgentRunner._validate_credential_store("sqs", self._config({"type": "in_memory"}))

    def test_a_shared_store_on_a_broker_and_any_store_in_one_process_are_accepted(self):
        from types import SimpleNamespace

        from agentkernel.pipeline.agent_runner import AgentRunner

        AgentRunner._validate_credential_store("sqs", self._config({"type": "redis", "redis": {}}))
        AgentRunner._validate_credential_store("in_memory", self._config({"type": "in_memory"}))
        AgentRunner._validate_credential_store("sqs", SimpleNamespace(identity=None))

    def test_the_agent_runner_refuses_it_before_it_starts(self, credentials, monkeypatch):
        from agentkernel.pipeline.agent_runner import AgentRunner
        from agentkernel.pipeline.transport.base import QueueTransportFactory

        credentials()
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda *args, **kwargs: "sqs"))
        monkeypatch.setattr(AgentRunner, "start", lambda self, exit_on_shutdown=True: pytest.fail("the runner started"))

        with pytest.raises(AKConfigError, match="identity.credentials.store.type in_memory"):
            AgentRunner.run()

    def test_the_io_handler_checks_it_too(self, monkeypatch):
        from agentkernel.pipeline.io_handler import IOHandler

        config = self._config({"type": "in_memory"})
        checked = []
        monkeypatch.setattr("agentkernel.pipeline.agent_runner.AgentRunner._validate_credential_store", staticmethod(lambda t, c: checked.append(t)))
        try:
            IOHandler._validate_topology("sqs", config)
        except Exception:
            pass  # the stand-in configuration lacks what the other checks read; only the credential check matters here

        assert checked == ["sqs"]


class TestADirectRequestAnsweredWithoutARun:
    """The direct REST route runs the agent in-process, so once it has answered nothing will use the credential: a
    request refused before its run (an unknown agent) releases it, as does one whose stream never starts (#603)."""

    @staticmethod
    def _client(kept: Principal):
        from fastapi import Depends, FastAPI, Request
        from fastapi.testclient import TestClient

        from agentkernel.api.handler import AgentRESTRequestHandler

        async def _identity(request: Request) -> None:
            request.state.principal = kept

        app = FastAPI()
        app.include_router(AgentRESTRequestHandler().get_router(), dependencies=[Depends(_identity)])
        return TestClient(app)

    @pytest.mark.parametrize("message_type", ["complete", "delta"])
    @pytest.mark.parametrize("route", ["/api/v1/chat", "/api/v1/chat-multipart"])
    def test_a_request_for_an_unknown_agent_releases_its_credential(self, credential_manager, monkeypatch, message_type, route):
        from agentkernel.core.config import AKConfig, _ExecutionConfig

        monkeypatch.setattr(AKConfig.get(), "execution", _ExecutionConfig(message_type=message_type))
        kept = asyncio.run(credential_manager.retain(_alice(), "run-token"))
        fields = {"prompt": "hello", "session_id": "s1", "agent": "nobody"}

        with Runtime(InMemorySessionStore()):
            client = self._client(kept)
            response = client.post(route, json=fields) if route.endswith("chat") else client.post(route, data=fields)

        assert response.status_code == 404
        assert credential_manager.store.get(kept.credential_ref) is None


class TestNoTokenLeaks:
    def test_no_log_record_carries_the_token_from_request_to_release(self, credentials, caplog):
        from fastapi import Depends, FastAPI, Request
        from fastapi.testclient import TestClient

        from agentkernel.identity.provider.base import IdentityProvider
        from agentkernel.identity.provider.request import RequestAuthenticator

        token = _jwt(sub="alice", exp=int(time.time()) + 120, marker="ak-leak-check")

        class _Accepting(IdentityProvider):
            name = "accepting"

            async def authenticate(self, credential, context=None):
                return Principal(subject="alice", provider=self.name, namespace="accepting", claims={"exp": int(time.time()) + 120})

        manager = credentials(exchangers=[{"audience": AUDIENCE}])
        runner = _TokenAsker()
        app = FastAPI()

        async def chat(request: Request):
            with Runtime(InMemorySessionStore()) as runtime:
                await runtime.run(_Billing(runner), runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")], principal=request.state.principal)
            return {}

        app.add_api_route("/chat", chat, methods=["POST"], dependencies=[Depends(RequestAuthenticator(_Accepting(), manager).dependency())])
        with caplog.at_level(logging.DEBUG):
            TestClient(app).post("/chat", headers={"Authorization": f"Bearer {token}"})

        assert runner.answers == [token]  # the tool had it
        assert token not in caplog.text
        assert InMemoryCredentialStore._entries == {}  # gone with the run: passthrough leaves no cached copy behind


# --- iteration 25b: a connection's credential lasts while the connection does -----------------------


class TestRenewingAConnectionsCredential:
    @pytest.fixture
    def recorded(self, credentials, monkeypatch):
        """The manager, and the (key, expires_at) of every touch its store is asked for."""
        manager = credentials(inbound_ttl=120)
        touches: list[tuple] = []
        touch = manager.store.touch

        def recording(key, expires_at):
            touches.append((key, expires_at))
            touch(key, expires_at)

        monkeypatch.setattr(manager.store, "touch", recording)
        return manager, touches

    @pytest.mark.asyncio
    async def test_a_connection_credential_without_an_expiry_is_kept_another_inbound_ttl(self, recorded):
        manager, touches = recorded
        principal = await manager.retain(_alice(), "connection-token", connection=True)
        touches.clear()

        manager.renew(principal)

        [(key, expires_at)] = touches
        assert key == principal.credential_ref and round(expires_at - time.time()) == 120
        assert manager.store.get(key) == b"connection-token"

    @pytest.mark.asyncio
    async def test_one_whose_token_has_an_expiry_is_never_kept_past_it(self, recorded):
        manager, touches = recorded
        principal = await manager.retain(_alice(exp=int(time.time()) + 3600), "connection-token", connection=True)
        touches.clear()

        manager.renew(principal)

        assert touches == []

    @pytest.mark.asyncio
    async def test_a_runs_credential_is_not_renewed(self, recorded):
        manager, touches = recorded
        principal = await manager.retain(_alice(), "run-token")
        touches.clear()

        manager.renew(principal)

        assert touches == []

    @pytest.mark.asyncio
    async def test_a_credential_that_is_gone_is_not_brought_back(self, recorded):
        # Renewal asks the store to extend a live entry, so a disconnect or an expiry between two frames is final.
        manager, _ = recorded
        principal = await manager.retain(_alice(), "connection-token", connection=True)
        manager.store.delete(principal.credential_ref)

        manager.renew(principal)

        assert manager.store.get(principal.credential_ref) is None

    @pytest.mark.asyncio
    async def test_a_store_that_fails_on_renewal_is_logged_not_raised(self, recorded, monkeypatch, caplog):
        manager, _ = recorded
        principal = await manager.retain(_alice(), "connection-token", connection=True)

        def unreachable(key):
            raise ConnectionError("the store is down")

        monkeypatch.setattr(manager.store, "touch", lambda key, expires_at: unreachable(key))
        with caplog.at_level(logging.WARNING, logger="ak.identity.credential.manager"):
            manager.renew(principal)

        assert "could not be renewed" in caplog.text

    @pytest.mark.asyncio
    async def test_the_classmethods_reach_the_process_manager_and_do_nothing_without_one(self, credentials, monkeypatch):
        from agentkernel.core.config import AKConfig

        manager = credentials()
        principal = await manager.retain(_alice(), "connection-token", connection=True)

        CredentialManager.forget_for(principal)
        assert manager.store.get(principal.credential_ref) is None

        monkeypatch.setattr(AKConfig.get(), "identity", None)
        CredentialManager.reset()
        CredentialManager.renew_for(principal)
        CredentialManager.forget_for(principal)
        CredentialManager.renew_for(None)


class TestASharedStoreIsRequired:
    @staticmethod
    def _config(store_type: str):
        from types import SimpleNamespace

        store = {"type": store_type, **({"redis": {}} if store_type == "redis" else {})}
        return SimpleNamespace(identity=SimpleNamespace(credentials=_CredentialsConfig(store=store)))

    def test_an_in_memory_store_is_refused_where_one_process_keeps_and_another_reads(self):
        with pytest.raises(AKConfigError, match="identity.credentials.store.type in_memory cannot work on AWS Lambda"):
            CredentialManager.require_shared_store(self._config("in_memory"), "on AWS Lambda")

    @pytest.mark.parametrize(
        "store_type",
        [
            pytest.param("agentkernel.identity.credential.in_memory.InMemoryCredentialStore", id="the in-memory store by its path"),
            pytest.param(f"{__name__}._VaultCredentialStore", id="a store of your own that is not shared"),
        ],
    )
    def test_a_store_named_by_a_dotted_path_is_refused_when_it_is_not_shared(self, store_type):
        # What decides is the class's `shared`, so naming the in-memory store by its path changes nothing.
        with pytest.raises(AKConfigError, match="cannot work on AWS Lambda"):
            CredentialManager.require_shared_store(self._config(store_type), "on AWS Lambda")

    def test_a_store_of_your_own_that_is_shared_is_accepted(self):
        CredentialManager.require_shared_store(self._config(f"{__name__}._SharedVaultCredentialStore"), "on AWS Lambda")

    def test_a_shared_store_or_no_credentials_block_is_accepted(self):
        from types import SimpleNamespace

        CredentialManager.require_shared_store(self._config("redis"), "on AWS Lambda")
        CredentialManager.require_shared_store(SimpleNamespace(identity=None), "on AWS Lambda")
        CredentialManager.require_shared_store(SimpleNamespace(identity=SimpleNamespace(credentials=None)), "on AWS Lambda")
