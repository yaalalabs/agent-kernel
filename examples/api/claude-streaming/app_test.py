"""Test the Claude example's SSE frame contract through its REST endpoint; requires Claude credentials."""

import asyncio
import json
import subprocess
import sys
import time
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

HOST, PORT = "localhost", 8000
STARTUP_TIMEOUT = 90


async def _wait_until_serving(proc):
    """Block until the app accepts a connection, or raise if it exits or never serves.

    Polled rather than slept: a cold CI runner can take much longer to import the app than a laptop does.
    """
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"app.py exited with code {proc.returncode} before it began serving")
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(HOST, PORT), timeout=1)
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.25)
            continue
        writer.close()
        await writer.wait_closed()
        return
    raise RuntimeError(f"app.py did not serve {HOST}:{PORT} within {STARTUP_TIMEOUT}s")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def base_url():
    proc = subprocess.Popen([sys.executable, "app.py"], stdout=sys.stdout, stderr=sys.stderr)
    try:
        await _wait_until_serving(proc)
        yield f"http://{HOST}:{PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


async def _collect_frames(url: str, prompt: str) -> tuple[str, list[dict]]:
    """POST to the streaming endpoint and parse every SSE `data:` frame into a dict."""
    session_id = str(uuid.uuid4())
    frames: list[dict] = []
    payload = {"prompt": prompt, "session_id": session_id, "agent": "weather"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", f"{url}/api/v1/chat", json=payload) as resp:
            resp.raise_for_status()
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    frames.append(json.loads(line[len("data:") :].strip()))
    return session_id, frames


def _assert_frame_contract(session_id: str, frames: list[dict]) -> list[dict]:
    """Check the SSE contract every streaming framework honors, and return the typed events in order."""
    assert frames, "expected at least one SSE frame"
    assert all(f.get("session_id") == session_id for f in frames)
    assert all("error" not in f for f in frames), frames

    # Exactly the final frame is the terminal done frame; it carries neither delta nor event.
    assert frames[-1].get("done") is True
    assert "delta" not in frames[-1] and "event" not in frames[-1]
    assert all(f.get("done") is False for f in frames[:-1])
    assert all("event" in f for f in frames[:-1]), frames

    # delta and event never disagree: only a text_delta carries a delta, and it is the same text.
    for frame in frames[:-1]:
        if "delta" in frame:
            assert frame["event"]["type"] == "text_delta", frame
            assert frame["delta"] == frame["event"]["content"], frame
        else:
            assert frame["event"]["type"] != "text_delta", frame

    # Boundaries bracket their own text deltas, including across the several messages of a tool turn.
    events = [f["event"] for f in frames[:-1]]
    open_messages = set()
    for event in events:
        if event["type"] == "message_start":
            assert event["message_id"] not in open_messages
            open_messages.add(event["message_id"])
        elif event["type"] == "text_delta":
            assert event["message_id"] in open_messages
        elif event["type"] == "message_end":
            assert event["message_id"] in open_messages
            open_messages.remove(event["message_id"])
    assert not open_messages, "every started message must end before done"

    text = "".join(f["delta"] for f in frames if "delta" in f)
    assert text.strip(), "expected non-empty streamed text across delta frames"
    return events


async def test_streaming_delta_then_done(base_url):
    session_id, frames = await _collect_frames(base_url, "In two sentences, why is the sky blue?")
    events = _assert_frame_contract(session_id, frames)

    event_types = [e["type"] for e in events]
    assert "message_start" in event_types and "message_end" in event_types, event_types


async def test_tool_call_streams_start_args_end_and_result(base_url):
    session_id, frames = await _collect_frames(base_url, "What's the weather in Tokyo? Use the get_weather tool.")
    events = _assert_frame_contract(session_id, frames)

    starts = [e for e in events if e["type"] == "tool_call_start" and e["name"].endswith("get_weather")]
    assert starts, [e["type"] for e in events]
    call_id = starts[0]["tool_call_id"]
    of_call = [e for e in events if e.get("tool_call_id") == call_id]
    kinds = [e["type"] for e in of_call]

    # The call opens, its arguments stream, it closes, and only then does its result arrive.
    assert kinds[0] == "tool_call_start" and "tool_call_end" in kinds and "tool_call_result" in kinds, kinds
    assert kinds.index("tool_call_end") < kinds.index("tool_call_result"), kinds
    args = "".join(e["delta"] for e in of_call if e["type"] == "tool_call_args")
    assert "tokyo" in json.loads(args)["city"].lower(), args  # the streamed fragments join into valid JSON
    result = next(e for e in of_call if e["type"] == "tool_call_result")
    assert "sunny" in result["content"].lower()

    # The model's answer, streamed after the tool returned, uses the result.
    answer_start = events.index(result)
    answer = "".join(e["content"] for e in events[answer_start:] if e["type"] == "text_delta")
    assert "sunny" in answer.lower(), answer
