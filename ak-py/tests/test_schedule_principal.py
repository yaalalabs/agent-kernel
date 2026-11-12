"""Scheduled-task ownership on the principal, over the real REST wiring (#603, plan iteration 10).

``RESTAPI.build_app`` installs the identity dependency, so a ``static`` provider resolving two
tokens stands in for the callers: the task a chat request created for one principal is readable,
amendable and cancellable by that principal alone, a listing is the caller's own, and a request
nothing authenticated is refused on every route. The fire-time level re-check joins this file in
plan iteration 19.
"""

import pytest
from fastapi.testclient import TestClient

from agentkernel.api.http import RESTAPI
from agentkernel.core.config import AKConfig
from agentkernel.core.model import BaseRunRequest, Principal, ScheduleSpec
from agentkernel.identity import IdentityProviderFactory
from agentkernel.schedule.handler import ScheduleRESTRequestHandler
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore
from agentkernel.secret import SecretManager

SCHEDULES = "/api/v1/schedules"
ALICE = Principal(subject="alice", provider="static", namespace="static", groups=["ops"])
BOB = Principal(subject="bob", provider="static", namespace="static")
ALICE_AUTH = {"Authorization": "Bearer alice-secret"}
BOB_AUTH = {"Authorization": "Bearer bob-secret"}
AMENDMENT = {"prompt": "send the daily report", "cron": "0 9 * * *", "timezone": "UTC", "session_mode": "reuse", "status": "active"}

IDENTITY_YAML = """
identity:
  provider:
    type: static
    static:
      principals:
        ALICE_TOKEN:
          subject: alice
          groups: [ops]
        BOB_TOKEN:
          subject: bob
"""


class _RecordingProvider(ScheduleProvider):
    """Stands in for a real trigger backend: registers nothing, remembers nothing."""

    def create(self, task, body_template):
        return f"ref-{task.task_id}"

    def update(self, task, body_template):
        pass

    def delete(self, provider_ref):
        pass

    def get(self, provider_ref):
        return {"provider_ref": provider_ref}


@pytest.fixture
def served(monkeypatch, tmp_path):
    """The schedule routes on a ``RESTAPI`` app whose identity dependency runs the static provider."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(IDENTITY_YAML)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    monkeypatch.setenv("ALICE_TOKEN", "alice-secret")
    monkeypatch.setenv("BOB_TOKEN", "bob-secret")
    AKConfig._reset()
    SecretManager.reset()
    IdentityProviderFactory.reset()
    store = InMemoryScheduleStore()
    store.clear()
    manager = ScheduleManager(provider=_RecordingProvider(), store=store)
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: manager))
    try:
        yield TestClient(RESTAPI.build_app(handlers=[ScheduleRESTRequestHandler()]), raise_server_exceptions=False), manager
    finally:
        store.clear()
        IdentityProviderFactory.reset()
        SecretManager.reset()
        AKConfig._reset()


def _create(manager: ScheduleManager, principal: Principal, session_id: str = "s1"):
    """A task the way the chat route creates one: from a request carrying a schedule block."""
    req = BaseRunRequest(prompt="send the weekly report", session_id=session_id, principal=principal, schedule=ScheduleSpec(cron="0 9 * * 1"))
    return manager.create_from_request(req)


class TestOwnership:
    def test_a_task_belongs_to_the_principal_whose_request_created_it(self, served):
        client, manager = served
        task = _create(manager, ALICE)

        mine = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH)
        theirs = client.get(f"{SCHEDULES}/{task.task_id}", headers=BOB_AUTH)

        assert mine.status_code == 200
        assert (mine.json()["user_id"], mine.json()["principal"]["subject"]) == ("alice", "alice")
        assert theirs.status_code == 403

    def test_a_listing_is_the_callers_own_tasks(self, served):
        client, manager = served
        mine = _create(manager, ALICE, "s1")
        _create(manager, BOB, "s2")

        # The caller asks for bob's tasks; the listing stays the caller's own.
        listing = client.get(SCHEDULES, params={"user_id": "bob"}, headers=ALICE_AUTH)

        assert listing.status_code == 200
        assert [task["task_id"] for task in listing.json()["schedules"]] == [mine.task_id]

    def test_amending_and_cancelling_require_the_owner(self, served):
        client, manager = served
        task = _create(manager, ALICE)

        assert client.put(f"{SCHEDULES}/{task.task_id}", json=AMENDMENT, headers=BOB_AUTH).status_code == 403
        assert client.delete(f"{SCHEDULES}/{task.task_id}", headers=BOB_AUTH).status_code == 403
        assert manager.get_task(task.task_id).prompt == "send the weekly report"

        assert client.put(f"{SCHEDULES}/{task.task_id}", json=AMENDMENT, headers=ALICE_AUTH).json()["prompt"] == "send the daily report"
        assert client.delete(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()["status"] == ScheduleStatus.CANCELLED.value


class TestAuthentication:
    def test_every_route_refuses_a_request_nothing_authenticated(self, served):
        client, manager = served
        task = _create(manager, ALICE)

        responses = [
            client.get(SCHEDULES),
            client.get(f"{SCHEDULES}/{task.task_id}"),
            client.put(f"{SCHEDULES}/{task.task_id}", json=AMENDMENT),
            client.delete(f"{SCHEDULES}/{task.task_id}"),
        ]

        assert [response.status_code for response in responses] == [401, 401, 401, 401]
        assert {response.json()["detail"] for response in responses} == {"Authentication required"}
        assert manager.get_task(task.task_id).status == ScheduleStatus.ACTIVE

    def test_a_refused_credential_is_the_dependencys_401(self, served):
        client, _ = served

        response = client.get(SCHEDULES, headers={"Authorization": "Bearer nobody"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Unauthorized"
