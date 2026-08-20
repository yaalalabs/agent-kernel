"""Tests for the deployed serverless scheduling example.

Set AK_TEST_ENDPOINT to the module's `agent_invoke_url` output (the chat route). The management
routes are derived from it, so both live behind the same API Gateway stage.

These are integration tests against a real deployment: they create real EventBridge schedules and
cancel them afterwards. Nothing here waits for an occurrence to fire — a schedule far enough in the
future to be safe is also too far away to await — so the assertions cover the registration, the 202
contract, the management surface, and validation.

Note the management routes are the custom `Lambda.register` routes in lambda_request_handler.py,
not `ScheduleRESTRequestHandler`: the serverless router is not FastAPI. That is why the task id
travels as a query parameter or in the body rather than as a path segment.
"""

import asyncio
import json
import os
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

USER_ID = "alice"
# Deliberately far in the future: the assertions never wait for a firing.
FUTURE_AT = "2035-01-31T09:00:00"


class ScheduleTestClient:
    """Thin client over the chat route and the custom management routes."""

    def __init__(self, chat_url: str):
        self.chat_url = chat_url.rstrip("/")
        # /api/v1/chat -> /api/v1/schedules
        self.schedules_url = self.chat_url.rsplit("/", 1)[0] + "/schedules"

    async def chat(self, prompt: str, session_id: str, schedule: dict | None = None) -> httpx.Response:
        payload = {"prompt": prompt, "session_id": session_id, "user_id": USER_ID}
        if schedule is not None:
            payload["schedule"] = schedule
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Retry 5xx and timeouts: Lambda cold starts can exceed the gateway timeout.
            for attempt in range(3):
                try:
                    response = await client.post(self.chat_url, json=payload)
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise
                    continue
                if response.status_code < 500 or attempt == 2:
                    return response
                await asyncio.sleep(5)
            return response

    async def list_schedules(self) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.get(self.schedules_url, params={"user_id": USER_ID})

    async def get_schedule(self, task_id: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.get(f"{self.schedules_url}/get", params={"user_id": USER_ID, "task_id": task_id})

    async def amend_schedule(self, task_id: str, body: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(
                f"{self.schedules_url}/amend", json={"task_id": task_id, "user_id": USER_ID, **body}
            )

    async def cancel_schedule(self, task_id: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.schedules_url}/cancel", json={"task_id": task_id, "user_id": USER_ID})


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    assert endpoint, "Set AK_TEST_ENDPOINT to the deployment's agent_invoke_url"
    yield ScheduleTestClient(endpoint)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def cleanup(client):
    """Cancel every schedule this user still owns, however the tests ended.

    Not tidiness: `terraform destroy` deletes the EventBridge schedule *group*, and AWS refuses to
    delete a group that still holds schedules. A test that fails midway would otherwise leave one
    behind and break the next run's destroy step, so this runs even on failure.
    """
    yield
    listing = await client.list_schedules()
    if listing.status_code != 200:
        return
    for task in listing.json().get("schedules", []):
        if task["status"] in ("active", "paused"):
            await client.cancel_schedule(task["task_id"])


def _task_id_of(response: httpx.Response) -> str:
    """Pull the task id out of a 202 acknowledgement, whose `result` is a JSON string."""
    ack = json.loads(response.json()["result"])
    assert ack["status"] == "SCHEDULED", ack
    return ack["scheduled_task_id"]


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_a_plain_chat_still_runs_immediately(client):
    response = await client.chat("Say the single word: ready", session_id=str(uuid.uuid4()))
    assert response.status_code == 200, response.text
    assert response.json().get("result")


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_a_one_time_schedule_is_acknowledged_with_202(client):
    response = await client.chat(
        "Send me the daily summary",
        session_id=str(uuid.uuid4()),
        schedule={"at": FUTURE_AT, "timezone": "Asia/Colombo"},
    )
    # 202, not 200: accepted, not executed. The status survives the queue round trip because the
    # agent runner forwards it and the response store keeps it.
    assert response.status_code == 202, response.text
    task_id = _task_id_of(response)

    read = await client.get_schedule(task_id)
    assert read.status_code == 200, read.text
    task = read.json()
    assert task["status"] == "active"
    assert task["spec"]["at"] == FUTURE_AT
    assert task["user_id"] == USER_ID
    assert task["trigger_count"] == 0

    assert (await client.cancel_schedule(task_id)).json()["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.order(3)
async def test_a_recurring_schedule_can_be_amended_and_cancelled(client):
    response = await client.chat(
        "Send the weekly report",
        session_id=str(uuid.uuid4()),
        schedule={"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"},
    )
    assert response.status_code == 202, response.text
    task_id = _task_id_of(response)

    # Full replacement rather than a merge, so every value is sent even when unchanged.
    amended = await client.amend_schedule(
        task_id,
        {
            "prompt": "Send the weekly report",
            "cron": "0 8 * * 1",
            "timezone": "Asia/Colombo",
            "session_mode": "new",
            "status": "paused",
        },
    )
    assert amended.status_code == 200, amended.text
    assert amended.json()["spec"]["cron"] == "0 8 * * 1"
    assert amended.json()["status"] == "paused"

    listing = await client.list_schedules()
    assert listing.status_code == 200, listing.text
    assert task_id in [task["task_id"] for task in listing.json()["schedules"]]

    # The record survives cancellation as the audit trail.
    cancelled = await client.cancel_schedule(task_id)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_an_unusable_schedule_is_rejected_at_creation(client):
    response = await client.chat(
        "Send me the daily summary",
        session_id=str(uuid.uuid4()),
        schedule={"at": "2020-01-01T09:00:00"},
    )
    # Rejected at creation rather than silently never firing.
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
@pytest.mark.order(5)
async def test_the_agent_can_schedule_work_itself(client):
    # Runs now; the agent is expected to call create_schedule rather than answer as if it had run.
    response = await client.chat(
        "Every weekday at 8am in Asia/Colombo, remind me to review the overnight alerts.",
        session_id=str(uuid.uuid4()),
    )
    assert response.status_code == 200, response.text

    listing = await client.list_schedules()
    active = [task for task in listing.json()["schedules"] if task["status"] == "active"]
    assert active, "expected the agent to have registered a schedule via create_schedule"

    for task in active:
        await client.cancel_schedule(task["task_id"])
