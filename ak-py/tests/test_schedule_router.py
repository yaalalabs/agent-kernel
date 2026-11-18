"""Schedule management routes (#629 Phase 4, on the principal since #603).

Mirror of tests/test_thread_router.py: the routes run in a FastAPI TestClient over the real
in-memory store and a fake provider, behind the identity dependency, so the whole status mapping
is observable: 404 when the capability is off, the 401 variants (the handler's for an absent
credential, the dependency's for a refused one), 403 before 404 on an unowned task, and 400 on an
unusable amendment.
"""

import subprocess
import sys

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import Principal, ScheduleSpec
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory, RequestAuthenticator
from agentkernel.schedule.handler import ScheduleRESTRequestHandler
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore

FUTURE_AT = "2030-06-01T09:00:00"

SCHEDULES_PATH = "/api/v1/schedules"
TOKENS = {"u1-token": "u1", "u2-token": "u2"}
AUTH = {"Authorization": "Bearer u1-token"}


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


class _Provider(IdentityProvider):
    """One token per test user, so every status below has a live path."""

    name = "test"

    async def authenticate(self, credential, context=None):
        subject = TOKENS.get(credential)
        if subject is None:
            raise AuthenticationError("unknown token")
        return Principal(subject=subject, provider=self.name, namespace="test")


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    """Stand the configured identity provider in: the handler requires one at construction."""
    provider = _Provider()
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))
    return provider


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


def _client() -> TestClient:
    """The routes behind the identity dependency, as ``RESTAPI`` mounts them."""
    app = FastAPI()
    app.include_router(ScheduleRESTRequestHandler().get_router(), dependencies=[Depends(RequestAuthenticator(_Provider()).dependency())])
    return TestClient(app, raise_server_exceptions=False)


def _principal(subject: str) -> Principal:
    return Principal(subject=subject, provider="test", namespace="test")


def _create(manager: ScheduleManager, **overrides):
    fields = {"principal": _principal("u1"), "prompt": "send the weekly report", "spec": ScheduleSpec(cron="0 9 * * 1"), "session_id": "s1"}
    fields.update(overrides)
    return manager.create(**fields)


def _amendment(**overrides) -> dict:
    body = {"prompt": "send the daily report", "cron": "0 9 * * *", "timezone": "UTC", "session_mode": "reuse", "status": "active"}
    body.update(overrides)
    return body


class TestConstruction:
    def test_refuses_to_build_without_an_identity_block(self, monkeypatch):
        """The routes enforce ownership on the caller, so with nobody able to authenticate they are a configuration error."""
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))

        with pytest.raises(AKConfigError, match="ScheduleRESTRequestHandler requires an identity block"):
            ScheduleRESTRequestHandler()


class TestUnconfiguredCapability:
    def test_every_route_reports_the_capability_as_off(self, scheduling_disabled):
        client = _client()

        assert client.get(SCHEDULES_PATH, headers=AUTH).status_code == 404
        assert client.get(f"{SCHEDULES_PATH}/t1", headers=AUTH).status_code == 404
        assert client.put(f"{SCHEDULES_PATH}/t1", json=_amendment(), headers=AUTH).status_code == 404
        assert client.delete(f"{SCHEDULES_PATH}/t1", headers=AUTH).status_code == 404

    def test_the_detail_names_the_missing_configuration(self, scheduling_disabled):
        response = _client().get(SCHEDULES_PATH, headers=AUTH)
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


class TestReads:
    def test_list_schedules_is_the_callers_own(self, scheduling):
        mine = _create(scheduling, principal=_principal("u1"))
        _create(scheduling, principal=_principal("u2"))

        response = _client().get(SCHEDULES_PATH, headers=AUTH)

        assert response.status_code == 200
        assert [task["task_id"] for task in response.json()["schedules"]] == [mine.task_id]

    def test_list_schedules_pages_through_a_cursor(self, scheduling):
        for _ in range(3):
            _create(scheduling)

        client = _client()
        first = client.get(SCHEDULES_PATH, params={"limit": 2}, headers=AUTH).json()
        second = client.get(SCHEDULES_PATH, params={"limit": 2, "cursor": first["next_cursor"]}, headers=AUTH).json()

        assert len(first["schedules"]) == 2
        assert first["next_cursor"] is not None
        assert len(second["schedules"]) == 1
        assert second["next_cursor"] is None

    def test_malformed_cursor_400(self, scheduling):
        assert _client().get(SCHEDULES_PATH, params={"cursor": "!!bad!!"}, headers=AUTH).status_code == 400

    def test_get_schedule_returns_the_full_record(self, scheduling):
        task = _create(scheduling)

        response = _client().get(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task.task_id
        assert body["spec"]["cron"] == "0 9 * * 1"
        assert body["status"] == "active"

    def test_get_missing_schedule_404(self, scheduling):
        assert _client().get(f"{SCHEDULES_PATH}/missing", headers=AUTH).status_code == 404

    def test_creation_is_not_exposed_as_a_route(self, scheduling):
        # A schedule is created by a chat request carrying a 'schedule' block, never here.
        assert _client().post(SCHEDULES_PATH, json={"prompt": "hi"}, headers=AUTH).status_code == 405


class TestAmendment:
    def test_put_replaces_the_rule_and_the_prompt(self, scheduling):
        task = _create(scheduling)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(cron=None, at=FUTURE_AT, timezone="Asia/Colombo"), headers=AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["prompt"] == "send the daily report"
        assert body["spec"] == {"at": FUTURE_AT, "cron": None, "timezone": "Asia/Colombo", "session_mode": "reuse"}

    def test_put_can_pause_a_schedule(self, scheduling):
        task = _create(scheduling)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(status="paused"), headers=AUTH)

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

        assert _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(**overrides), headers=AUTH).status_code == 400

    def test_a_prompt_only_body_cannot_keep_the_stored_rule(self, scheduling):
        """PUT has no partial form: ScheduleAmendment defaults timezone/session_mode and the route
        passes model_dump(), so a body carrying only a prompt reaches the manager with at and cron
        both None and fails the spec's one-of rule. The untouched-rule branch of _apply_amendment is
        a manager-level affordance, not this route's contract — docs/docs/advanced/scheduling.md
        says so, and this pins it."""
        task = _create(scheduling)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json={"prompt": "send the daily report"}, headers=AUTH)

        assert response.status_code == 400
        assert scheduling.get_task(task.task_id).spec.cron == "0 9 * * 1"  # unchanged

        # The same change through the manager keeps the rule and applies the prompt.
        amended = scheduling.update(task.task_id, {"prompt": "send the daily report"}, user_id="u1")
        assert amended.spec.cron == "0 9 * * 1"
        assert amended.prompt == "send the daily report"

    def test_amendment_rejected_by_the_body_model_is_422(self, scheduling):
        # prompt is required on the amendment body: FastAPI rejects the payload before the manager.
        task = _create(scheduling)

        assert _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json={"cron": "0 9 * * *"}, headers=AUTH).status_code == 422

    def test_amending_a_closed_schedule_400(self, scheduling):
        task = _create(scheduling)
        _client().delete(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(), headers=AUTH)

        assert response.status_code == 400
        assert "can no longer be changed" in response.json()["detail"]

    def test_amending_a_missing_schedule_404(self, scheduling):
        assert _client().put(f"{SCHEDULES_PATH}/missing", json=_amendment(), headers=AUTH).status_code == 404


class TestCancellation:
    def test_delete_returns_the_cancelled_schedule(self, scheduling):
        task = _create(scheduling)

        response = _client().delete(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["status"] == ScheduleStatus.CANCELLED.value
        # The record survives the cancellation as the audit trail.
        assert _client().get(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH).status_code == 200

    def test_deleting_a_missing_schedule_404(self, scheduling):
        assert _client().delete(f"{SCHEDULES_PATH}/missing", headers=AUTH).status_code == 404


class TestAuthentication:
    """The 401 variants: the handler's for an absent credential, the dependency's for a refused one."""

    def test_missing_header_401(self, scheduling):
        response = _client().get(SCHEDULES_PATH)

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_every_single_task_route_requires_a_caller(self, scheduling):
        task = _create(scheduling)
        client = _client()

        statuses = [
            client.get(f"{SCHEDULES_PATH}/{task.task_id}").status_code,
            client.put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment()).status_code,
            client.delete(f"{SCHEDULES_PATH}/{task.task_id}").status_code,
        ]

        assert statuses == [401, 401, 401]
        assert scheduling.get_task(task.task_id).prompt == "send the weekly report"

    def test_bad_token_401(self, scheduling):
        response = _client().get(SCHEDULES_PATH, headers={"Authorization": "Bearer bad-token"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Unauthorized"

    def test_non_bearer_scheme_401(self, scheduling):
        response = _client().get(SCHEDULES_PATH, headers={"Authorization": "Basic u1-token"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authorization header"

    def test_empty_token_401(self, scheduling):
        response = _client().get(SCHEDULES_PATH, headers={"Authorization": "Bearer "})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authorization header"

    def test_lowercase_bearer_scheme_accepted(self, scheduling):
        response = _client().get(SCHEDULES_PATH, headers={"Authorization": "bearer u1-token"})

        assert response.status_code == 200


class TestOwnership:
    def test_a_user_id_query_cannot_widen_the_listing(self, scheduling):
        mine = _create(scheduling, principal=_principal("u1"))
        _create(scheduling, principal=_principal("u2"))

        # The caller asks for u2's schedules; the listing stays the caller's own.
        response = _client().get(SCHEDULES_PATH, params={"user_id": "u2"}, headers=AUTH)

        assert response.status_code == 200
        assert [task["task_id"] for task in response.json()["schedules"]] == [mine.task_id]

    def test_get_owned_schedule_200(self, scheduling):
        task = _create(scheduling, principal=_principal("u1"))

        response = _client().get(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

        assert response.status_code == 200

    def test_get_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, principal=_principal("u2"))

        response = _client().get(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

        assert response.status_code == 403
        assert response.json()["detail"] == "Schedule is not owned by the authorised user"

    def test_amending_an_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, principal=_principal("u2"))

        response = _client().put(f"{SCHEDULES_PATH}/{task.task_id}", json=_amendment(), headers=AUTH)

        assert response.status_code == 403

    def test_cancelling_an_unowned_schedule_403(self, scheduling):
        task = _create(scheduling, principal=_principal("u2"))

        response = _client().delete(f"{SCHEDULES_PATH}/{task.task_id}", headers=AUTH)

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
