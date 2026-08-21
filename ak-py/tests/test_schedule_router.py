"""Schedule management routes (#629 Phase 4).

Mirror of tests/test_thread_router.py: the routes run in a FastAPI TestClient over the real
in-memory store and a fake provider, so the whole status mapping is observable — 404 when the
capability is off, the three 401 variants from the shared authorised base, 403 before 404 on an
unowned task, and 400 on an unusable amendment.
"""

import subprocess
import sys
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentkernel.auth import Authoriser
from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.util.factory import AKConfigError
from agentkernel.schedule.handler import ScheduleRESTRequestHandler
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore

FUTURE_AT = "2030-06-01T09:00:00"

SCHEDULES_PATH = "/api/v1/schedules"


class RecordingScheduleProvider(ScheduleProvider):
    """Stands in for a real trigger backend: registers nothing, remembers everything."""

    def __init__(self):
        self.deleted: list[str] = []

    def create(self, task, body_template):
        return f"ref-{task.task_id}"

    def update(self, task, body_template):
        pass

    def delete(self, provider_ref):
        self.deleted.append(provider_ref)

    def get(self, provider_ref):
        return {"provider_ref": provider_ref}


class StaticAuthoriser(Authoriser):
    """Test authoriser: token 'good-token' resolves to user 'u1', anything else is rejected."""

    def authorise(self, token: str) -> Optional[str]:
        return "u1" if token == "good-token" else None


@pytest.fixture
def scheduling(monkeypatch):
    """Serve the routes from a manager over the real in-memory store and a fake provider."""
    store = InMemoryScheduleStore()
    store.clear()
    manager = ScheduleManager(provider=RecordingScheduleProvider(), store=store)
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: manager))
    yield manager
    store.clear()


@pytest.fixture
def scheduling_disabled(monkeypatch):
    """No 'schedule' block: the manager reports the capability as unconfigured."""
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: None))


def _client(authoriser: Optional[Authoriser] = None) -> TestClient:
    app = FastAPI()
    app.include_router(ScheduleRESTRequestHandler(authoriser=authoriser).get_router())
    return TestClient(app, raise_server_exceptions=False)


def _create(manager: ScheduleManager, **overrides):
    fields = {"user_id": "u1", "prompt": "send the weekly report", "spec": ScheduleSpec(cron="0 9 * * 1"), "session_id": "s1"}
    fields.update(overrides)
    return manager.create(**fields)


def _amendment(**overrides) -> dict:
    body = {"prompt": "send the daily report", "cron": "0 9 * * *", "timezone": "UTC", "session_mode": "reuse", "status": "active"}
    body.update(overrides)
    return body


class TestUnconfiguredCapability:
    def test_every_route_reports_the_capability_as_off(self, scheduling_disabled):
        client = _client()

        assert client.get(SCHEDULES_PATH).status_code == 404
        assert client.get(f"{SCHEDULES_PATH}/t1").status_code == 404
        assert client.put(f"{SCHEDULES_PATH}/t1", json=_amendment()).status_code == 404
        assert client.delete(f"{SCHEDULES_PATH}/t1").status_code == 404

    def test_the_detail_names_the_missing_configuration(self, scheduling_disabled):
        response = _client().get(SCHEDULES_PATH)
        assert response.json()["detail"] == "Scheduling is not configured"


class TestImportIsolation:
    def test_importing_the_manager_does_not_load_the_fastapi_handler(self):
        """The ChatService reaches the capability through schedule.manager, in processes that need
        not have the api extra installed — so importing it must not pull this handler in with it."""
        script = (
            "import sys, agentkernel.schedule.manager;"
            "assert 'agentkernel.schedule.handler' not in sys.modules, 'the handler was imported eagerly';"
            "assert 'fastapi' not in sys.modules, 'fastapi was imported eagerly'"
        )

        assert subprocess.run([sys.executable, "-c", script]).returncode == 0


class TestRoutesOpen:
    """Schedule routes without an Authoriser (open access)."""

    def test_list_schedules_by_user(self, scheduling):
        mine = _create(scheduling, user_id="u1")
        _create(scheduling, user_id="u2")

        response = _client().get(SCHEDULES_PATH, params={"user_id": "u1"})

        assert response.status_code == 200
        assert [task["task_id"] for task in response.json()["schedules"]] == [mine.task_id]

    def test_list_schedules_pages_through_a_cursor(self, scheduling):
        for _ in range(3):
            _create(scheduling)

        client = _client()
        first = client.get(SCHEDULES_PATH, params={"limit": 2}).json()
        second = client.get(SCHEDULES_PATH, params={"limit": 2, "cursor": first["next_cursor"]}).json()

        assert len(first["schedules"]) == 2
        assert first["next_cursor"] is not None
        assert len(second["schedules"]) == 1
        assert second["next_cursor"] is None

    def test_malformed_cursor_400(self, scheduling):
        assert _client().get(SCHEDULES_PATH, params={"cursor": "!!bad!!"}).status_code == 400

    def test_get_schedule_returns_the_full_record(self, scheduling):
        task = _create(scheduling)

        response = _client().get(f"{SCHEDULES_PATH}/{task.task_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task.task_id
        assert body["spec"]["cron"] == "0 9 * * 1"
        assert body["status"] == "active"

    def test_get_missing_schedule_404(self, scheduling):
        assert _client().get(f"{SCHEDULES_PATH}/missing").status_code == 404

    def test_creation_is_not_exposed_as_a_route(self, scheduling):
        # A schedule is created by a chat request carrying a 'schedule' block, never here.
        assert _client().post(SCHEDULES_PATH, json={"prompt": "hi"}).status_code == 405


class TestAmendment:
    def test_put_replaces_the_rule_and_the_prompt(self, scheduling):
        task = _create(scheduling)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(cron=None, at=FUTURE_AT, timezone="Asia/Colombo"))

        assert response.status_code == 200
        body = response.json()
        assert body["prompt"] == "send the daily report"
        assert body["spec"] == {"at": FUTURE_AT, "cron": None, "timezone": "Asia/Colombo", "session_mode": "reuse"}

    def test_put_can_pause_a_schedule(self, scheduling):
        task = _create(scheduling)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(status="paused"))

        assert response.json()["status"] == "paused"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"at": FUTURE_AT},  # both at and cron: the spec's one-of rule
            {"cron": None},  # neither
            {"timezone": "Mars/Olympus"},
            {"cron": "0 9 * *"},  # not a 5-field expression
            {"prompt": ""},
        ],
    )
    def test_unusable_amendment_400(self, scheduling, overrides):
        task = _create(scheduling)

        assert _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(**overrides)).status_code == 400

    def test_amendment_rejected_by_the_body_model_is_422(self, scheduling):
        # prompt is required on the amendment body: FastAPI rejects the payload before the manager.
        task = _create(scheduling)

        assert _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json={"cron": "0 9 * * *"}).status_code == 422

    def test_amending_a_closed_schedule_400(self, scheduling):
        task = _create(scheduling)
        _client().delete(f"{SCHEDULES_PATH}/{task.task_id}")

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment())

        assert response.status_code == 400
        assert "can no longer be changed" in response.json()["detail"]

    def test_amending_a_missing_schedule_404(self, scheduling):
        assert _client().put(f"{SCHEDULES_PATH}/missing", json=_amendment()).status_code == 404


class TestCancellation:
    def test_delete_returns_the_cancelled_schedule(self, scheduling):
        task = _create(scheduling)

        response = _client().delete(f"{SCHEDULES_PATH}/{task.task_id}")

        assert response.status_code == 200
        assert response.json()["status"] == ScheduleStatus.CANCELLED.value
        # The record survives the cancellation as the audit trail.
        assert _client().get(f"{SCHEDULES_PATH}/{task.task_id}").status_code == 200

    def test_deleting_a_missing_schedule_404(self, scheduling):
        assert _client().delete(f"{SCHEDULES_PATH}/missing").status_code == 404


class TestRoutesAuthorised:
    """Schedule routes protected by an Authoriser."""

    def test_missing_token_401(self, scheduling):
        assert _client(StaticAuthoriser()).get(SCHEDULES_PATH).status_code == 401

    def test_bad_token_401(self, scheduling):
        response = _client(StaticAuthoriser()).get(SCHEDULES_PATH, headers={"Authorization": "Bearer bad-token"})
        assert response.status_code == 401

    def test_non_bearer_scheme_401(self, scheduling):
        response = _client(StaticAuthoriser()).get(SCHEDULES_PATH, headers={"Authorization": "Basic good-token"})
        assert response.status_code == 401

    def test_empty_token_401(self, scheduling):
        response = _client(StaticAuthoriser()).get(SCHEDULES_PATH, headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_lowercase_bearer_scheme_accepted(self, scheduling):
        response = _client(StaticAuthoriser()).get(SCHEDULES_PATH, headers={"Authorization": "bearer good-token"})
        assert response.status_code == 200

    def test_listing_forced_to_the_authorised_user(self, scheduling):
        mine = _create(scheduling, user_id="u1")
        _create(scheduling, user_id="u2")

        # The caller asks for u2's schedules but the token resolves to u1.
        response = _client(StaticAuthoriser()).get(SCHEDULES_PATH, params={"user_id": "u2"}, headers={"Authorization": "Bearer good-token"})

        assert response.status_code == 200
        assert [task["task_id"] for task in response.json()["schedules"]] == [mine.task_id]

    def test_get_owned_schedule_200(self, scheduling):
        task = _create(scheduling, user_id="u1")

        response = _client(StaticAuthoriser()).get(f"{SCHEDULES_PATH}/{task.task_id}", headers={"Authorization": "Bearer good-token"})

        assert response.status_code == 200

    def test_get_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, user_id="u2")

        response = _client(StaticAuthoriser()).get(f"{SCHEDULES_PATH}/{task.task_id}", headers={"Authorization": "Bearer good-token"})

        assert response.status_code == 403
        assert response.json()["detail"] == "Schedule is not owned by the authorised user"

    def test_amending_an_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, user_id="u2")

        response = _client(StaticAuthoriser()).put(
            f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(), headers={"Authorization": "Bearer good-token"}
        )

        assert response.status_code == 403

    def test_cancelling_an_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, user_id="u2")

        response = _client(StaticAuthoriser()).delete(f"{SCHEDULES_PATH}/{task.task_id}", headers={"Authorization": "Bearer good-token"})

        assert response.status_code == 403


class TestMountTimeValidation:
    """Mounting the routes is what validates the configured backends (no other layer does)."""

    @pytest.fixture
    def scheduling(self):
        """Configure the capability on the live AKConfig singleton, which ScheduleManager reads."""

        def _configure(**fields):
            AKConfig.get().schedule = _ScheduleConfig.model_validate(fields)
            return AKConfig.get().schedule

        yield _configure
        AKConfig.get().schedule = None
        ScheduleManager.reset()

    def test_mounting_builds_the_manager(self, scheduling):
        scheduling()

        ScheduleRESTRequestHandler().get_router()

        assert ScheduleManager._instance is not None

    def test_unusable_configuration_fails_the_mount(self, scheduling):
        scheduling(provider={"type": "not-a-provider"})

        with pytest.raises(AKConfigError, match="unknown schedule provider type"):
            ScheduleRESTRequestHandler().get_router()

    def test_mounting_without_the_capability_configured_is_allowed(self):
        """Routes mount on an unconfigured app and report 404 per request, as the thread routes do."""
        routes = {route.path for route in ScheduleRESTRequestHandler().get_router().routes}

        assert ScheduleManager._instance is None
        assert routes == {"/api/v1/schedules", "/api/v1/schedules/{task_id}"}
