"""
SSE streaming test for the Pydantic AI streaming example.

The shared `agentkernel.test` JSON request/response client cannot drive Server-Sent Events, so this
test starts `app.py` (which runs with `execution.mode: stream` from config.yaml) and consumes the
`text/event-stream` body directly with httpx: it POSTs to /api/v1/chat and asserts the frame
contract documented in README.md — a sequence of `delta` frames followed by a single terminal
`done` frame, all echoing the request's session_id.

The assertions are structural (frame shape, ordering, non-empty accumulated text) rather than
semantic, so the test does not depend on the model's exact wording. Requires OPENAI_API_KEY, since
the demo agent uses openai:gpt-4o-mini.
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

    # Exactly the final frame is the terminal done frame; it carries no delta.
    assert frames[-1].get("done") is True
    assert "delta" not in frames[-1]
    assert all(f.get("done") is False for f in frames[:-1])

    # The delta frames accumulate to a non-empty story.
    story = "".join(f["delta"] for f in frames[:-1])
    assert story.strip(), "expected non-empty streamed text across delta frames"
