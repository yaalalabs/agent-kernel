"""The credential store contract, the cipher every store encrypts with, and the factory that picks a backend (#603).

A store keeps one value per key until the value expires. The value is a credential, so a store never holds
it as it came: ``put`` encrypts with AES-GCM under the deployment's key, binding the store key as associated
data, and ``get`` decrypts. A backend sees only ciphertext and implements four small methods; encryption and
the refusal of an expired value live here, once.
"""

import base64
import binascii
import os
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ...secret import SecretManager, SecretNotFoundError
from ..errors import CredentialError

if TYPE_CHECKING:
    from ...core.config import _CredentialsConfig, _CredentialStoreConfig

_ENCRYPTION_KEY_FIELD = "identity.credentials.encryption_key"


class CredentialCipher:
    """AES-GCM over a 32-byte key: what a credential store encrypts with.

    A sealed value is a fresh 12-byte nonce followed by the ciphertext and its tag. The store key a value is
    kept under is the associated data, so a value copied under another key does not decrypt.
    """

    KEY_BYTES: ClassVar[int] = 32
    NONCE_BYTES: ClassVar[int] = 12
    _TAG_BYTES: ClassVar[int] = 16

    def __init__(self, key: bytes):
        """
        :param key: The 32-byte AES key.
        :raises ValueError: If the key is not 32 bytes.
        :raises ImportError: If the ``auth`` extra (cryptography) is not installed.
        """
        if len(key) != self.KEY_BYTES:
            raise ValueError(f"a credential key is {self.KEY_BYTES} bytes; got {len(key)}")
        with require_extra("auth", _ENCRYPTION_KEY_FIELD):
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aead = AESGCM(key)

    @classmethod
    def from_config(cls, config: "_CredentialsConfig") -> "CredentialCipher | None":
        """
        Builds the cipher from ``identity.credentials``: the secret named by ``encryption_key``, read through the
        secret capability and base64url-decoded.

        :param config: The ``identity.credentials`` block.
        :return: The cipher, or None when the block names no key.
        :raises AKConfigError: If the secret is missing, the name is not a secret key, or the value is not a
            base64url-encoded 32-byte key. The value never appears in the message.
        """
        name = config.encryption_key
        if name is None:
            return None
        try:
            encoded = SecretManager.current().get(name)
        except SecretNotFoundError as exc:
            raise AKConfigError(f"{_ENCRYPTION_KEY_FIELD}: secret '{name}' not found: {exc}") from exc
        except ValueError as exc:
            raise AKConfigError(f"{_ENCRYPTION_KEY_FIELD}: '{name}' is not a secret key: {exc}") from exc
        if encoded is None:  # not reached: with no default, a miss raises SecretNotFoundError
            raise AKConfigError(f"{_ENCRYPTION_KEY_FIELD}: secret '{name}' not found")
        try:
            key = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            # Not chained: the decoder's message can quote the value.
            raise AKConfigError(
                f"{_ENCRYPTION_KEY_FIELD}: the secret '{name}' is not base64url; it must hold a base64url-encoded {cls.KEY_BYTES}-byte key"
            ) from None
        if len(key) != cls.KEY_BYTES:
            raise AKConfigError(
                f"{_ENCRYPTION_KEY_FIELD}: the secret '{name}' decodes to {len(key)} bytes; it must be {cls.KEY_BYTES} "
                f'(for example: python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")'
            )
        return cls(key)

    def encrypt(self, plaintext: bytes, reference: str) -> bytes:
        """
        :param plaintext: The value to seal.
        :param reference: The store key the value is kept under, bound as associated data.
        :return: The nonce followed by the ciphertext and its tag.
        """
        nonce = os.urandom(self.NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext, reference.encode())

    def decrypt(self, sealed: bytes, reference: str) -> bytes:
        """
        :param sealed: What ``encrypt`` returned.
        :param reference: The store key the value was read from.
        :return: The plaintext.
        :raises CredentialError: If the value was sealed under another key or another reference, or was changed.
        """
        from cryptography.exceptions import InvalidTag

        failed = CredentialError(
            "a stored credential could not be decrypted: it was written under another encryption key or another " "reference, or it was changed"
        )
        if len(sealed) < self.NONCE_BYTES + self._TAG_BYTES:
            raise failed
        try:
            return self._aead.decrypt(sealed[: self.NONCE_BYTES], sealed[self.NONCE_BYTES :], reference.encode())
        except InvalidTag:
            raise failed from None


class CredentialStore(ABC):
    """Where credentials are kept between the surface that receives them and the run that uses them.

    ``put`` / ``get`` / ``delete`` / ``clear`` are the interface; a backend implements ``_write``, ``_read``,
    ``_remove`` and ``_clear`` over ciphertext. A store shared with other processes (``shared``, the default)
    refuses to be built without a cipher: credentials would otherwise sit in plaintext in a database.
    """

    shared: ClassVar[bool] = True
    """Whether what the store holds leaves this process. A shared store requires a cipher."""

    def __init__(self, cipher: CredentialCipher | None):
        """
        :param cipher: What values are encrypted with; None keeps them as they came (a store that is not shared only).
        :raises AKConfigError: If the store is shared and there is no cipher.
        """
        if cipher is None and self.shared:
            raise AKConfigError(
                f"{type(self).__name__} keeps credentials outside this process, so {_ENCRYPTION_KEY_FIELD} must name the "
                "secret holding the key they are encrypted with"
            )
        self._cipher = cipher

    @classmethod
    def from_config(cls, config: "_CredentialStoreConfig", cipher: CredentialCipher | None) -> "CredentialStore":
        """
        Builds a bring-your-own store (a dotted-path ``type``). Override it to read settings of your own from
        ``config.model_extra``; the default passes the cipher alone.

        :param config: The ``identity.credentials.store`` block.
        :param cipher: The cipher built from ``identity.credentials.encryption_key``, or None.
        """
        return cls(cipher)

    def put(self, key: str, value: bytes, expires_at: float) -> None:
        """
        Keeps a credential until ``expires_at``, replacing any under the same key.

        :param key: The reference the credential is kept under.
        :param value: The credential.
        :param expires_at: When it expires, in UNIX epoch seconds.
        :raises ValueError: If ``expires_at`` has passed.
        """
        if expires_at <= time.time():
            raise ValueError("the credential has already expired; nothing was stored")
        self._write(key, value if self._cipher is None else self._cipher.encrypt(value, key), expires_at)

    def get(self, key: str) -> bytes | None:
        """
        :param key: The reference the credential was kept under.
        :return: The credential, or None when there is none or it has expired.
        :raises CredentialError: If what is stored does not decrypt with this store's key.
        """
        held = self._read(key)
        if held is None:
            return None
        return held if self._cipher is None else self._cipher.decrypt(held, key)

    def delete(self, key: str) -> None:
        """
        Removes a credential; a key holding none is not an error.

        :param key: The reference the credential was kept under.
        """
        self._remove(key)

    def clear(self) -> None:
        """Removes every credential the store holds."""
        self._clear()

    @abstractmethod
    def _write(self, key: str, data: bytes, expires_at: float) -> None:
        """
        :param key: The reference.
        :param data: What to keep (ciphertext when the store has a cipher).
        :param expires_at: When it expires, in UNIX epoch seconds; in the future.
        """

    @abstractmethod
    def _read(self, key: str) -> bytes | None:
        """
        :param key: The reference.
        :return: What was kept, or None when nothing is or it has expired.
        """

    @abstractmethod
    def _remove(self, key: str) -> None:
        """:param key: The reference; one holding nothing is not an error."""

    @abstractmethod
    def _clear(self) -> None:
        """Removes everything the store holds."""


class CredentialStoreFactory:
    """Builds the credential store ``identity.credentials.store`` selects."""

    BUILTINS: ClassVar[tuple[str, ...]] = ("in_memory", "redis", "valkey", "dynamodb")

    @staticmethod
    def create(config: "_CredentialsConfig") -> CredentialStore:
        """
        ``store.type`` is a built-in short name (in_memory, redis, valkey, dynamodb), matched whatever its case, or a
        dotted path to a ``CredentialStore`` subclass, built through its ``from_config``.

        :param config: The ``identity.credentials`` block.
        :return: The store, not yet connected.
        :raises AKConfigError: If the type is unknown, a shared store has no connection block or no encryption key,
            or the key is unusable.
        :raises ImportError: If a store's client library is not installed, naming the extra that ships it.
        """
        cipher = CredentialCipher.from_config(config)
        store = config.store
        key = store.type.lower()
        if key == "in_memory":
            from .in_memory import InMemoryCredentialStore

            return InMemoryCredentialStore(cipher)
        if key == "redis":
            redis = CredentialStoreFactory._settings(store, "redis")
            with require_extra("redis", "identity.credentials.store.type: redis"):
                from .redis import RedisCredentialStore

            return RedisCredentialStore(url=redis.url, prefix=redis.prefix, cipher=cipher)
        if key == "valkey":
            valkey = CredentialStoreFactory._settings(store, "valkey")
            with require_extra("valkey", "identity.credentials.store.type: valkey"):
                from .valkey import ValkeyCredentialStore

            return ValkeyCredentialStore(url=valkey.url, prefix=valkey.prefix, cipher=cipher)
        if key == "dynamodb":
            dynamodb = CredentialStoreFactory._settings(store, "dynamodb")
            with require_extra("aws", "identity.credentials.store.type: dynamodb"):
                from .dynamodb import DynamoDBCredentialStore

            return DynamoDBCredentialStore(table_name=dynamodb.table_name, cipher=cipher)
        if "." not in store.type:
            raise AKConfigError(
                f"unknown credential store type '{store.type}'; expected one of {list(CredentialStoreFactory.BUILTINS)} "
                "or a dotted path to a CredentialStore subclass"
            )
        return resolve_dotted(store.type, base=CredentialStore).from_config(store, cipher)

    @staticmethod
    def _settings(store: "_CredentialStoreConfig", backend: str) -> Any:
        """
        :param store: The ``identity.credentials.store`` block.
        :param backend: The store type, which is also the name of its block.
        :return: The block.
        :raises AKConfigError: If the block is absent.
        """
        settings = getattr(store, backend)
        if settings is None:
            raise AKConfigError(f"identity.credentials.store.{backend} must be set when identity.credentials.store.type is '{backend}'")
        return settings
