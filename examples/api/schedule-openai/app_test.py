import asyncio
import datetime
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

# Deferring a request never reaches the agent, so every test here runs without an LLM call.
FUTURE_AT = "2030-01-31T09:00:00"
PAST_AT = "2020-01-01T09:00:00"
WEEKLY_CRON = "0 9 * * 1"


class APITestClient:
    def __init__(self, url):
        self.url = url

    async def chat(self, prompt, session_id, user_id=None, schedule=None):
        payload = {"prompt": prompt, "session_id": session_id, "agent": "assistant"}
        if user_id is not None:
            payload["user_id"] = user_id
        if schedule is not None:
            payload["schedule"] = schedule
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(f"{self.url}/api/v1/chat", json=payload)

    async def request(self, method, path, json=None):
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.request(method, f"{self.url}{path}", json=json)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_deferred_request_is_acknowledged_with_202(http_client):
    print("test_deferred_request_is_acknowledged_with_202")
    resp = await http_client.chat(
        "Send me the daily summary",
        session_id="ses-one-time",
        user_id="alice",
        schedule={"at": FUTURE_AT, "timezone": "Asia/Colombo"},
    )
    assert resp.status_code == 202
    assert "SCHEDULED" in resp.json()["result"]
    assert resp.json()["session_id"] == "ses-one-time"


@pytest.mark.asyncio
async def test_recurring_request_is_acknowledged_with_202(http_client):
    print("test_recurring_request_is_acknowledged_with_202")
    resp = await http_client.chat(
        "Send the weekly report",
        session_id="ses-recurring",
        user_id="alice",
        schedule={"cron": WEEKLY_CRON, "timezone": "Asia/Colombo", "session_mode": "new"},
    )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_past_timestamp_is_rejected_at_creation(http_client):
    print("test_past_timestamp_is_rejected_at_creation")
    resp = await http_client.chat(
        "Send me the daily summary", session_id="ses-past", user_id="alice", schedule={"at": PAST_AT}
    )
    assert resp.status_code == 400
    assert "must be in the future" in resp.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_scheduling_requires_a_user_id(http_client):
    print("test_scheduling_requires_a_user_id")
    resp = await http_client.chat("Send me the daily summary", session_id="ses-anon", schedule={"at": FUTURE_AT})
    assert resp.status_code == 400
    assert "user identity" in resp.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_schedule_lifecycle_over_the_management_routes(http_client):
    print("test_schedule_lifecycle_over_the_management_routes")
    session_id = str(uuid.uuid4())
    resp = await http_client.chat(
        "Send the weekly report",
        session_id=session_id,
        user_id="alice",
        schedule={"cron": WEEKLY_CRON, "timezone": "Asia/Colombo"},
    )
    assert resp.status_code == 202

    listed = await http_client.request("GET", "/api/v1/schedules?user_id=alice")
    assert listed.status_code == 200
    mine = [task for task in listed.json()["schedules"] if task["session_id"] == session_id]
    assert len(mine) == 1
    task_id = mine[0]["task_id"]
    assert mine[0]["spec"]["cron"] == WEEKLY_CRON
    assert mine[0]["status"] == "active"

    read = await http_client.request("GET", f"/api/v1/schedules/{task_id}")
    assert read.status_code == 200
    assert read.json()["task_id"] == task_id

    # PUT carries the full amendable state: the omitted cron is cleared by the new 'at'.
    amended = await http_client.request(
        "PUT",
        f"/api/v1/schedules/{task_id}",
        json={
            "prompt": "Send the daily report",
            "at": FUTURE_AT,
            "timezone": "UTC",
            "session_mode": "reuse",
            "status": "paused",
        },
    )
    assert amended.status_code == 200
    assert amended.json()["prompt"] == "Send the daily report"
    assert amended.json()["spec"] == {"at": FUTURE_AT, "cron": None, "timezone": "UTC", "session_mode": "reuse"}
    assert amended.json()["status"] == "paused"

    cancelled = await http_client.request("DELETE", f"/api/v1/schedules/{task_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # The record survives the cancellation as the audit trail.
    assert (await http_client.request("GET", f"/api/v1/schedules/{task_id}")).status_code == 200


@pytest.mark.asyncio
async def test_management_routes_report_unknown_schedules(http_client):
    print("test_management_routes_report_unknown_schedules")
    assert (await http_client.request("GET", "/api/v1/schedules/missing")).status_code == 404
    assert (await http_client.request("DELETE", "/api/v1/schedules/missing")).status_code == 404


@pytest.mark.asyncio
async def test_one_time_occurrence_fires_and_completes_the_task(http_client):
    print("test_one_time_occurrence_fires_and_completes_the_task")
    fires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    resp = await http_client.chat("Say hello", session_id=str(uuid.uuid4()), user_id="alice", schedule={"at": fires_at})
    assert resp.status_code == 202
    task_id = resp.json()["result"].split('"scheduled_task_id": "')[1].split('"')[0]

    # The occurrence records itself before the agent runs, so this does not wait on an LLM call.
    for _ in range(30):
        task = (await http_client.request("GET", f"/api/v1/schedules/{task_id}")).json()
        if task["trigger_count"] == 1:
            break
        await asyncio.sleep(1)

    assert task["trigger_count"] == 1
    assert task["status"] == "completed"  # a one-time schedule has no further occurrences
    assert task["last_triggered_at"] is not None
    assert task["last_request_id"] is not None
