"""LocalScheduleProvider: the in-process timer that fires occurrences into the input queue.

Fire times are pushed a few tens of milliseconds out (or handed to the provider through a stubbed
occurrence calculator) so the scheduler thread's real waiting behavior is exercised without the
suite waiting on wall-clock cron boundaries.
"""

import datetime
import json
import re

import pytest

from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.schedule.model import TOKEN_OCCURRENCE_TIME, TOKEN_REQUEST_ID, ScheduledTask, ScheduleStatus
from agentkernel.schedule.provider.base import ScheduleProvider, ScheduleProviderFactory
from agentkernel.schedule.provider.local import LocalScheduleProvider
from agentkernel.schedule.timing import OccurrenceCalculator

DELIVERY_WAIT_SECONDS = 3.0
BODY_TEMPLATE = json.dumps(
    {
        "prompt": "send the weekly report",
        "agent": None,
        "user_id": "u1",
        "session_id": "s1",
        "scheduled_task_id": "t1",
        "request_id": TOKEN_REQUEST_ID,
        "scheduled_time": TOKEN_OCCURRENCE_TIME,
    }
)


@pytest.fixture(autouse=True)
def _reset_transport():
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()


@pytest.fixture
def transport():
    return InMemoryTransport()


@pytest.fixture
def provider(transport):
    """A provider whose armed occurrences are disarmed at teardown.

    Its scheduler thread is a daemon that outlives the test, and the in-memory queues are
    process-wide, so an occurrence left armed here would fire into another test's queues.
    """
    created = LocalScheduleProvider(transport=transport)
    yield created
    for task_id in list(created._armed):
        created.delete(task_id)


def _task(spec: ScheduleSpec, task_id: str = "t1", **overrides) -> ScheduledTask:
    fields = {
        "task_id": task_id,
        "user_id": "u1",
        "prompt": "send the weekly report",
        "session_id": "s1",
        "spec": spec,
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": "2030-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


def _at_spec(seconds_ahead: float, **overrides) -> ScheduleSpec:
    """A one-time spec whose wall-clock time is a moment away, in UTC."""
    occurrence = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds_ahead)
    return ScheduleSpec(at=occurrence.replace(tzinfo=None).isoformat(), **overrides)


def _fetch_triggers(transport: InMemoryTransport, expected: int = 1, wait: float = DELIVERY_WAIT_SECONDS) -> list:
    """Collect up to ``expected`` triggers from the input queue, giving the thread time to fire."""
    consumer = transport.create_consumer(QueueName.INPUT)
    messages = []
    while len(messages) < expected:
        batch = consumer.fetch(expected - len(messages), wait)
        if not batch:
            break
        for message in batch:
            consumer.ack(message)
        messages.extend(batch)
    return messages


class TestNextFireComputation:
    def test_get_reports_the_armed_occurrence(self, provider):
        task = _task(ScheduleSpec(cron="0 9 * * 1", timezone="Asia/Colombo"))

        provider.create(task, BODY_TEMPLATE)

        armed = provider.get("t1")
        assert armed["task_id"] == "t1"
        # Armed in the spec's timezone, at the next Monday 09:00 there.
        fire_time = datetime.datetime.fromisoformat(armed["next_fire_time"])
        assert (fire_time.hour, fire_time.minute) == (9, 0)
        assert fire_time.isoweekday() == 1
        assert fire_time.utcoffset() == datetime.timedelta(hours=5, minutes=30)

    def test_provider_ref_is_the_task_id(self, provider):
        assert provider.create(_task(ScheduleSpec(cron="0 9 * * 1")), BODY_TEMPLATE) == "t1"

    def test_one_time_occurrence_in_the_past_is_not_armed(self, provider):
        provider.create(_task(ScheduleSpec(at="2020-01-01T09:00:00")), BODY_TEMPLATE)

        assert provider.get("t1") is None

    def test_get_unknown_reference_returns_none(self, provider):
        assert provider.get("nope") is None


class TestFiring:
    def test_one_time_task_fires_once_and_disarms(self, transport, provider):
        provider.create(_task(_at_spec(0.2)), BODY_TEMPLATE)

        assert len(_fetch_triggers(transport)) == 1
        assert provider.get("t1") is None
        # Nothing further: the occurrence is spent.
        assert _fetch_triggers(transport, wait=0.3) == []

    def test_recurring_task_rearms_after_each_occurrence(self, transport, provider, monkeypatch):
        # A real cron boundary is up to a minute away, so the occurrence rule is stubbed to hand
        # the provider two occurrences and then run out.
        occurrences = [
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=0.2),
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=0.4),
            None,
        ]
        monkeypatch.setattr(OccurrenceCalculator, "next_fire_time", classmethod(lambda cls, spec, after=None: occurrences.pop(0)))
        provider.create(_task(ScheduleSpec(cron="* * * * *")), BODY_TEMPLATE)

        triggers = _fetch_triggers(transport, expected=2)
        assert len(triggers) == 2
        assert provider.get("t1") is None

    def test_trigger_carries_the_body_with_substituted_occurrence_values(self, transport, provider):
        provider.create(_task(_at_spec(0.2)), BODY_TEMPLATE)

        body = json.loads(_fetch_triggers(transport)[0].body)
        assert body["prompt"] == "send the weekly report"
        assert body["scheduled_task_id"] == "t1"
        assert TOKEN_REQUEST_ID not in json.dumps(body)
        assert re.fullmatch(r"[0-9a-f-]{36}", body["request_id"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["scheduled_time"])

    def test_trigger_carries_no_message_attributes(self, transport, provider):
        # The delivery contract is body-only, matching what EventBridge Scheduler can send.
        provider.create(_task(_at_spec(0.2)), BODY_TEMPLATE)

        assert _fetch_triggers(transport)[0].attributes == {}

    def test_reused_session_groups_triggers_by_that_session(self, transport, provider):
        provider.create(_task(_at_spec(0.2, session_mode="reuse")), BODY_TEMPLATE)

        assert _fetch_triggers(transport)[0].group_id == "s1"

    def test_per_occurrence_session_groups_triggers_by_the_task(self, transport, provider):
        template = BODY_TEMPLATE.replace('"session_id": "s1"', f'"session_id": "ak-sched-t1-{TOKEN_OCCURRENCE_TIME}"')

        provider.create(_task(_at_spec(0.2, session_mode="new")), template)

        trigger = _fetch_triggers(transport)[0]
        assert trigger.group_id == "t1"
        assert json.loads(trigger.body)["session_id"].startswith("ak-sched-t1-20")

    def test_delivery_failure_skips_the_occurrence_without_killing_the_loop(self, transport, provider, monkeypatch):
        attempts = []
        working_send = transport.send

        def send_failing_once(queue, message):
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("queue unreachable")
            return working_send(queue, message)

        monkeypatch.setattr(transport, "send", send_failing_once)

        provider.create(_task(_at_spec(0.2)), BODY_TEMPLATE)
        provider.create(_task(_at_spec(0.5), task_id="t2"), BODY_TEMPLATE)

        # The first occurrence is lost, the loop survives to deliver the second.
        assert len(_fetch_triggers(transport)) == 1
        assert len(attempts) == 2


class TestArmingLifecycle:
    def test_update_replaces_the_armed_occurrence(self, transport, provider):
        provider.create(_task(ScheduleSpec(cron="0 9 * * 1", timezone="UTC")), BODY_TEMPLATE)
        first = provider.get("t1")["next_fire_time"]

        provider.update(_task(ScheduleSpec(cron="30 9 * * 1", timezone="UTC")), BODY_TEMPLATE)

        assert provider.get("t1")["next_fire_time"] != first

    def test_pausing_a_task_disarms_it(self, transport, provider):
        task = _task(_at_spec(0.3))
        provider.create(task, BODY_TEMPLATE)

        provider.update(task.model_copy(update={"status": ScheduleStatus.PAUSED}), BODY_TEMPLATE)

        assert provider.get("t1") is None
        assert _fetch_triggers(transport, wait=0.6) == []

    def test_delete_disarms_the_task_and_tolerates_an_unarmed_one(self, transport, provider):
        provider.create(_task(_at_spec(0.3)), BODY_TEMPLATE)

        provider.delete("t1")
        provider.delete("t1")

        assert provider.get("t1") is None
        assert _fetch_triggers(transport, wait=0.6) == []

    def test_an_amended_occurrence_does_not_fire_at_the_old_time(self, transport, provider):
        task = _task(_at_spec(0.3))
        provider.create(task, BODY_TEMPLATE)

        provider.update(_task(_at_spec(30)), BODY_TEMPLATE)

        assert _fetch_triggers(transport, wait=0.8) == []


class TestScheduleProviderFactory:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @staticmethod
    def _configure(monkeypatch, provider_type: str) -> None:
        config = AKConfig.get().model_copy(update={"schedule": _ScheduleConfig.model_validate({"provider": {"type": provider_type}})})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

    def test_builds_the_local_provider_with_the_configured_transport(self, monkeypatch):
        self._configure(monkeypatch, "local")

        provider = ScheduleProviderFactory.create()

        assert isinstance(provider, LocalScheduleProvider)
        # Transport-agnostic: the local provider imposes no transport requirement.
        assert type(provider).supported_transports is None

    def test_builds_a_bring_your_own_provider_from_a_dotted_path(self, monkeypatch):
        self._configure(monkeypatch, f"{_CustomScheduleProvider.__module__}._CustomScheduleProvider")

        assert isinstance(ScheduleProviderFactory.create(), _CustomScheduleProvider)

    def test_unknown_short_name_is_a_config_error(self, monkeypatch):
        self._configure(monkeypatch, "celery")

        with pytest.raises(AKConfigError, match="unknown schedule provider type 'celery'"):
            ScheduleProviderFactory.create()

    def test_unconfigured_capability_cannot_build_a_provider(self, monkeypatch):
        config = AKConfig.get().model_copy(update={"schedule": None})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

        with pytest.raises(ValueError, match="Scheduling is not configured"):
            ScheduleProviderFactory.create()


class _CustomScheduleProvider(ScheduleProvider):
    """Bring-your-own provider used to pin dotted-path resolution."""

    def create(self, task, body_template):
        return task.task_id

    def update(self, task, body_template):
        return None

    def delete(self, provider_ref):
        return None

    def get(self, provider_ref):
        return None
