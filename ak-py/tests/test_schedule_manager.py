"""ScheduleManager: validation, store/provider ordering, ownership and occurrence recording.

The manager is exercised against the real in-memory store and a recording fake provider, so the
ordering guarantees (record first, register second, roll back on failure) are observable.
"""

import json
from typing import Optional

import pytest

from agentkernel.core.base import Agent, Runner
from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import AgentReplyText, BaseRunRequest, ScheduleSpec
from agentkernel.core.runtime import Runtime
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.schedule.errors import ScheduleError
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.provider.eventbridge import EventBridgeScheduleProvider
from agentkernel.schedule.provider.local import LocalScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore

FUTURE_AT = "2030-06-01T09:00:00"


class FakeScheduleProvider(ScheduleProvider):
    """Records what the manager asked of the provider, and can be made to fail on demand."""

    def __init__(self, fail_on: Optional[str] = None):
        self.created: list[tuple[str, str]] = []  # (task_id, body_template)
        self.updated: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self._fail_on = fail_on

    def create(self, task, body_template):
        self._maybe_fail("create")
        self.created.append((task.task_id, body_template))
        return f"ref-{task.task_id}"

    def update(self, task, body_template):
        self._maybe_fail("update")
        self.updated.append((task.task_id, body_template))

    def delete(self, provider_ref):
        self._maybe_fail("delete")
        self.deleted.append(provider_ref)

    def get(self, provider_ref):
        return {"provider_ref": provider_ref}

    def _maybe_fail(self, operation: str) -> None:
        if self._fail_on == operation:
            raise ScheduleError(f"provider {operation} rejected")


def _sqs_only_provider() -> EventBridgeScheduleProvider:
    """The shipped SQS-only provider, so the compatibility checks pin the real class attribute.

    Its client is created on first use, so constructing one never reaches AWS.
    """
    return EventBridgeScheduleProvider(group_name="ak-schedules", role_arn="arn:aws:iam::1:role/r", queue_arn="arn:aws:sqs:us-east-1:1:q.fifo")


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        yield "ok"


class DummyAgent(Agent):
    def __init__(self, name: str = "planner"):
        super().__init__(name, DummyRunner("DummyRunner"))

    def get_description(self) -> str:
        return "Test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture(autouse=True)
def _reset_manager():
    ScheduleManager.reset()
    InMemoryScheduleStore().clear()
    yield
    ScheduleManager.reset()
    InMemoryScheduleStore().clear()


@pytest.fixture
def store():
    return InMemoryScheduleStore()


@pytest.fixture
def provider():
    return FakeScheduleProvider()


@pytest.fixture
def manager(provider, store):
    return ScheduleManager(provider=provider, store=store)


@pytest.fixture
def registered_agent():
    """A registered agent, so a task naming it passes the manager's named-agent precheck."""
    agent = DummyAgent()
    Runtime.current().register(agent)
    yield agent
    Runtime.current().deregister(agent)


def _configure_schedule(monkeypatch, **schedule_fields) -> None:
    """Point AKConfig at a schedule block (or at no block, when fields are omitted)."""
    AKConfig._reset()
    base = AKConfig.get()
    schedule = _ScheduleConfig.model_validate(schedule_fields) if schedule_fields is not None else None
    monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"schedule": schedule})))


def _create(manager: ScheduleManager, **overrides):
    fields = {"user_id": "u1", "prompt": "send the weekly report", "spec": ScheduleSpec(cron="0 9 * * 1"), "session_id": "s1"}
    fields.update(overrides)
    return manager.create(**fields)


class TestSingletonAndConfiguration:
    def test_get_returns_none_without_a_schedule_block(self, monkeypatch):
        AKConfig._reset()
        base = AKConfig.get()
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"schedule": None})))

        assert ScheduleManager.get() is None

    def test_get_builds_and_caches_the_shared_instance(self, monkeypatch):
        _configure_schedule(monkeypatch, provider={"type": "local"}, store={"type": "in_memory"})

        manager = ScheduleManager.get()

        assert manager is not None
        assert manager is ScheduleManager.get()

    def test_reset_drops_the_shared_instance(self, monkeypatch):
        _configure_schedule(monkeypatch, provider={"type": "local"})
        first = ScheduleManager.get()

        ScheduleManager.reset()

        assert ScheduleManager.get() is not first

    def test_transport_agnostic_provider_accepts_any_transport(self, store, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        assert ScheduleManager(provider=FakeScheduleProvider(), store=store) is not None
        assert LocalScheduleProvider.supported_transports is None

    def test_incompatible_provider_and_transport_fail_fast(self, store, monkeypatch):
        _configure_schedule(monkeypatch, provider={"type": "eventbridge"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        with pytest.raises(AKConfigError, match="delivers to \\['sqs'\\] transports, but the configured queue transport is 'in_memory'"):
            ScheduleManager(provider=_sqs_only_provider(), store=store)

    def test_compatible_provider_and_transport_are_accepted(self, store, monkeypatch):
        _configure_schedule(monkeypatch, provider={"type": "eventbridge"}, store={"type": "dynamodb"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        assert ScheduleManager(provider=_sqs_only_provider(), store=store) is not None

    def test_local_provider_is_accepted_on_the_single_process_pairing(self, store, monkeypatch):
        _configure_schedule(monkeypatch, provider={"type": "local"}, store={"type": "in_memory"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        assert ScheduleManager(provider=FakeScheduleProvider(), store=store) is not None

    def test_local_provider_and_broker_transport_fail_fast(self, store, monkeypatch):
        """A broker transport puts the management routes and the scheduler thread in different processes."""
        _configure_schedule(monkeypatch, provider={"type": "local"}, store={"type": "in_memory"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        with pytest.raises(AKConfigError, match="provider 'local' is single-process only.*transport is 'sqs' and the store is 'in_memory'"):
            ScheduleManager(provider=FakeScheduleProvider(), store=store)

    def test_local_provider_and_shared_store_fail_fast(self, store, monkeypatch):
        """A store the local provider's own process does not own is a pairing it cannot serve."""
        _configure_schedule(monkeypatch, provider={"type": "local"}, store={"type": "dynamodb"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))

        with pytest.raises(AKConfigError, match="provider 'local' is single-process only.*store is 'dynamodb'"):
            ScheduleManager(provider=FakeScheduleProvider(), store=store)

    def test_the_single_process_constraint_applies_only_to_the_local_provider(self, store, monkeypatch):
        """A provider that owns its timers elsewhere is unaffected by this check."""
        _configure_schedule(monkeypatch, provider={"type": "eventbridge"}, store={"type": "dynamodb"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        assert ScheduleManager(provider=_sqs_only_provider(), store=store) is not None

    def test_in_memory_store_and_broker_transport_fail_fast(self, store, monkeypatch):
        """A durable provider fires from whichever process created a task; in-memory records do not travel."""
        _configure_schedule(monkeypatch, provider={"type": "eventbridge"}, store={"type": "in_memory"})
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))

        with pytest.raises(AKConfigError, match="store 'in_memory' is single-process only.*transport is 'sqs'"):
            ScheduleManager(provider=_sqs_only_provider(), store=store)


class TestCreation:
    def test_create_stores_the_record_then_registers_it(self, manager, provider, store):
        task = _create(manager)

        assert task.status is ScheduleStatus.ACTIVE
        assert task.provider_ref == f"ref-{task.task_id}"
        assert provider.created[0][0] == task.task_id
        # The stored record carries the provider reference, so a later cancel can deregister it.
        assert store.get(task.task_id).provider_ref == task.provider_ref

    def test_create_from_a_chat_request_takes_the_envelope_fields(self, manager, registered_agent):
        req = BaseRunRequest(
            prompt="send the weekly report",
            agent="planner",
            session_id="s1",
            user_id="u1",
            schedule=ScheduleSpec(at=FUTURE_AT, timezone="Asia/Colombo"),
        )

        task = manager.create_from_request(req)

        assert (task.user_id, task.agent, task.session_id) == ("u1", "planner", "s1")
        assert task.spec.timezone == "Asia/Colombo"

    def test_creation_rejects_an_agent_that_is_not_registered(self, manager, store):
        # Every occurrence runs unattended, so a bad agent name has to fail at creation rather
        # than in the runner at each fire time.
        with pytest.raises(ValueError, match="No agent available"):
            _create(manager, agent="not-an-agent")

        assert store.list() == ([], None)

    def test_creation_without_an_agent_name_is_not_prechecked(self, manager, provider):
        # The default agent is resolved by whichever process fires the occurrence, which is not
        # necessarily this one, so an unnamed agent is left to run time.
        task = _create(manager)

        assert task.agent is None
        assert provider.created[0][0] == task.task_id

    def test_create_from_a_request_without_a_schedule_block_is_rejected(self, manager):
        req = BaseRunRequest(prompt="hi", session_id="s1", user_id="u1")

        with pytest.raises(ValueError, match="carries no 'schedule' block"):
            manager.create_from_request(req)

    @pytest.mark.parametrize(
        "overrides, message",
        [
            ({"user_id": None}, "requires a user identity"),
            ({"prompt": ""}, "requires a prompt"),
            ({"session_id": None}, "requires a session_id"),
            ({"spec": ScheduleSpec(cron="0 9 * *  ")}, "5-field expression"),
            ({"spec": ScheduleSpec(cron="0 9 * * 1", timezone="Mars/Olympus")}, "unknown schedule timezone"),
            ({"spec": ScheduleSpec(at="not-a-timestamp")}, "must be an ISO-8601 timestamp"),
            ({"spec": ScheduleSpec(at="2030-06-01T09:00:00+05:30")}, "must not carry a UTC offset"),
            ({"spec": ScheduleSpec(at="2020-01-01T09:00:00")}, "must be in the future"),
        ],
    )
    def test_unusable_creation_input_is_rejected(self, manager, provider, overrides, message):
        with pytest.raises(ValueError, match=message):
            _create(manager, **overrides)

        # Nothing was registered: validation runs before any write.
        assert provider.created == []

    def test_provider_failure_rolls_the_record_back(self, store):
        manager = ScheduleManager(provider=FakeScheduleProvider(fail_on="create"), store=store)

        with pytest.raises(ScheduleError, match="provider create rejected"):
            _create(manager)

        assert store.list() == ([], None)


class TestTriggerBody:
    def test_reused_session_body_carries_the_originating_session(self, manager, provider):
        task = _create(manager, spec=ScheduleSpec(cron="0 9 * * 1", session_mode="reuse"))

        body = provider.created[0][1]
        assert f'"session_id": "{task.session_id}"' in body
        assert f'"scheduled_task_id": "{task.task_id}"' in body
        assert TOKEN_REQUEST_ID in body
        assert TOKEN_OCCURRENCE_TIME in body

    def test_new_session_body_carries_a_per_occurrence_session_template(self, manager, provider):
        task = _create(manager, spec=ScheduleSpec(cron="0 9 * * 1", session_mode="new"))

        assert f'"session_id": "ak-sched-{task.task_id}-{TOKEN_OCCURRENCE_TIME}"' in provider.created[0][1]

    def test_body_carries_no_schedule_block(self, manager, provider):
        # A trigger that re-declared the schedule would register another task every time it fired.
        _create(manager)

        body = json.loads(provider.created[0][1])
        assert "schedule" not in body
        assert sorted(body) == ["agent", "prompt", "request_id", "scheduled_task_id", "scheduled_time", "session_id", "user_id"]


class TestReads:
    def test_get_task_returns_none_for_an_unknown_id(self, manager):
        assert manager.get_task("missing") is None

    def test_get_task_enforces_ownership(self, manager):
        task = _create(manager, user_id="u1")

        assert manager.get_task(task.task_id, user_id="u1").task_id == task.task_id
        with pytest.raises(PermissionError, match="not owned by user u2"):
            manager.get_task(task.task_id, user_id="u2")

    def test_get_task_without_a_resolved_user_skips_the_ownership_check(self, manager):
        task = _create(manager, user_id="u1")

        assert manager.get_task(task.task_id) is not None

    def test_list_tasks_is_scoped_by_owner(self, manager):
        mine = _create(manager, user_id="u1")
        _create(manager, user_id="u2")

        page = manager.list_tasks(user_id="u1")

        assert [task.task_id for task in page.tasks] == [mine.task_id]
        assert page.next_cursor is None

    def test_list_tasks_pages_through_an_opaque_cursor(self, manager):
        for _ in range(3):
            _create(manager)

        first = manager.list_tasks(limit=2)
        second = manager.list_tasks(limit=2, cursor=first.next_cursor)

        assert len(first.tasks) == 2
        assert first.next_cursor is not None
        assert len(second.tasks) == 1
        assert second.next_cursor is None

    def test_malformed_cursor_is_rejected(self, manager):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            manager.list_tasks(cursor="not-a-cursor")


class TestAmendment:
    def test_amendment_replaces_the_rule_and_re_registers_the_task(self, manager, provider, store):
        task = _create(manager)

        amended = manager.update(task.task_id, {"cron": None, "at": FUTURE_AT, "timezone": "Asia/Colombo", "prompt": "send the daily report"})

        assert amended.spec.at == FUTURE_AT
        assert amended.spec.cron is None
        assert amended.prompt == "send the daily report"
        assert provider.updated[0][0] == task.task_id
        assert store.get(task.task_id).prompt == "send the daily report"

    def test_amendment_can_pause_and_resume_a_task(self, manager):
        task = _create(manager)

        paused = manager.update(task.task_id, {"status": "paused"})
        assert paused.status is ScheduleStatus.PAUSED

        assert manager.update(task.task_id, {"status": "active"}).status is ScheduleStatus.ACTIVE

    def test_amendment_cannot_set_a_lifecycle_outcome(self, manager):
        task = _create(manager)

        with pytest.raises(ValueError, match="can only be amended to one of"):
            manager.update(task.task_id, {"status": "completed"})

    def test_amendment_cannot_touch_a_non_amendable_field(self, manager):
        task = _create(manager)

        with pytest.raises(ValueError, match="Cannot amend \\['user_id'\\]"):
            manager.update(task.task_id, {"user_id": "u2"})

    def test_amendment_cannot_empty_the_prompt(self, manager):
        task = _create(manager)

        with pytest.raises(ValueError, match="prompt cannot be emptied"):
            manager.update(task.task_id, {"prompt": ""})

    def test_amended_rule_is_validated_structurally_and_semantically(self, manager):
        task = _create(manager)

        with pytest.raises(ValueError, match="exactly one of 'at'"):
            manager.update(task.task_id, {"at": FUTURE_AT, "cron": "0 9 * * 1"})
        with pytest.raises(ValueError, match="unknown schedule timezone"):
            manager.update(task.task_id, {"cron": "0 9 * * 1", "timezone": "Mars/Olympus"})

    def test_amending_one_occurrence_field_replaces_the_whole_rule(self, manager):
        task = _create(manager, spec=ScheduleSpec(cron="0 9 * * 1", timezone="Asia/Colombo", session_mode="new"))

        amended = manager.update(task.task_id, {"at": FUTURE_AT})

        # The rule is replaced as a unit, so the fields the amendment left out fall back to their
        # defaults rather than to the stored values.
        assert (amended.spec.at, amended.spec.cron) == (FUTURE_AT, None)
        assert (amended.spec.timezone, amended.spec.session_mode) == ("UTC", "reuse")

    def test_an_occurrence_rule_cannot_be_amended_away(self, manager):
        task = _create(manager)

        with pytest.raises(ValueError, match="exactly one of 'at'"):
            manager.update(task.task_id, {"timezone": "Asia/Colombo"})

    def test_an_amendment_naming_no_occurrence_field_leaves_the_rule_untouched(self, manager):
        task = _create(manager, spec=ScheduleSpec(cron="0 9 * * 1", timezone="Asia/Colombo"))

        amended = manager.update(task.task_id, {"prompt": "send the daily report"})

        assert (amended.spec.cron, amended.spec.timezone) == ("0 9 * * 1", "Asia/Colombo")

    def test_amending_an_unknown_task_reports_it_as_missing(self, manager):
        with pytest.raises(KeyError, match="not found"):
            manager.update("missing", {"prompt": "whatever"})

    def test_amendment_enforces_ownership(self, manager):
        task = _create(manager, user_id="u1")

        with pytest.raises(PermissionError):
            manager.update(task.task_id, {"prompt": "theirs now"}, user_id="u2")

    def test_closed_task_can_no_longer_be_amended(self, manager, store):
        task = _create(manager)
        store.update(task.model_copy(update={"status": ScheduleStatus.COMPLETED}))

        with pytest.raises(ValueError, match="is completed and can no longer be changed"):
            manager.update(task.task_id, {"prompt": "again"})

    def test_provider_failure_restores_the_previous_record(self, store):
        manager = ScheduleManager(provider=FakeScheduleProvider(fail_on="update"), store=store)
        task = _create(manager)

        with pytest.raises(ScheduleError, match="provider update rejected"):
            manager.update(task.task_id, {"prompt": "send the daily report"})

        assert store.get(task.task_id).prompt == "send the weekly report"


class TestCancellation:
    def test_cancel_deregisters_and_records_the_transition(self, manager, provider, store):
        task = _create(manager)

        cancelled = manager.cancel(task.task_id)

        assert cancelled.status is ScheduleStatus.CANCELLED
        assert provider.deleted == [task.provider_ref]
        # The record survives as the audit trail rather than being deleted.
        assert store.get(task.task_id).status is ScheduleStatus.CANCELLED

    def test_cancel_enforces_ownership(self, manager):
        task = _create(manager, user_id="u1")

        with pytest.raises(PermissionError):
            manager.cancel(task.task_id, user_id="u2")

    def test_cancelling_an_unknown_task_reports_it_as_missing(self, manager):
        with pytest.raises(KeyError, match="not found"):
            manager.cancel("missing")

    def test_cancelling_twice_is_rejected(self, manager):
        task = _create(manager)
        manager.cancel(task.task_id)

        with pytest.raises(ValueError, match="is cancelled and can no longer be changed"):
            manager.cancel(task.task_id)


class TestTriggerRecording:
    def test_recording_advances_the_occurrence_fields(self, manager, store):
        task = _create(manager)

        manager.record_trigger(task.task_id, request_id="r1", occurred_at="2030-06-01T09:00:00Z")

        recorded = store.get(task.task_id)
        assert recorded.trigger_count == 1
        assert recorded.last_request_id == "r1"
        assert recorded.last_triggered_at == "2030-06-01T09:00:00Z"
        assert recorded.status is ScheduleStatus.ACTIVE

    def test_recording_stamps_the_current_time_when_the_provider_reports_none(self, manager, store):
        task = _create(manager)

        manager.record_trigger(task.task_id)

        assert store.get(task.task_id).last_triggered_at is not None

    def test_recording_completes_a_one_time_task(self, manager, store):
        task = _create(manager, spec=ScheduleSpec(at=FUTURE_AT))

        manager.record_trigger(task.task_id, request_id="r1")

        assert store.get(task.task_id).status is ScheduleStatus.COMPLETED

    def test_recording_an_unknown_task_is_ignored(self, manager):
        manager.record_trigger("missing", request_id="r1")

    def test_recording_never_raises_into_the_run(self, provider, store, monkeypatch):
        manager = ScheduleManager(provider=provider, store=store)
        task = _create(manager)
        monkeypatch.setattr(store, "record_trigger", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("store down")))

        manager.record_trigger(task.task_id, request_id="r1")
