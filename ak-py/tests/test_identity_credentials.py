"""The credentials capability (#603, spec section 5).

Iteration 24: the encrypted credential store. `CredentialCipher`, `CredentialStoreContract` run over the in-memory,
Redis, Valkey and DynamoDB backends (the redis-likes over a fake client at `store._driver._client`, DynamoDB over a
fake driver, the `test_schedule_store.py` pattern), and `CredentialStoreFactory`.
"""

import base64
import fnmatch
import logging
import math
import os
import sys
import time

import pytest
from boto3.dynamodb.types import Binary

from agentkernel.core.config import _CredentialsConfig
from agentkernel.core.util.driver.valkey import ValkeyDriver
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.credential.dynamodb import DynamoDBCredentialStore
from agentkernel.identity.credential.in_memory import InMemoryCredentialStore
from agentkernel.identity.credential.redis import RedisCredentialStore
from agentkernel.identity.credential.store import CredentialCipher, CredentialStore, CredentialStoreFactory
from agentkernel.identity.credential.testing import TOKEN, CredentialStoreContract
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

    def scan_iter(self, match: str, count: int | None = None):
        return [key for key in list(self.values) if fnmatch.fnmatch(key, match)]


class _FakeDynamoDBDriver:
    """Stand-in for DynamoDBDriver, one item per credential. Like DynamoDB it removes nothing when an item expires."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def put(self, item: dict) -> None:
        self.items[item["credential_key"]] = dict(item)

    def get(self, pk_value: str, sk_value=None) -> dict | None:
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

    def _remove(self, key):
        pass

    def _clear(self):
        pass


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

    def test_importing_the_package_loads_no_credential_store(self):
        import subprocess

        loaded = subprocess.run(
            [sys.executable, "-c", "import sys, agentkernel.identity; print([m for m in sys.modules if '.credential' in m])"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        assert loaded == "[]"
