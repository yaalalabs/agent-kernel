"""AG-UI example tests. Requires OPENAI_API_KEY."""

import asyncio
import json
import os
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

TOKEN = "demo-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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


def run_input(prompt: str, thread_id: str, state=None, context=None) -> dict:
    return {
        "threadId": thread_id,
        "runId": str(uuid.uuid4()),
        "state": state,
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": prompt}],
        "tools": [],
        "context": context or [],
        "forwardedProps": None,
    }


async def collect(url: str, payload: dict, path: str = "/agui") -> list[dict]:
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with client.stream("POST", f"{url}{path}", json=payload, headers=AUTH) as response:
            response.raise_for_status()
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:") :].strip()))
    return events


@pytest.mark.asyncio
async def test_discovery_lists_the_streaming_agent(base_url):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url}/agui/agents", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"agents": ["planner"]}


@pytest.mark.asyncio
async def test_routes_reject_a_missing_or_bad_token(base_url):
    async with httpx.AsyncClient(timeout=30.0) as client:
        assert (await client.get(f"{base_url}/agui/agents")).status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert (await client.post(f"{base_url}/agui", json=run_input("hi", "t"), headers=bad)).status_code == 401


@pytest.mark.asyncio
async def test_the_asset_route_serves_nothing_outside_assets(base_url):
    """Percent-encode `..`; httpx would otherwise normalise `/assets/..` to `/`."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        for path in ("/assets/%2e%2e", "/assets/nope.js"):
            assert (await client.get(f"{base_url}{path}")).status_code == 404, path


@pytest.mark.asyncio
async def test_run_lifecycle_brackets_the_response(base_url):
    events = await collect(base_url, run_input("Say hello in five words.", str(uuid.uuid4())))
    types = [event["type"] for event in events]

    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert types.count("RUN_STARTED") == 1
    assert types.count("RUN_FINISHED") + types.count("RUN_ERROR") == 1

    assert "TEXT_MESSAGE_START" in types and "TEXT_MESSAGE_END" in types
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert text.strip()

    message_ids = {e["messageId"] for e in events if e["type"].startswith("TEXT_MESSAGE_")}
    assert len(message_ids) == 1


@pytest.mark.asyncio
async def test_named_agent_route_works_too(base_url):
    events = await collect(base_url, run_input("Say hi.", str(uuid.uuid4())), path="/agui/planner")
    assert events[0]["type"] == "RUN_STARTED"


@pytest.mark.asyncio
async def test_an_unknown_agent_is_404(base_url):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{base_url}/agui/nobody", json=run_input("hi", "t"), headers=AUTH)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_audio_content_is_rejected_before_the_stream_opens(base_url):
    payload = run_input("listen", str(uuid.uuid4()))
    payload["messages"][0]["content"] = [
        {"type": "audio", "source": {"type": "data", "value": "AAA", "mimeType": "audio/mpeg"}}
    ]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{base_url}/agui", json=payload, headers=AUTH)
    assert response.status_code == 400
    assert "audio" in response.json()["detail"]


@pytest.mark.asyncio
async def test_state_round_trip(base_url):
    thread_id = str(uuid.uuid4())

    events = await collect(
        base_url, run_input("Add exactly one task titled 'milk' to my task list.", thread_id, state={"tasks": []})
    )
    snapshots = [e for e in events if e["type"] == "STATE_SNAPSHOT"]
    assert snapshots, f"expected a StateSnapshot after the agent updated the state; got {[e['type'] for e in events]}"

    titles = [task["title"] for task in snapshots[-1]["snapshot"]["tasks"]]
    assert any("milk" in title.lower() for title in titles), titles

    quiet = await collect(base_url, run_input("Just say ok.", thread_id, state=snapshots[-1]["snapshot"]))
    assert not [e for e in quiet if e["type"] == "STATE_SNAPSHOT"]


@pytest.mark.asyncio
async def test_client_context_reaches_the_agent_as_tool_output(base_url):
    context = [{"description": "the user's favourite colour", "value": "vermilion"}]
    prompt = "Check the context the frontend attached, then tell me my favourite colour."
    events = await collect(base_url, run_input(prompt, str(uuid.uuid4()), context=context))
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "vermilion" in text.lower(), text


@pytest.mark.asyncio
async def test_a_tool_call_is_streamed_as_tool_call_events(base_url):
    """The tool-call half of the demo, which only became reachable once the adapters were migrated.

    `count_open_tasks` is a plain function tool, so what this proves is the whole outbound chain for a
    tool call: the adapter's run-item mapping, `to_agui`, and the encoder. The prompt names the tool
    for the same reason the context test does — the capability is that the call *surfaces as events*,
    not that the model infers its way to it.
    """
    thread_id = str(uuid.uuid4())
    state = {"tasks": [{"title": "milk", "done": False}, {"title": "bread", "done": True}]}
    events = await collect(base_url, run_input("Call count_open_tasks and tell me the number.", thread_id, state=state))
    types = [event["type"] for event in events]

    assert "TOOL_CALL_START" in types, types
    assert "TOOL_CALL_END" in types, types

    started = [e for e in events if e["type"] == "TOOL_CALL_START"]
    call = next((e for e in started if e["toolCallName"] == "count_open_tasks"), None)
    assert call is not None, [e.get("toolCallName") for e in started]

    # The result must carry the *same* id as the call, which is what lets a client attach it to the
    # card it already rendered. Matching the specific call's id rather than counting a set of every
    # TOOL_CALL_* id: that set is non-empty even when the two disagree, so it cannot fail on the
    # decorrelation it is meant to catch. Scoped to this call, not `== 1`, because the model is free
    # to reach for a shared-state tool in the same turn.
    result_ids = {e["toolCallId"] for e in events if e["type"] == "TOOL_CALL_RESULT"}
    assert call["toolCallId"] in result_ids, (call["toolCallId"], result_ids)


@pytest.mark.skipif(not os.getenv("AK_DEMO_REASONING_MODEL"), reason="reasoning is opt-in; set AK_DEMO_REASONING_MODEL")
@pytest.mark.asyncio
async def test_reasoning_is_streamed_on_its_own_events_when_enabled(base_url):
    """Skipped by default, and deliberately so: the CI model emits no reasoning, and pointing this
    example at a reasoning model on every PR would make it slower and pricier for no coverage gain.

    Asserting that the two streams are *addressed* separately: reasoning arrives on
    REASONING_MESSAGE_* and carries message ids disjoint from the answer's, so a client renders the
    thinking block without splicing it into the reply. That reasoning text never rides in
    `StreamChunk.delta` (§4 rule 5) is a stronger claim than disjoint ids can support, and is pinned
    where it belongs, in `ak-py/tests/test_runtime_stream_events.py`.
    """
    events = await collect(base_url, run_input("Plan the order to do two errands in, briefly.", str(uuid.uuid4())))
    types = [event["type"] for event in events]

    assert "REASONING_MESSAGE_START" in types, types
    reasoning_ids = {e["messageId"] for e in events if e["type"].startswith("REASONING_MESSAGE_")}
    answer_ids = {e["messageId"] for e in events if e["type"].startswith("TEXT_MESSAGE_")}
    assert reasoning_ids and not (reasoning_ids & answer_ids), (reasoning_ids, answer_ids)
