"""#884: every public chat route parses ChatRunRequest, so a client cannot set the fields only
internal producers use, and the API docs do not advertise them.

One case per handler that serves POST /api/v1/chat. A route whose body annotation drifted back to
BaseRunRequest would accept the fields again and fail here.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentkernel.api.handler import AgentRESTRequestHandler
from agentkernel.core.config import AKConfig, _ThreadStoreConfig
from agentkernel.core.model import ChatRunRequest, Principal
from agentkernel.identity import IdentityProvider, IdentityProviderFactory, RequestAuthenticator
from agentkernel.integration.thread.manager import ConversationThreadManager
from agentkernel.integration.thread.thread_chat import AgentThreadRequestHandler, ThreadRequestHandler
from agentkernel.pipeline.request_handler import RequestHandler, RestHandler
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


class _QueuedRestHandler(RestHandler):
    """RestHandler in queue mode, the shape ECSQueueRequestHandler serves."""

    def _is_queue_mode(self) -> bool:
        return True


HANDLERS = {
    "direct": AgentRESTRequestHandler,
    "rest-queue": _QueuedRestHandler,
    "pipeline": RequestHandler,
    "thread-direct": AgentThreadRequestHandler,
    "thread-pipeline": ThreadRequestHandler,
}

INTERNAL_VALUES = {"requests": [{"type": "text", "prompt": "x"}], "scheduled_task_id": "t1", "scheduled_time": "2026-01-01T00:00:00Z"}
AUTH = {"Authorization": "Bearer u1-token"}


class _Provider(IdentityProvider):
    """Accepts any token as user u1: the thread handlers need a configured provider to build."""

    name = "test"

    async def authenticate(self, credential, context=None):
        return Principal(subject="u1", provider=self.name, namespace="test")


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: _Provider()))
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.delenv("AK_EXECUTION__MODE", raising=False)
    AKConfig._reset()
    AKConfig.get().thread = _ThreadStoreConfig(type="in_memory")
    ConversationThreadManager.reset()
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()
    ConversationThreadManager.reset()
    AKConfig._reset()


def _app(name: str) -> FastAPI:
    """The handler's routes behind the identity dependency, as ``RESTAPI`` mounts them."""
    app = FastAPI()
    app.include_router(HANDLERS[name]().get_router(), dependencies=[Depends(RequestAuthenticator(_Provider()).dependency())])
    return app


@pytest.mark.parametrize("name", HANDLERS)
@pytest.mark.parametrize("field", sorted(ChatRunRequest.INTERNAL_FIELDS))
def test_the_chat_route_rejects_an_internal_field(name, field):
    body = {"prompt": "hi", "session_id": "s1", field: INTERNAL_VALUES[field]}

    response = TestClient(_app(name)).post(AgentRESTRequestHandler.CHAT_PATH, json=body, headers=AUTH)

    assert response.status_code == 422
    assert field in response.text


@pytest.mark.parametrize("name", HANDLERS)
def test_the_chat_route_schema_does_not_advertise_them(name):
    spec = _app(name).openapi()
    ref = spec["paths"][AgentRESTRequestHandler.CHAT_PATH]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    properties = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]

    assert "prompt" in properties
    assert not ChatRunRequest.INTERNAL_FIELDS & properties.keys()


@pytest.mark.parametrize("name", HANDLERS)
def test_a_null_internal_field_reaches_the_route_unrejected(name):
    """Null means "not set": the body passes the model and gets the route's own answer (no prompt here)."""
    body = {"session_id": "s1", **dict.fromkeys(ChatRunRequest.INTERNAL_FIELDS)}

    response = TestClient(_app(name)).post(AgentRESTRequestHandler.CHAT_PATH, json=body, headers=AUTH)

    assert response.status_code == 400
    assert "prompt" in response.text.lower()
