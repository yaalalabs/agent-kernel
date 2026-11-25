"""Scheduled-task ownership on the principal, over the real REST wiring (#603, plan iteration 10).

``RESTAPI.build_app`` installs the identity dependency, so a ``static`` provider resolving two
tokens stands in for the callers: the task a chat request created for one principal is readable,
amendable and cancellable by that principal alone, a listing is the caller's own, and a request
nothing authenticated is refused on every route.

Plan iteration 19 adds the fire-time re-check (``TestFireTimeAccess``): an occurrence runs as the
task's owner, so with an ``authorization`` block the owner's level is asked again when it fires, and
an occurrence the owner may no longer run is skipped and leaves the reason on the task.
"""

import json

import pytest
from fastapi.testclient import TestClient

from agentkernel.api.http import RESTAPI
from agentkernel.core.chat_service import ChatService, SkippedOccurrenceReply
from agentkernel.core.config import AKConfig
from agentkernel.core.model import BaseRunRequest, Principal, ScheduleSpec
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.identity import IdentityProviderFactory
from agentkernel.schedule.handler import ScheduleRESTRequestHandler
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduleStatus
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


class TestFireTimeAccess:
    """An occurrence acts as the task's owner, unattended (#603, plan iteration 19). The owner's grants are read
    when it fires, not when the task was created, so taking the grant away stops the task: the occurrence is
    skipped, and the task the owner reads back says why.

    The real manager and store, the real access gate over a static policy that the test rewrites, and the body a
    provider would deliver, run through the chat service as the queue runner runs it."""

    WEEKLY = {"subjects": ["user:alice"], "agents": ["reports"], "level": "read"}

    @pytest.fixture
    def hosting(self, served, surface_agent):
        runtime = Runtime(InMemorySessionStore())
        runtime.register(surface_agent("reports"))
        with runtime:
            yield served

    @staticmethod
    def _fire(manager: ScheduleManager, task_id: str, request_id: str = "r-1"):
        """Deliver one occurrence of a task as its provider would: the frozen body, with the occurrence values in."""
        frozen = manager._build_trigger_body(manager.get_task(task_id))
        body = json.loads(frozen.replace(TOKEN_REQUEST_ID, request_id).replace(TOKEN_OCCURRENCE_TIME, "2030-06-03T09:00:00Z"))
        return ChatService().process_chat_request(BaseRunRequest.model_validate(body))

    @staticmethod
    def _create(manager: ScheduleManager, principal: Principal = ALICE):
        req = BaseRunRequest(
            prompt="send the weekly report", agent="reports", session_id="s1", principal=principal, schedule=ScheduleSpec(cron="0 9 * * 1")
        )
        return manager.create_from_request(req)

    def test_an_occurrence_runs_while_its_owner_holds_a_level(self, hosting, authorization):
        client, manager = hosting
        authorization(grants=[self.WEEKLY])
        task = self._create(manager)

        status, body = self._fire(manager, task.task_id)

        assert (status, body) == (200, {"result": "reports", "session_id": "s1"})
        stored = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()
        assert (stored["trigger_count"], stored["last_request_id"], stored["last_error"]) == (1, "r-1", None)

    def test_an_owner_who_lost_access_is_skipped_and_the_task_says_why(self, hosting, authorization):
        client, manager = hosting
        authorization(grants=[self.WEEKLY])
        task = self._create(manager)
        authorization(grants=[])  # the operator takes the grant away

        status, body = self._fire(manager, task.task_id)

        assert (status, body) == (403, {"result": SkippedOccurrenceReply.TEXT, "session_id": "s1"})
        stored = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()
        assert (stored["trigger_count"], stored["last_request_id"]) == (1, "r-1")
        assert stored["last_error"] == "Agent 'reports' not found"
        assert stored["status"] == ScheduleStatus.ACTIVE.value  # a recurring task stays armed: the next occurrence is asked again

    def test_access_given_back_runs_the_next_occurrence_and_clears_the_error(self, hosting, authorization):
        client, manager = hosting
        authorization(grants=[self.WEEKLY])
        task = self._create(manager)
        authorization(grants=[])
        self._fire(manager, task.task_id, "r-1")
        authorization(grants=[self.WEEKLY])

        status, _ = self._fire(manager, task.task_id, "r-2")

        stored = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()
        assert (status, stored["trigger_count"], stored["last_request_id"], stored["last_error"]) == (200, 2, "r-2", None)

    def test_a_skipped_one_time_task_is_closed(self, hosting, authorization):
        client, manager = hosting
        authorization(grants=[self.WEEKLY])
        req = BaseRunRequest(
            prompt="send it once", agent="reports", session_id="s1", principal=ALICE, schedule=ScheduleSpec(at="2030-06-03T09:00:00")
        )
        task = manager.create_from_request(req)
        authorization(grants=[])

        self._fire(manager, task.task_id)

        stored = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()
        assert (stored["status"], stored["last_error"]) == (ScheduleStatus.COMPLETED.value, "Agent 'reports' not found")

    def test_without_an_authorization_block_nothing_is_asked_and_the_occurrence_runs(self, hosting):
        client, manager = hosting
        task = self._create(manager, BOB)

        status, body = self._fire(manager, task.task_id)

        assert (status, body["result"]) == (200, "reports")
        assert client.get(f"{SCHEDULES}/{task.task_id}", headers=BOB_AUTH).json()["last_error"] is None

    def test_a_trigger_carrying_no_owner_runs_as_nobody_and_is_skipped_without_a_record(self, hosting, authorization):
        """A body with no principal on it (a task from before principal ownership, or a forged trigger) acts as
        the anonymous principal: the gate refuses it, and it is not the owner's occurrence to record."""
        client, manager = hosting
        authorization(grants=[self.WEEKLY])
        task = self._create(manager)
        body = json.loads(manager._build_trigger_body(manager.get_task(task.task_id)).replace(TOKEN_REQUEST_ID, "r-1"))
        body["principal"] = None

        status, reply = ChatService().process_chat_request(BaseRunRequest.model_validate(body))

        assert (status, reply["result"]) == (403, SkippedOccurrenceReply.TEXT)
        stored = client.get(f"{SCHEDULES}/{task.task_id}", headers=ALICE_AUTH).json()
        assert (stored["trigger_count"], stored["last_error"]) == (0, None)
