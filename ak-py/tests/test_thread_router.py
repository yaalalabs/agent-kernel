from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.api.thread import ThreadRESTRequestHandler
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.thread import Authoriser, ConversationThreadManager
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore


@pytest.fixture
def thread_enabled():
    """Enable thread support with the in-memory store for the duration of a test."""
    AKConfig.get().thread = _ThreadStoreConfig(type="memory")
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()
    yield ConversationThreadManager.get()
    AKConfig.get().thread = None
    ConversationThreadManager.reset()
    InMemoryThreadStore._threads.clear()
    InMemoryThreadStore._messages.clear()


class StaticAuthoriser(Authoriser):
    """Test authoriser: token 'good-token' resolves to user 'u1', anything else is rejected."""

    def authorise(self, token: str) -> Optional[str]:
        return "u1" if token == "good-token" else None


def _client(authoriser: Optional[Authoriser] = None) -> TestClient:
    app = FastAPI()
    app.include_router(ThreadRESTRequestHandler(authoriser=authoriser).get_router())
    return TestClient(app)


class TestThreadRouterOpen:
    """Thread routes without an Authoriser (open access)."""

    def test_list_threads_by_user(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u2", first_prompt="b")

        response = _client().get("/api/v1/threads", params={"user_id": "u1"})
        assert response.status_code == 200
        threads = response.json()["threads"]
        assert [t["session_id"] for t in threads] == ["s1"]
        assert "messages" not in threads[0]

    def test_list_threads_by_group(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", group_id="g1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u1", first_prompt="b")

        response = _client().get("/api/v1/threads", params={"group_id": "g1"})
        assert response.status_code == 200
        assert [t["session_id"] for t in response.json()["threads"]] == ["s1"]

    def test_get_thread_with_messages(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.append_message("s1", "user", "hello")
        thread_enabled.append_message("s1", "assistant", "hi!")

        response = _client().get("/api/v1/threads/s1")
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "s1"
        assert [m["content"] for m in body["messages"]] == ["hello", "hi!"]

    def test_get_missing_thread_404(self, thread_enabled):
        response = _client().get("/api/v1/threads/missing")
        assert response.status_code == 404

    def test_get_thread_message_pagination(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        for i in range(5):
            thread_enabled.append_message("s1", "user", f"m{i}")

        client = _client()
        r1 = client.get("/api/v1/threads/s1", params={"limit": 2})
        assert r1.status_code == 200
        b1 = r1.json()
        assert [m["content"] for m in b1["messages"]] == ["m0", "m1"]
        assert b1["next_cursor"] is not None

        r2 = client.get("/api/v1/threads/s1", params={"limit": 2, "cursor": b1["next_cursor"]})
        b2 = r2.json()
        assert [m["content"] for m in b2["messages"]] == ["m2", "m3"]

    def test_get_thread_bad_cursor_400(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        response = _client().get("/api/v1/threads/s1", params={"cursor": "!!bad!!"})
        assert response.status_code == 400

    def test_list_threads_pagination(self, thread_enabled):
        for i in range(3):
            thread_enabled.get_or_create_thread(f"s{i}", "u1", first_prompt="p")

        client = _client()
        r1 = client.get("/api/v1/threads", params={"user_id": "u1", "limit": 2})
        b1 = r1.json()
        assert len(b1["threads"]) == 2
        assert b1["next_cursor"] is not None

        r2 = client.get("/api/v1/threads", params={"user_id": "u1", "limit": 2, "cursor": b1["next_cursor"]})
        b2 = r2.json()
        assert len(b2["threads"]) == 1
        assert b2["next_cursor"] is None

    def test_routes_404_when_thread_support_disabled(self):
        AKConfig.get().thread = None
        ConversationThreadManager.reset()
        response = _client().get("/api/v1/threads")
        assert response.status_code == 404


class TestThreadRouterAuthorised:
    """Thread routes protected by an Authoriser."""

    def test_missing_token_401(self, thread_enabled):
        response = _client(StaticAuthoriser()).get("/api/v1/threads")
        assert response.status_code == 401

    def test_bad_token_401(self, thread_enabled):
        response = _client(StaticAuthoriser()).get("/api/v1/threads", headers={"Authorization": "Bearer bad-token"})
        assert response.status_code == 401

    def test_non_bearer_scheme_401(self, thread_enabled):
        response = _client(StaticAuthoriser()).get("/api/v1/threads", headers={"Authorization": "Basic good-token"})
        assert response.status_code == 401

    def test_empty_token_401(self, thread_enabled):
        response = _client(StaticAuthoriser()).get("/api/v1/threads", headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_lowercase_bearer_scheme_accepted(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        response = _client(StaticAuthoriser()).get("/api/v1/threads", headers={"Authorization": "bearer good-token"})
        assert response.status_code == 200

    def test_listing_forced_to_authorised_user(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        thread_enabled.get_or_create_thread("s2", "u2", first_prompt="b")

        # Caller asks for u2's threads but the token resolves to u1 — listing is forced to u1
        response = _client(StaticAuthoriser()).get("/api/v1/threads", params={"user_id": "u2"}, headers={"Authorization": "Bearer good-token"})
        assert response.status_code == 200
        assert [t["session_id"] for t in response.json()["threads"]] == ["s1"]

    def test_get_owned_thread_200(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u1", first_prompt="a")
        response = _client(StaticAuthoriser()).get("/api/v1/threads/s1", headers={"Authorization": "Bearer good-token"})
        assert response.status_code == 200

    def test_get_unowned_thread_403(self, thread_enabled):
        thread_enabled.get_or_create_thread("s1", "u2", first_prompt="a")
        response = _client(StaticAuthoriser()).get("/api/v1/threads/s1", headers={"Authorization": "Bearer good-token"})
        assert response.status_code == 403
