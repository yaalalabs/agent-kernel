"""C1 to C5 together: a caller line, a handoff, the agent's reply and the end of the session, through the real pool and gateway.

The native session is a fake adapter that reports what a real one would; the output queue is the in-memory
transport; the edge is the LiveKit gateway over its fakes. Nothing reaches a model or a room.
"""

import asyncio
import json
import threading
import types

import pytest
from test_livekit_gateway import _FakeRtc, _Recorder
from test_realtime_pool import _Adapter, _Agent, _drain_output

import agentkernel.integration.livekit.adapter as livekit_adapter
from agentkernel import Session
from agentkernel.core.model import AgentRequestText, BaseRunRequest, StreamChunk
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.pipeline.envelope import ATTR_REALTIME_END, QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnection, RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    async def send_inline(send, *args):
        return send(*args)

    monkeypatch.setattr("agentkernel.pipeline.realtime_pool.asyncio.to_thread", send_inline)
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    RealtimeConnectionPool.reset()
    ThreadRunner.shutdown_event.clear()


@pytest.mark.asyncio
async def test_a_call_from_caller_line_to_handoff_to_end_of_session(monkeypatch):
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
    conn = RealtimeConnection("s1", _Agent(name="pm"), Runtime(InMemorySessionStore()), Session("s1"), asyncio.get_running_loop())
    conn.update_delivery_context("r1", None, "livekit", {"session_id": "s1"})
    await conn.connect()

    # What a native session reports: the caller speaks, the PM hands off, the BA answers.
    for kind, data in [
        ("input_transcript", {"text": "we need online booking", "message_id": "i1"}),
        ("audio_delta", {"delta": "QUFB", "message_id": "m1"}),
        ("transcript_delta", {"delta": "Let me bring in our BA.", "message_id": "m1"}),
        ("done", {"status": "completed"}),
        ("agent_changed", {"agent": "ba", "previous_agent": "pm", "agents": ["pm", "ba"]}),
        ("audio_delta", {"delta": "QUFB", "message_id": "m2"}),
        ("transcript_delta", {"delta": "BA here. Who books?", "message_id": "m2"}),
        ("done", {"status": "completed"}),
    ]:
        await conn.handle_framework_event(kind, data)
    await asyncio.sleep(0.3)
    conn._pacing_task.cancel()

    chunks = [StreamChunk.model_validate(json.loads(message.body)) for message in _drain_output(transport)]
    order = ["done" if chunk.done else chunk.event.type for chunk in chunks]
    assert order == [
        "agent_changed",
        "input_transcript",
        "audio_delta",
        "text_delta",
        "done",
        "agent_changed",
        "audio_delta",
        "text_delta",
        "done",
    ]

    monkeypatch.setattr(livekit_adapter, "rtc", _FakeRtc)
    gateway = _Recorder.build("pm", "ba")
    gateway._loop = asyncio.get_running_loop()
    gateway._caller_identity = "client-1"
    gateway._team_lock, gateway._pending_team, gateway._connected = threading.Lock(), None, True
    for chunk in chunks:
        await gateway.deliver_chunk(chunk, {})
    gateway._close_hooks()

    assert [(call[1].speaker, call[1].role, call[1].text) for call in gateway.calls if call[0] == "line"] == [
        ("client-1", "user", "we need online booking"),
        ("pm", "agent", "Let me bring in our BA."),
        ("ba", "agent", "BA here. Who books?"),
    ]
    assert [call[1:] for call in gateway.calls if call[0] == "changed"] == [("pm", None), ("ba", "pm")]

    # The edge ends: the control closes the native session and later input for it is dropped.
    pool = RealtimeConnectionPool.initialize()
    thread = threading.Thread(target=pool.start, daemon=True)
    thread.start()
    try:
        from unittest.mock import MagicMock

        handler = types.SimpleNamespace(service=types.SimpleNamespace(agent=_Agent(), runtime=Runtime(InMemorySessionStore()), session=Session("s2")))
        chat_service = MagicMock()
        chat_service.prepare_agent_handler.return_value = handler
        pool.dispatch(BaseRunRequest(prompt="", session_id="s2", requests=[AgentRequestText(prompt="hi")]), "r", None, {}, chat_service)
        live = pool.get_connection("s2")
        assert live is not None

        pool.dispatch(BaseRunRequest(prompt="", session_id="s2", requests=[]), "r", None, {ATTR_REALTIME_END: "true"}, chat_service)
        pool.dispatch(BaseRunRequest(prompt="", session_id="s2", requests=[AgentRequestText(prompt="late")]), "r", None, {}, chat_service)

        assert live.closed
        assert pool.get_connection("s2") is None
        assert chat_service.prepare_agent_handler.call_count == 1
    finally:
        ThreadRunner.shutdown_event.set()
        thread.join(timeout=5)
