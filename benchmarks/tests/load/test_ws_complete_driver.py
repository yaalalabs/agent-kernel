import asyncio
import json

import pytest
from agentkernel.core import TraceStage
from mocks.ws_server import MockWsServer

from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver
from ak_bench.load.token import TokenSigner

SECRET = "s3cret"


async def until(condition, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def connected(server: MockWsServer, events: list, endpoint: str | None = None) -> WebSocketCompleteDriver:
    driver = WebSocketCompleteDriver(endpoint or server.url, TokenSigner(SECRET).token("bench-1"), events.append)
    await driver.connect()
    return driver


@pytest.mark.asyncio
async def test_frame_shape_and_complete_reply():
    events = []
    async with MockWsServer(SECRET) as server:
        driver = await connected(server, events)
        await driver.send("req1", "sess1", "req1")
        await until(lambda: len(events) == 2)
        await driver.close()
    assert server.received[0][1] == {"request_id": "req1", "body": {"session_id": "sess1", "prompt": "req1"}}
    # CHAT_QUEUED (which carries the request id) is ignored; the reply without request id is matched by its text.
    assert [(e.request_id, e.kind) for e in events] == [("req1", "first_chunk"), ("req1", "complete")]
    assert events[0].mono == events[1].mono


@pytest.mark.asyncio
async def test_token_added_to_endpoint_query():
    async with MockWsServer(SECRET) as server:
        driver = await connected(server, [], server.url + "?x=1")
        await driver.close()
    assert server.paths == [f"/ws?x=1&token={TokenSigner(SECRET).token('bench-1')}"]
    assert server.connections == {"bench-1": 1}


@pytest.mark.asyncio
async def test_refused_token_raises_on_connect():
    async with MockWsServer("other-secret") as server:
        driver = WebSocketCompleteDriver(server.url, TokenSigner(SECRET).token("bench-1"), print)
        with pytest.raises(ConnectionRefusedError, match="1008"):
            await driver.connect()
        await driver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server_kw", "detail"),
    [({"fail": {"req1"}}, "Request processing failed"), ({"agent_error": {"req1"}}, "agent failed")],
)
async def test_id_less_error_reply_settles_the_only_in_flight_request(server_kw, detail):
    events = []
    async with MockWsServer(SECRET, **server_kw) as server:
        driver = await connected(server, events)
        await driver.send("req1", "sess1", "req1")
        await until(lambda: events)
        await driver.close()
    assert [(e.request_id, e.kind, e.detail) for e in events] == [("req1", "error", detail)]


@pytest.mark.asyncio
async def test_id_less_error_reply_with_two_in_flight_is_not_guessed(caplog):
    events = []
    async with MockWsServer(SECRET, delay_s=0.05, fail={"req1"}, drop={"req2"}) as server:
        driver = await connected(server, events)
        await driver.send("req1", "sess1", "req1")
        await driver.send("req2", "sess1", "req2")
        await until(lambda: "id-less error reply with 2 requests in flight" in caplog.text)
        await asyncio.sleep(0.1)
        await driver.close()
    # Neither is settled: both stay in flight and end by the generator's client timeout.
    assert events == []
    assert list(driver._in_flight) == ["req1", "req2"]
    assert any(r.levelname == "WARNING" and "Request processing failed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_duplicate_reply_dropped():
    events = []
    async with MockWsServer(SECRET, duplicate=True) as server:
        driver = await connected(server, events)
        await driver.send("req1", "sess1", "req1")
        await until(lambda: len(events) == 2)
        await asyncio.sleep(0.1)
        await driver.close()
    assert len(events) == 2


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "CHAT_RESPONSE", "error": "boom", "request_id": "abc"},  # agent error reply
        {"type": "SYSTEM_RESPONSE", "error": "boom", "request_id": "abc", "session_id": "s"},  # permanent delivery failure (no status)
    ],
)
def test_error_frames_are_errors_not_ok(frame):
    events = []
    driver = WebSocketCompleteDriver("ws://unused", "t", events.append)
    driver._in_flight["abc"] = None
    driver._handle(json.dumps(frame))
    assert [(e.request_id, e.kind, e.detail) for e in events] == [("abc", "error", "boom")]


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "CHAT_QUEUED", "status": "SUCCESS", "request_id": "abc"},
        {"type": "STREAM_CHUNK", "request_id": "abc", "delta": "abc"},
        {"type": "SYSTEM_RESPONSE", "status": "SUCCESS", "request_id": "abc"},
    ],
)
def test_frames_that_are_not_replies_ignored(frame):
    events = []
    driver = WebSocketCompleteDriver("ws://unused", "t", events.append)
    driver._in_flight["abc"] = None
    driver._handle(json.dumps(frame))
    assert events == []
    assert "abc" in driver._in_flight


def test_unmatched_and_non_json_frames_dropped():
    events = []
    driver = WebSocketCompleteDriver("ws://unused", "t", events.append)
    driver._in_flight["abc"] = None
    driver._in_flight["def"] = None  # two in flight, so the id-less FAILED frame can't be attributed
    driver._handle("not json")
    driver._handle(json.dumps({"type": "CHAT_RESPONSE", "result": "content={'echo': 'xyz'}"}))
    driver._handle(json.dumps({"type": "SYSTEM_RESPONSE", "status": "FAILED", "message": "Request processing failed"}))
    assert events == []


def test_trace_stages_skip_streaming_and_polling_stages():
    stages = WebSocketCompleteDriver.trace_stages
    assert TraceStage.AGENT_FIRST_CHUNK not in stages
    assert TraceStage.RESPONSE_POLL_START not in stages and TraceStage.RESPONSE_FOUND not in stages
    assert list(stages) == [s for s in TraceStage if s in stages]
    assert stages[0] == TraceStage.REQUEST_RECEIVED and stages[-1] == TraceStage.RESPONSE_DELIVERED
