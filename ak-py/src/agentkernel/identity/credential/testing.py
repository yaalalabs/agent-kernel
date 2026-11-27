"""Reusable conformance suites for credential store backends and token exchangers (#603).

Import from test code only: the module imports ``pytest`` and is kept out of the package exports.
"""

import os
import time
from collections.abc import Callable

import pytest

from ...core.model import Principal
from ..errors import CredentialError
from .exchange import IssuedToken, TokenExchanger
from .store import CredentialCipher, CredentialStore

# Shaped like a bearer token, and distinctive enough that finding it in a stored value means it was kept as it came.
TOKEN = b"eyJhbGciOiJSUzI1NiJ9.ak-contract-credential.c2lnbmF0dXJl"


class CredentialStoreContract:
    """What every credential store must do, over one backend shared by every store a test builds.

    Subclass it in a backend's tests and override ``make_store``: a function taking a ``CredentialCipher`` and
    returning a store over the same backend on every call, so a second store can read, or fail to read, what the
    first wrote. Deliberately not named ``Test*``: pytest collects it only through a subclass that supplies the
    fixture.

    Expiry is checked against the clock: the expired-entry case waits a fraction of a second, so a backend whose
    expiry is the server's (Redis) needs a test double that honours the expiry it is given.
    """

    @pytest.fixture
    def make_store(self) -> Callable[[CredentialCipher], CredentialStore]:
        raise NotImplementedError("override make_store in the backend's test class")

    @pytest.fixture
    def cipher(self) -> CredentialCipher:
        return CredentialCipher(os.urandom(CredentialCipher.KEY_BYTES))

    @pytest.fixture
    def store(self, make_store, cipher) -> CredentialStore:
        store = make_store(cipher)
        store.clear()
        yield store
        store.clear()

    @staticmethod
    def _later(seconds: float = 60.0) -> float:
        return time.time() + seconds

    def test_a_credential_reads_back_as_it_was_put(self, store):
        store.put("ref-1", TOKEN, self._later())

        assert store.get("ref-1") == TOKEN

    def test_an_unknown_key_reads_as_none(self, store):
        assert store.get("never-put") is None

    def test_a_second_put_replaces_the_first(self, store):
        store.put("ref-1", TOKEN, self._later())
        store.put("ref-1", b"rotated", self._later())

        assert store.get("ref-1") == b"rotated"

    def test_delete_removes_one_credential_and_leaves_the_others(self, store):
        store.put("ref-1", TOKEN, self._later())
        store.put("ref-2", b"other", self._later())

        store.delete("ref-1")

        assert (store.get("ref-1"), store.get("ref-2")) == (None, b"other")

    def test_deleting_an_unknown_key_is_not_an_error(self, store):
        store.delete("never-put")

    def test_clear_removes_every_credential(self, store):
        store.put("ref-1", TOKEN, self._later())
        store.put("ref-2", b"other", self._later())

        store.clear()

        assert (store.get("ref-1"), store.get("ref-2")) == (None, None)

    def test_an_expired_credential_reads_as_none(self, store):
        store.put("ref-1", TOKEN, self._later(0.2))
        time.sleep(0.35)

        assert store.get("ref-1") is None

    @pytest.mark.parametrize("seconds", [0.0, -30.0])
    def test_a_credential_that_has_already_expired_is_refused(self, store, seconds):
        with pytest.raises(ValueError, match="expired"):
            store.put("ref-1", TOKEN, self._later(seconds))

        assert store.get("ref-1") is None

    def test_what_the_backend_holds_is_not_the_credential(self, store):
        store.put("ref-1", TOKEN, self._later())

        held = store._read("ref-1")

        assert held is not None and TOKEN not in held

    def test_a_store_with_another_key_cannot_read_it(self, store, make_store):
        store.put("ref-1", TOKEN, self._later())
        other = make_store(CredentialCipher(os.urandom(CredentialCipher.KEY_BYTES)))

        with pytest.raises(CredentialError):
            other.get("ref-1")

    def test_a_credential_copied_under_another_key_cannot_be_read(self, store):
        # The key is the associated data, so a stored value cannot be replayed as another run's credential.
        store.put("ref-1", TOKEN, self._later())
        store._write("ref-2", store._read("ref-1"), self._later())

        with pytest.raises(CredentialError):
            store.get("ref-2")

    def test_touch_keeps_a_live_credential_longer(self, store):
        store.put("ref-1", TOKEN, self._later(0.3))

        store.touch("ref-1", self._later(60))
        time.sleep(0.45)

        assert store.get("ref-1") == TOKEN

    def test_touch_refuses_an_expiry_that_has_passed(self, store):
        store.put("ref-1", TOKEN, self._later())

        with pytest.raises(ValueError):
            store.touch("ref-1", time.time() - 1)

        assert store.get("ref-1") == TOKEN

    def test_touch_never_creates_a_credential(self, store):
        store.touch("never-put", self._later(60))

        assert store.get("never-put") is None

    def test_touch_never_brings_back_an_expired_credential(self, store):
        store.put("ref-1", TOKEN, self._later(0.2))
        time.sleep(0.35)

        store.touch("ref-1", self._later(60))

        assert store.get("ref-1") is None

    def test_touch_never_brings_back_a_deleted_credential(self, store):
        store.put("ref-1", TOKEN, self._later())
        store.delete("ref-1")

        store.touch("ref-1", self._later(60))

        assert store.get("ref-1") is None

    def test_another_store_over_the_same_backend_reads_it(self, store, make_store, cipher):
        store.put("ref-1", TOKEN, self._later())

        assert make_store(cipher).get("ref-1") == TOKEN


class TokenExchangerContract:
    """What every token exchanger must do. Subclass it and override ``exchanger`` and ``inbound``.

    Deliberately not named ``Test*``: pytest collects it only through a subclass that supplies the fixtures.
    """

    AUDIENCE = "https://api.contract.example"

    @pytest.fixture
    def exchanger(self) -> TokenExchanger:
        raise NotImplementedError("override exchanger in the exchanger's test class")

    @pytest.fixture
    def inbound(self) -> str:
        raise NotImplementedError("override inbound: a credential the exchanger accepts")

    @pytest.fixture
    def actor(self) -> Principal:
        return Principal(kind="agent", subject="billing", provider="agentkernel")

    @pytest.mark.asyncio
    async def test_an_exchange_issues_a_token(self, exchanger, inbound, actor):
        issued = await exchanger.exchange(inbound, self.AUDIENCE, ["read"], actor)

        assert isinstance(issued, IssuedToken)
        assert issued.access_token and issued.token_type

    @pytest.mark.asyncio
    async def test_the_issued_token_has_not_expired(self, exchanger, inbound, actor):
        issued = await exchanger.exchange(inbound, self.AUDIENCE, [], actor)

        assert issued.expires_at > time.time()

    @pytest.mark.asyncio
    async def test_an_exchange_without_an_actor_is_accepted(self, exchanger, inbound):
        assert (await exchanger.exchange(inbound, self.AUDIENCE, [], None)).access_token

    def test_the_issued_token_is_not_in_its_repr(self):
        issued = IssuedToken(access_token="secret-access-token", expires_at=time.time() + 60)

        assert "secret-access-token" not in repr(issued)
