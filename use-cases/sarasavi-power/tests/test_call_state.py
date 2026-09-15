"""Call state machine tests with fully faked I/O (no WebRTC, no Gemini, no Meta)."""

from __future__ import annotations

import asyncio
import contextlib

from voice.call_manager import BUSY_MESSAGE, CallManager, CallSession, CallState


class FakeCallsAPI:
    def __init__(self, pre_accept_ok=True, accept_ok=True):
        self.actions: list[str] = []
        self._pre_accept_ok = pre_accept_ok
        self._accept_ok = accept_ok

    async def pre_accept(self, call_id, sdp):
        self.actions.append("pre_accept")
        return self._pre_accept_ok

    async def accept(self, call_id, sdp):
        self.actions.append("accept")
        return self._accept_ok

    async def reject(self, call_id):
        self.actions.append("reject")
        return True

    async def terminate(self, call_id):
        self.actions.append("terminate")
        return True


class FakeBridge:
    def __init__(self, connects=True):
        self._connects = connects
        self.closed = False

    async def answer(self, offer_sdp):
        return "sdp-answer"

    async def wait_connected(self, timeout):
        return self._connects

    async def wait_disconnected(self):
        await asyncio.Event().wait()  # never, unless cancelled

    async def pump_caller_to_gemini(self, live):
        await asyncio.Event().wait()

    async def pump_gemini_to_caller(self, live, transcript, on_tool_call):
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


class FakeLiveSession:
    async def send_client_content(self, **kwargs):
        pass

    async def send_tool_response(self, **kwargs):
        pass


@contextlib.asynccontextmanager
async def fake_live_connect():
    yield FakeLiveSession()


class FakeExecutor:
    async def call(self, name, args):
        return {"ok": True}


def _session(calls_api, bridge, on_done=None, max_seconds=0.2) -> CallSession:
    return CallSession(
        "call-1",
        "94770000001",
        "sdp-offer",
        calls_api=calls_api,
        bridge=bridge,
        live_connect=fake_live_connect,
        executor=FakeExecutor(),
        on_done=on_done,
        max_seconds=max_seconds,
    )


def test_happy_path_signals_and_ends_at_max_duration() -> None:
    api = FakeCallsAPI()
    bridge = FakeBridge()
    finished: list[CallSession] = []

    async def on_done(session):
        finished.append(session)

    session = _session(api, bridge, on_done=on_done, max_seconds=0.05)
    asyncio.run(session.run())

    assert api.actions == ["pre_accept", "accept", "terminate"]
    assert bridge.closed
    assert session.state is CallState.DONE
    assert finished == [session]


def test_end_call_tool_hangs_up_before_max_duration() -> None:
    """The agent's own end_call tool call terminates the line, not just a timeout."""
    import voice.call_manager as call_manager_module

    original_grace = call_manager_module.END_CALL_GRACE_SECONDS
    call_manager_module.END_CALL_GRACE_SECONDS = 0.01  # keep the test fast
    try:

        class EndCallFunctionCall:
            id = "fc-1"
            name = "end_call"
            args: dict = {}

        class EndCallBridge(FakeBridge):
            async def pump_gemini_to_caller(self, live, transcript, on_tool_call):
                await on_tool_call([EndCallFunctionCall()])
                await asyncio.Event().wait()  # the model stream itself stays open

        api = FakeCallsAPI()
        session = _session(api, EndCallBridge(), max_seconds=2.0)
        asyncio.run(session.run())

        assert api.actions == ["pre_accept", "accept", "terminate"]
        assert session.state is CallState.DONE
    finally:
        call_manager_module.END_CALL_GRACE_SECONDS = original_grace


def test_pre_accept_failure_ends_call_cleanly() -> None:
    api = FakeCallsAPI(pre_accept_ok=False)
    session = _session(api, FakeBridge())

    asyncio.run(session.run())

    assert api.actions == ["pre_accept"]
    assert session.state is CallState.DONE


def test_media_connect_timeout_terminates() -> None:
    api = FakeCallsAPI()
    session = _session(api, FakeBridge(connects=False))

    asyncio.run(session.run())

    assert api.actions == ["pre_accept", "accept", "terminate"]
    assert session.state is CallState.DONE


def test_close_is_idempotent_and_on_done_fires_once() -> None:
    api = FakeCallsAPI()
    fired: list[str] = []

    async def on_done(session):
        fired.append(session.call_id)

    session = _session(api, FakeBridge(), on_done=on_done)

    async def scenario():
        await session.close("first")
        await session.close("second")

    asyncio.run(scenario())

    assert fired == ["call-1"]


def _manager(api, send_log, max_calls=1) -> CallManager:
    def factory(call_id, from_number, offer_sdp):
        return _session(api, FakeBridge(), max_seconds=0.05)

    async def send_text(to, text):
        send_log.append((to, text))

    return CallManager(api, factory, send_text=send_text, max_calls=max_calls)


def test_manager_rejects_when_at_capacity() -> None:
    api = FakeCallsAPI()
    sent: list[tuple[str, str]] = []

    async def scenario():
        manager = _manager(api, sent, max_calls=0)
        await manager.handle_call_event(
            {"event": "connect", "id": "call-9", "from": "9477", "session": {"sdp": "offer"}}
        )

    asyncio.run(scenario())

    assert "reject" in api.actions
    assert sent == [("9477", BUSY_MESSAGE)]


def test_manager_ignores_connect_without_sdp_and_unknown_terminate() -> None:
    api = FakeCallsAPI()

    async def scenario():
        manager = _manager(api, [])
        await manager.handle_call_event({"event": "connect", "id": "call-9"})
        await manager.handle_call_event({"event": "terminate", "id": "ghost"})
        await manager.handle_call_event({"event": "connect"})

    asyncio.run(scenario())

    assert api.actions == []


def test_manager_runs_call_and_releases_capacity() -> None:
    api = FakeCallsAPI()

    async def scenario():
        manager = _manager(api, [], max_calls=1)
        await manager.handle_call_event(
            {"event": "connect", "id": "call-1", "from": "9477", "session": {"sdp": "offer"}}
        )
        assert manager.active_calls == 1
        for _ in range(100):
            await asyncio.sleep(0.01)
            if manager.active_calls == 0:
                break
        return manager.active_calls

    active = asyncio.run(scenario())

    assert active == 0
    assert api.actions == ["pre_accept", "accept", "terminate"]
