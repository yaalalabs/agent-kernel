"""Thread read routes (``ThreadRESTRequestHandler``) behind the identity dependency (#603).

The routes serve authenticated callers only: the handler refuses to build without an identity
block, a request nothing authenticated is a 401, a listing is the caller's own threads, and a
thread read enforces ownership on the principal's subject.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentkernel.api.handler import AuthorisedRESTRequestHandler
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory, RequestAuthenticator
from agentkernel.integration.thread import ConversationThreadManager, ThreadNamingStrategy, ThreadRESTRequestHandler
from agentkernel.integration.thread.store.in_memory import InMemoryThreadStore

MEDIA_TYPE = "application/a2ui+json"
TOKENS = {"u1-token": "u1", "u2-token": "u2"}
AUTH = {"Authorization": "Bearer u1-token"}


class EchoNaming(ThreadNamingStrategy):
    """Offline test strategy: the first prompt becomes the name, no LLM call."""

    def generate_name(self, prompt: str) -> str:
        return (prompt or "").strip()


class _Provider(IdentityProvider):
    """One token per test user, so every status below has a live path."""

    name = "test"

    async def authenticate(self, credential, context=None):
        subject = TOKENS.get(credential)
        if subject is None:
            raise AuthenticationError("unknown token")
        return Principal(subject=subject, provider=self.name, namespace="test")


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    """Stand the configured identity provider in: the handler requires one at construction."""
    provider = _Provider()
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))
    return provider


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test."""
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    ConversationThreadManager.set_naming_strategy(EchoNaming())
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


def _client() -> TestClient:
    """The routes behind the identity dependency, as ``RESTAPI`` mounts them."""
    app = FastAPI()
    app.include_router(ThreadRESTRequestHandler().get_router(), dependencies=[Depends(RequestAuthenticator(_Provider()).dependency())])
    return TestClient(app)


class TestConstruction:
    def test_refuses_to_build_without_an_identity_block(self, monkeypatch):
        """The routes enforce ownership on the caller, so with nobody able to authenticate they are a configuration error."""
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))

        with pytest.raises(AKConfigError, match="ThreadRESTRequestHandler requires an identity block"):
            ThreadRESTRequestHandler()

    def test_is_an_authorised_handler(self):
        """The identity requirement and ``_resolve_user`` come from the shared base, not a copy of it."""
        assert issubclass(ThreadRESTRequestHandler, AuthorisedRESTRequestHandler)


class TestAuthentication:
    """The 401 variants: the handler's for an absent credential, the dependency's for a refused one."""

    def test_missing_header_401(self, thread_enabled):
        response = _client().get("/api/v1/threads")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"
        assert response.headers["www-authenticate"] == "Bearer"

    def test_the_thread_read_requires_a_caller_too(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")

        response = _client().get("/api/v1/threads/s1")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_bad_token_401(self, thread_enabled):
        response = _client().get("/api/v1/threads", headers={"Authorization": "Bearer bad-token"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Unauthorized"

    def test_non_bearer_scheme_401(self, thread_enabled):
        response = _client().get("/api/v1/threads", headers={"Authorization": "Basic u1-token"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authorization header"

    def test_empty_token_401(self, thread_enabled):
        response = _client().get("/api/v1/threads", headers={"Authorization": "Bearer "})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authorization header"

    def test_lowercase_bearer_scheme_accepted(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")

        response = _client().get("/api/v1/threads", headers={"Authorization": "bearer u1-token"})

        assert response.status_code == 200


class TestOwnership:
    def test_listing_is_the_callers_own_threads(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u2", first_prompt="b")

        response = _client().get("/api/v1/threads", headers=AUTH)

        assert response.status_code == 200
        threads = response.json()["threads"]
        assert [t["session_id"] for t in threads] == ["s1"]
        assert "messages" not in threads[0]

    def test_a_user_id_query_cannot_widen_the_listing(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u2", first_prompt="b")

        # The caller asks for u2's threads; the listing stays the caller's own.
        response = _client().get("/api/v1/threads", params={"user_id": "u2"}, headers=AUTH)

        assert response.status_code == 200
        assert [t["session_id"] for t in response.json()["threads"]] == ["s1"]

    def test_group_filter_applies_within_the_callers_threads(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", group_id="g1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u1", first_prompt="b")
        thread_enabled.get_or_create_thread("s3", "u2", group_id="g1", first_prompt="c")

        response = _client().get("/api/v1/threads", params={"group_id": "g1"}, headers=AUTH)

        assert response.status_code == 200
        assert [t["session_id"] for t in response.json()["threads"]] == ["s1"]

    def test_get_owned_thread_200(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")

        response = _client().get("/api/v1/threads/s1", headers=AUTH)

        assert response.status_code == 200

    def test_get_unowned_thread_403(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u2", first_prompt="a")

        response = _client().get("/api/v1/threads/s1", headers=AUTH)

        assert response.status_code == 403
        assert response.json()["detail"] == "Thread is not owned by the authorised user"

    def test_get_missing_thread_404(self, thread_enabled):
        assert _client().get("/api/v1/threads/missing", headers=AUTH).status_code == 404


class TestReads:
    def test_get_thread_with_messages(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.append_message("s1", "user", "hello")
        thread_enabled.append_message("s1", "assistant", "hi!")

        response = _client().get("/api/v1/threads/s1", headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "s1"
        assert [m["content"] for m in body["messages"]] == ["hello", "hi!"]

    def test_get_thread_carries_a_labelled_payload_as_an_object(self, thread_enabled):
        """The read route's half of #763, asserted where the route is tested.

        The unlabelled message is beside it on purpose: ``media_type`` is omitted rather than sent
        as ``null``, which is what keeps the key absent for anyone who never opted into A2UI.
        """
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.append_message("s1", "assistant", {"version": "v1.0"}, media_type=MEDIA_TYPE)
        thread_enabled.append_message("s1", "assistant", "plain words")

        messages = _client().get("/api/v1/threads/s1", headers=AUTH).json()["messages"]

        assert (messages[0]["content"], messages[0]["media_type"]) == ({"version": "v1.0"}, MEDIA_TYPE)
        assert messages[1]["content"] == "plain words"
        assert "media_type" not in messages[1]

    def test_get_thread_message_pagination(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        for i in range(5):
            thread_enabled.append_message("s1", "user", f"m{i}")

        client = _client()
        r1 = client.get("/api/v1/threads/s1", params={"limit": 2}, headers=AUTH)
        assert r1.status_code == 200
        b1 = r1.json()
        assert [m["content"] for m in b1["messages"]] == ["m0", "m1"]
        assert b1["next_cursor"] is not None

        r2 = client.get("/api/v1/threads/s1", params={"limit": 2, "cursor": b1["next_cursor"]}, headers=AUTH)
        b2 = r2.json()
        assert [m["content"] for m in b2["messages"]] == ["m2", "m3"]

    def test_get_thread_bad_cursor_400(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")

        response = _client().get("/api/v1/threads/s1", params={"cursor": "!!bad!!"}, headers=AUTH)

        assert response.status_code == 400

    def test_list_threads_pagination(self, thread_enabled):
        for i in range(3):
            thread_enabled.get_or_create_thread(f"s{i}", "u1", first_prompt="p")

        client = _client()
        r1 = client.get("/api/v1/threads", params={"limit": 2}, headers=AUTH)
        b1 = r1.json()
        assert len(b1["threads"]) == 2
        assert b1["next_cursor"] is not None

        r2 = client.get("/api/v1/threads", params={"limit": 2, "cursor": b1["next_cursor"]}, headers=AUTH)
        b2 = r2.json()
        assert len(b2["threads"]) == 1
        assert b2["next_cursor"] is None

    def test_routes_404_when_thread_support_disabled(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()

        response = _client().get("/api/v1/threads", headers=AUTH)

        assert response.status_code == 404
