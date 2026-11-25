"""Integration test for queue-mode SSE on ECS.

The point of this example is that chunks arrive *incrementally*. A test that only checks the final
text would pass just as happily against a gateway that buffered the whole reply and released it in
one burst, which is the bug #978 exists to remove. So the timing assertion is the real test and the
content assertion is the sanity check.
"""

import json
import os
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

# A reply has to take long enough to actually stream. A one-line answer arrives in a single frame
# whether or not the gateway buffers, and proves nothing either way.
LONG_PROMPT = (
    "Explain the tank-and-canal irrigation system of ancient Anuradhapura and Polonnaruwa in at "
    "least six sentences, covering how the reservoirs were fed and what the bisokotuwa sluice did."
)


class SSETestClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def stream(self, prompt: str) -> tuple[list[dict], list[float]]:
        """POST the prompt and return (frames, arrival offsets in seconds from the first frame)."""
        payload = {"prompt": prompt, "session_id": self.session_id, "agent": "triage"}
        frames: list[dict] = []
        offsets: list[float] = []
        start: float | None = None
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", self.url, json=payload) as resp:
                resp.raise_for_status()
                assert resp.headers["content-type"].startswith(
                    "text/event-stream"
                ), f"expected an SSE response, got {resp.headers.get('content-type')!r}"
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    now = time.monotonic()
                    if start is None:
                        start = now
                    frames.append(json.loads(line[len("data: ") :]))
                    offsets.append(now - start)
        return frames, offsets


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sse_client():
    yield SSETestClient(os.environ["AK_TEST_ENDPOINT"])


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def streamed(sse_client):
    """One streamed reply, shared by the assertions below so the suite makes a single agent call."""
    yield await sse_client.stream(LONG_PROMPT)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_reply_arrives_as_multiple_frames(streamed):
    frames, _ = streamed
    assert len(frames) > 1, f"expected several SSE frames, got {len(frames)}: a single frame means the reply was buffered"
    assert any(f.get("done") for f in frames), "no terminal frame with done=true"
    assert not any("error" in f for f in frames), f"error frame in stream: {[f for f in frames if 'error' in f]}"


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_frames_are_spread_over_time(streamed):
    """The assertion that distinguishes streaming from buffering.

    A buffered reply arrives as one burst, so every frame lands within milliseconds of the first.
    A streamed one spreads across the generation. The threshold is deliberately loose: this
    separates "one burst" from "a stream", not fast streaming from slow.
    """
    _, offsets = streamed
    span = offsets[-1] - offsets[0]
    assert span > 0.5, (
        f"all {len(offsets)} frames arrived within {span:.3f}s of each other, which is a buffered "
        "response released in one burst, not a stream"
    )


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_streamed_text_answers_the_question(streamed):
    frames, _ = streamed
    text = "".join(f.get("delta", "") for f in frames)
    assert text.strip(), "frames carried no delta text"
    Test.compare(text, ["An explanation of ancient Sri Lankan reservoir and canal irrigation at Anuradhapura and Polonnaruwa"])
