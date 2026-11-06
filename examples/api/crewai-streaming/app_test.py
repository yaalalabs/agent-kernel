"""Test the CrewAI example's SSE frame contract through its REST endpoint; requires OPENAI_API_KEY."""

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


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def stream(self, payload: dict) -> list[dict]:
        """POST to the streaming endpoint and parse every SSE `data:` frame into a dict."""
        frames: list[dict] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", f"{self.url}/api/v1/chat", json=payload) as resp:
                resp.raise_for_status()
                assert resp.headers["content-type"].startswith("text/event-stream")
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[len("data:") :].strip()))
        return frames


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    try:
        await _wait_until_serving(proc)
        yield APITestClient(f"http://{HOST}:{PORT}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.mark.asyncio
async def test_streaming_delta_then_done(http_client):
    print("test_streaming_delta_then_done")
    session_id = str(uuid.uuid4())
    frames = await http_client.stream(
        {"prompt": "a robot learning to paint", "session_id": session_id},
    )

    assert frames, "expected at least one SSE frame"

    # Every frame echoes the session id.
    assert all(f.get("session_id") == session_id for f in frames)

    # No frame carries an error.
    assert all("error" not in f for f in frames), frames

    # Exactly the final frame is the terminal done frame; it carries neither delta nor event.
    assert frames[-1].get("done") is True
    assert "delta" not in frames[-1]
    assert "event" not in frames[-1]
    assert all(f.get("done") is False for f in frames[:-1])

    # Every other frame carries the typed event it was built from.
    assert all("event" in f for f in frames[:-1]), frames

    # delta and event never disagree: a frame with a delta is a text_delta carrying the same text,
    # and any other kind of event omits delta entirely.
    for frame in frames[:-1]:
        if "delta" in frame:
            assert frame["event"]["type"] == "text_delta", frame
            assert frame["delta"] == frame["event"]["content"], frame
        else:
            assert frame["event"]["type"] != "text_delta", frame

    # The assistant message is bracketed by boundary frames.
    event_types = [f["event"]["type"] for f in frames[:-1]]
    assert "message_start" in event_types, event_types
    assert "message_end" in event_types, event_types

    # Boundaries bracket their own text deltas.
    open_messages = set()
    for frame in frames[:-1]:
        event = frame["event"]
        if event["type"] == "message_start":
            assert event["message_id"] not in open_messages
            open_messages.add(event["message_id"])
        elif event["type"] == "text_delta":
            assert event["message_id"] in open_messages
        elif event["type"] == "message_end":
            assert event["message_id"] in open_messages
            open_messages.remove(event["message_id"])
    assert not open_messages, "every started message must end before done"

    # The delta-bearing frames accumulate to a non-empty story. Filter on the key, not on position:
    # the boundary frames sit among them and have no delta.
    story = "".join(f["delta"] for f in frames if "delta" in f)
    assert story.strip(), "expected non-empty streamed text across delta frames"
