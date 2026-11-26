"""Integration test for queue-mode SSE on ECS.

The point of this example is that chunks arrive *incrementally*. A test that only checks the final
text would pass just as happily against a gateway that buffered the whole reply and released it in
one burst, which is the bug #978 exists to remove. So the timing assertion is the real test and the
content assertion is the sanity check.
"""

import asyncio
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

    async def wait_until_serving(self, budget: float = 180.0, interval: float = 10.0) -> None:
        """Block until the ALB has a healthy target behind the gateway.

        `terraform apply` returns when the ECS service is created, not when a task is running and
        registered, so the first request can arrive while the target group is still empty and the
        gateway answers 503. An empty body is used deliberately: the chat route rejects it at
        validation with a 4xx without running an agent, so this costs nothing but proves the
        container is serving. Done here rather than inside `stream` so retry time never lands in the
        arrival offsets the timing assertion reads.
        """
        deadline = time.monotonic() + budget
        last = None
        while time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(self.url, json={"session_id": "", "prompt": ""})
                if resp.status_code < 500:
                    return
                last = f"HTTP {resp.status_code}"
            except httpx.TransportError as exc:
                last = type(exc).__name__
            await asyncio.sleep(interval)
        raise AssertionError(f"endpoint never became ready within {budget:.0f}s (last: {last})")

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
    client = SSETestClient(os.environ["AK_TEST_ENDPOINT"])
    await client.wait_until_serving()
    yield client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def streamed(sse_client):
    """One streamed reply, shared by the assertions below so the suite makes a single agent call."""
    yield await sse_client.stream(LONG_PROMPT)


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_reply_arrives_as_multiple_frames(streamed):
    frames, _ = streamed
    assert (
        len(frames) > 1
    ), f"expected several SSE frames, got {len(frames)}: a single frame means the reply was buffered"
    assert any(f.get("done") for f in frames), "no terminal frame with done=true"
    assert not any("error" in f for f in frames), f"error frame in stream: {[f for f in frames if 'error' in f]}"


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_frames_are_spread_over_time(streamed):
    """The assertion that distinguishes streaming from buffering.

    A buffered reply arrives as one burst, so every frame lands within milliseconds of the first.
    A streamed one spreads across the generation. The threshold is deliberately loose: this
    separates "one burst" from "a stream", not fast streaming from slow.

    Only frames that carry text count. Frame count and total span alone are too weak: an empty
    delta followed a second later by the whole answer satisfies both while having streamed nothing.
    """
    frames, offsets = streamed
    text_offsets = [offset for frame, offset in zip(frames, offsets) if frame.get("delta")]
    assert len(text_offsets) >= 2, (
        f"only {len(text_offsets)} of {len(frames)} frames carried text, so the reply did not "
        "arrive incrementally even though several frames did"
    )
    span = text_offsets[-1] - text_offsets[0]
    assert span > 0.5, (
        f"all {len(text_offsets)} text frames arrived within {span:.3f}s of each other, which is a "
        "buffered response released in one burst, not a stream"
    )


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_streamed_text_answers_the_question(streamed):
    frames, _ = streamed
    text = "".join(f.get("delta", "") for f in frames)
    assert text.strip(), "frames carried no delta text"
    Test.compare(
        text, ["An explanation of ancient Sri Lankan reservoir and canal irrigation at Anuradhapura and Polonnaruwa"]
    )
