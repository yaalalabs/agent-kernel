import json
import os
import time
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


class SSETestClient:
    """Streams one chat request and records when each `data:` frame arrives."""

    def __init__(self, url: str, token: str | None):
        self.url = url
        self.token = token
        self.session_id = str(uuid.uuid4())

    async def stream(self, prompt: str) -> list[tuple[float, dict]]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        payload = {"prompt": prompt, "session_id": self.session_id, "agent": "triage"}
        frames: list[tuple[float, dict]] = []
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream("POST", self.url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                assert resp.headers["content-type"].startswith("text/event-stream")
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        frames.append((time.monotonic() - start, json.loads(line[len("data:") :].strip())))
        return frames


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    # AK_TEST_ENDPOINT is the chat URL (the deployment's agent_invoke_url); AK_TEST_TOKEN is the demo_auth_token value
    yield SSETestClient(os.environ["AK_TEST_ENDPOINT"], os.getenv("AK_TEST_TOKEN"))


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_reply_streams_as_several_frames_before_the_run_ends(http_client):
    frames = await http_client.stream("Who won the 1996 cricket world cup? Answer in two sentences.")

    assert len(frames) >= 3, f"expected several SSE frames, got {len(frames)}"
    assert frames[-1][1].get("done") is True
    assert not any("error" in body for _, body in frames), frames
    # Frames must arrive while the agent is still running, not in one block at the end
    first_arrival, last_arrival = frames[0][0], frames[-1][0]
    assert (
        last_arrival - first_arrival > 0.2
    ), f"all frames arrived together: first {first_arrival:.2f}s, last {last_arrival:.2f}s"
