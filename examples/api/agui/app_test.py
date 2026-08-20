"""
AG-UI protocol test for the agui example.

The shared `agentkernel.test` JSON request/response client cannot drive Server-Sent Events, and
AG-UI's request envelope is not Agent Kernel's chat body, so this test starts `app.py` and speaks
AG-UI to it directly with httpx.

It is the only end-to-end check that the whole outbound chain holds — a real framework adapter, the
runtime's event loop, `to_agui`, the SDK's `EventEncoder`, and a real HTTP surface. `ak-py`'s
`tests/test_agui_*.py` cover the same units against scripted runners; nothing there proves they
compose.

Assertions are structural (event ordering, frame shape, the presence of a state snapshot) rather than
semantic, so they do not depend on the model's exact wording. The one place the model's behaviour is
load-bearing is `test_state_round_trip`, which needs the agent to actually call `update_agui_state` —
that call *is* the capability, so a failure there is a real signal rather than flakiness to tolerate.
Requires OPENAI_API_KEY.
"""

import asyncio
import json
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
    """POST a run and parse every AG-UI event out of the SSE body."""
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
    """AG-UI has no open mode, so 401 is a live path on every route."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        assert (await client.get(f"{base_url}/agui/agents")).status_code == 401
        bad = {"Authorization": "Bearer nope"}
        assert (await client.post(f"{base_url}/agui", json=run_input("hi", "t"), headers=bad)).status_code == 401


@pytest.mark.asyncio
async def test_the_asset_route_serves_nothing_outside_assets(base_url):
    """The route matches names against the assets directory, so neither traversal nor an unknown
    name can reach a file. `..` must be sent percent-encoded — httpx normalises a literal
    `/assets/..` to `/` before it leaves the client, which would test nothing."""
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

    # The assistant message is bracketed and its content accumulates to something.
    assert "TEXT_MESSAGE_START" in types and "TEXT_MESSAGE_END" in types
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert text.strip()

    # Every frame carries its discriminator, and correlated events share a message id.
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
    """A 400 with an explanation, not a 200 whose first event is an error."""
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
    """The capability this example exists to demonstrate: the agent amends the shared state, the
    server streams the amended copy back, and the next run starts from what the client echoes."""
    thread_id = str(uuid.uuid4())

    events = await collect(
        base_url, run_input("Add exactly one task titled 'milk' to my task list.", thread_id, state={"tasks": []})
    )
    snapshots = [e for e in events if e["type"] == "STATE_SNAPSHOT"]
    assert snapshots, f"expected a StateSnapshot after the agent updated the state; got {[e['type'] for e in events]}"

    titles = [task["title"] for task in snapshots[-1]["snapshot"]["tasks"]]
    assert any("milk" in title.lower() for title in titles), titles

    # A run that changes nothing must not emit a snapshot — otherwise every turn re-syncs.
    quiet = await collect(base_url, run_input("Just say ok.", thread_id, state=snapshots[-1]["snapshot"]))
    assert not [e for e in quiet if e["type"] == "STATE_SNAPSHOT"]


@pytest.mark.asyncio
async def test_client_context_reaches_the_agent_as_tool_output(base_url):
    """context entries are pulled through a read-only tool, never injected into the prompt."""
    context = [{"description": "the user's favourite colour", "value": "vermilion"}]
    events = await collect(base_url, run_input("What is my favourite colour?", str(uuid.uuid4()), context=context))
    text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "vermilion" in text.lower(), text
