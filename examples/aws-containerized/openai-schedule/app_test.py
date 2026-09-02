"""Tests for the deployed scheduling example.

Set AK_TEST_ENDPOINT to the module's `agent_invoke_url` output (the chat route). The schedule
management routes are derived from it, so both live behind the same API Gateway stage.

These are integration tests against a real deployment: they create real EventBridge schedules and
clean up after themselves. Nothing here waits for an occurrence to actually fire — a schedule far
enough in the future to be safe is also too far away to await, so the assertions cover the
registration, the 202 contract, and the management surface.
"""

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
    """Thin client over the chat route and the schedule management routes."""

    def __init__(self, chat_url: str):
        self.chat_url = chat_url.rstrip("/")
        # /api/v1/chat -> /api/v1/schedules
        self.schedules_url = self.chat_url.rsplit("/", 1)[0] + "/schedules"
        self.session_id = str(uuid.uuid4())

    async def chat(self, prompt: str, schedule: dict | None = None) -> httpx.Response:
        payload = {"prompt": prompt, "session_id": self.session_id, "user_id": USER_ID}
        if schedule is not None:
            payload["schedule"] = schedule
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await client.post(self.chat_url, json=payload)

    async def list_schedules(self) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.get(self.schedules_url, params={"user_id": USER_ID})

    async def get_schedule(self, task_id: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.get(f"{self.schedules_url}/{task_id}")

    async def amend_schedule(self, task_id: str, body: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.put(f"{self.schedules_url}/{task_id}", json=body)

    async def cancel_schedule(self, task_id: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.delete(f"{self.schedules_url}/{task_id}")


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
    import json

    ack = json.loads(response.json()["result"])
    assert ack["status"] == "SCHEDULED", ack
    return ack["scheduled_task_id"]


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_a_plain_chat_still_runs_immediately(client):
    response = await client.chat("Say the single word: ready")
    assert response.status_code == 200
    assert response.json().get("result")


@pytest.mark.asyncio
@pytest.mark.order(2)
async def test_a_one_time_schedule_is_acknowledged_with_202(client):
    response = await client.chat(
        "Send me the daily summary",
        schedule={"at": FUTURE_AT, "timezone": "Asia/Colombo"},
    )
    # 202, not 200: the request was accepted, not executed. The status survives the queue round
    # trip as the `status_code` attribute the agent runner forwards.
    assert response.status_code == 202, response.text
    task_id = _task_id_of(response)

    read = await client.get_schedule(task_id)
    assert read.status_code == 200
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
        schedule={"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"},
    )
    assert response.status_code == 202, response.text
    task_id = _task_id_of(response)

    # PUT replaces the full amendable state rather than merging, so every value is sent.
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
    assert listing.status_code == 200
    assert task_id in [task["task_id"] for task in listing.json()["schedules"]]

    # The record survives cancellation as the audit trail.
    cancelled = await client.cancel_schedule(task_id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.order(4)
async def test_an_unusable_schedule_is_rejected_at_creation(client):
    response = await client.chat(
        "Send me the daily summary",
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
    )
    assert response.status_code == 200, response.text

    listing = await client.list_schedules()
    active = [task for task in listing.json()["schedules"] if task["status"] == "active"]
    assert active, "expected the agent to have registered a schedule via create_schedule"

    for task in active:
        await client.cancel_schedule(task["task_id"])
