"""LiveKitLifecycleAdapter: LiveKit's signed room webhooks as edge lifecycle events."""

import asyncio
import base64
import hashlib
import json
import types

import pytest
from fastapi import HTTPException
from livekit import api

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel.integration.livekit import LiveKitLifecycleAdapter

KEY, SECRET = "devkey", "secret" * 8


class _Request:
    """The two things parse reads from a FastAPI Request: the body and the Authorization header."""

    def __init__(self, event: str, room: str | None = "call_1", secret: str = SECRET, identity: str | None = None):
        payload = {
            "event": event,
            **({"room": {"name": room}} if room is not None else {}),
            **({"participant": {"identity": identity}} if identity else {}),
        }
        self._body = json.dumps(payload).encode()
        digest = base64.b64encode(hashlib.sha256(self._body).digest()).decode()
        self.headers = {"Authorization": api.AccessToken(KEY, secret).with_sha256(digest).to_jwt()}

    async def body(self):
        return self._body


def _parse(request):
    return asyncio.run(LiveKitLifecycleAdapter(api_key=KEY, api_secret=SECRET).parse(request))


def test_room_started_starts_the_rooms_edge():
    assert _parse(_Request("room_started")) == livekit_adapter.EdgeLifecycleEvent("call_1", start=True)


def test_room_finished_ends_it():
    assert _parse(_Request("room_finished")) == livekit_adapter.EdgeLifecycleEvent("call_1", start=False)


def test_a_caller_joining_starts_the_rooms_edge_again():
    assert _parse(_Request("participant_joined")) == livekit_adapter.EdgeLifecycleEvent("call_1", start=True)


def test_an_agent_participant_joining_does_not_start_an_edge():
    assert _parse(_Request("participant_joined", identity="agent-general")) is None


def test_an_invalid_utf8_body_is_a_401():
    request = _Request("room_started")
    request._body = b"\xff\xfe"

    with pytest.raises(HTTPException) as raised:
        _parse(request)

    assert raised.value.status_code == 401


@pytest.mark.parametrize("event", ["participant_left", "track_published"])
def test_other_room_events_start_or_end_nothing(event):
    assert _parse(_Request(event)) is None


def test_an_event_without_a_room_is_ignored():
    assert _parse(_Request("room_started", room=None)) is None


def test_a_bad_signature_is_a_401():
    with pytest.raises(HTTPException) as raised:
        _parse(_Request("room_started", secret="another" * 8))

    assert raised.value.status_code == 401


def test_needs_the_api_key_and_secret(monkeypatch):
    config = types.SimpleNamespace(livekit=types.SimpleNamespace(api_key="", api_secret=""))
    monkeypatch.setattr(livekit_adapter.AKConfig, "get", staticmethod(lambda: config))

    with pytest.raises(ValueError, match="AK_LIVEKIT__API_KEY"):
        LiveKitLifecycleAdapter()


def test_the_rooms_edge_is_built_with_the_same_keys(monkeypatch):
    built = {}
    monkeypatch.setattr(livekit_adapter, "LiveKitEdgeAdapter", lambda **kwargs: built.update(kwargs) or object())

    LiveKitLifecycleAdapter(api_key=KEY, api_secret=SECRET).create_edge("call_9")

    assert built == {"session_id": "call_9", "api_key": KEY, "api_secret": SECRET}


def test_every_room_gets_an_edge_by_default():
    assert LiveKitLifecycleAdapter(api_key=KEY, api_secret=SECRET).should_start("anything") is True


def test_the_handler_starts_a_real_edge_for_a_signed_room_webhook(monkeypatch):
    """The real pieces composed: EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter()) behind a route, a signed webhook, the edge it builds."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import agentkernel.integration.adapter.lifecycle as lifecycle_module
    from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler

    started = []

    class _Runner:
        def __init__(self, edge):
            self.edge = edge

        def start(self):
            started.append(self.edge)

    monkeypatch.setattr(lifecycle_module, "_EdgeRunner", _Runner)
    config = types.SimpleNamespace(
        livekit=types.SimpleNamespace(url="wss://lk", agent="", api_key="", api_secret=""),
        execution=types.SimpleNamespace(realtime=types.SimpleNamespace(input_batch_ms=100)),
    )
    monkeypatch.setattr(livekit_adapter.AKConfig, "get", staticmethod(lambda: config))
    handler = EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter(api_key=KEY, api_secret=SECRET))
    app = FastAPI()
    app.include_router(handler.get_router())
    request = _Request("room_started", room="call_7")

    response = TestClient(app).post(LiveKitLifecycleAdapter.webhook_path, content=request._body, headers=request.headers)

    assert response.status_code == 200
    for _ in range(100):
        if started:
            break
        asyncio.run(asyncio.sleep(0.02))
    (edge,) = started
    assert isinstance(edge, livekit_adapter.LiveKitEdgeAdapter)
    assert edge.session_id == "call_7"
