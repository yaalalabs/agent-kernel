"""
SSE streaming test for the Pydantic AI streaming example.

The shared `agentkernel.test` JSON request/response client cannot drive Server-Sent Events, so this
test starts `app.py` (which runs with `execution.mode: stream` from config.yaml) and consumes the
`text/event-stream` body directly with httpx: it POSTs to /api/v1/chat and asserts the frame
contract, stated here rather than by reference so this file stands on its own:

- Every frame echoes the request's session_id, and none carries an `error`.
- Every frame but the last carries an `event` — the typed stream event it was built from. The last
  frame is the terminal `{"done": true}` and carries neither `event` nor `delta`.
- A frame carrying assistant prose has both `delta` and a `text_delta` event, and the two agree.
  `delta` is what a plain-text client concatenates; `event` is the same text plus its correlation id.
- Frames whose event is not a `text_delta` carry **no `delta` key at all** — the payload is dumped
  with `exclude_none=True`, so an absent value is an absent key. The assistant message is bracketed
  by `message_start` and `message_end` frames of exactly this kind, which is why accumulating text
  must filter on the key's presence rather than slice by position.

The assertions are structural (frame shape, ordering, non-empty accumulated text) rather than
semantic, so the test does not depend on the model's exact wording. Nothing here assumes how many
boundary frames arrive or where: today `Runtime.stream` synthesises one pair because this adapter
still yields plain strings, and once it emits its own events the adapter decides. Requires
OPENAI_API_KEY, since the demo agent uses openai:gpt-4.1-mini.
"""

import asyncio
import json
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def base_url():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(5)
    try:
        yield "http://localhost:8000"
    finally:
        proc.terminate()
        proc.wait()


async def _collect_frames(url: str, payload: dict) -> list[dict]:
    """POST to the streaming endpoint and parse every SSE `data:` frame into a dict."""
    frames: list[dict] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", f"{url}/api/v1/chat", json=payload) as resp:
            resp.raise_for_status()
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    frames.append(json.loads(line[len("data:") :].strip()))
    return frames


@pytest.mark.asyncio
async def test_streaming_delta_then_done(base_url):
    print("test_streaming_delta_then_done")
    session_id = str(uuid.uuid4())
    frames = await _collect_frames(
        base_url,
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

    # The delta-bearing frames accumulate to a non-empty story. Filter on the key, not on position:
    # the boundary frames sit among them and have no delta.
    story = "".join(f["delta"] for f in frames if "delta" in f)
    assert story.strip(), "expected non-empty streamed text across delta frames"
