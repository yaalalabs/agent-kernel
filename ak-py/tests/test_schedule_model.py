"""Wire and task models of the scheduling capability (#629 Phase 3).

ScheduleSpec is the chat-envelope block; ScheduledTask is the stored record. Both travel
through queue bodies as JSON, so the round trips here pin that every field is a JSON
primitive (timestamps included).
"""

import json

import pytest
from pydantic import ValidationError

from agentkernel.core.model import BaseRunRequest, ScheduleSpec
from agentkernel.schedule.model import ScheduledTask, ScheduledTaskPage, ScheduleStatus


def _task(**overrides) -> ScheduledTask:
    """A stored record with every required field, overridable per case."""
    fields = {
        "task_id": "t1",
        "user_id": "u1",
        "prompt": "send the weekly report",
        "session_id": "s1",
        "spec": ScheduleSpec(cron="0 9 * * 1"),
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": "2030-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


class TestScheduleSpec:
    def test_one_time_spec_defaults_to_utc_and_session_reuse(self):
        spec = ScheduleSpec(at="2030-01-01T09:00:00")
        assert spec.timezone == "UTC"
        assert spec.session_mode == "reuse"
        assert spec.cron is None

    def test_recurring_spec_accepts_a_cron_expression_and_timezone(self):
        spec = ScheduleSpec(cron="0 9 * * 1", timezone="Asia/Colombo")
        assert spec.cron == "0 9 * * 1"
        assert spec.timezone == "Asia/Colombo"

    def test_both_at_and_cron_is_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of 'at'"):
            ScheduleSpec(at="2030-01-01T09:00:00", cron="0 9 * * *")

    def test_neither_at_nor_cron_is_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of 'at'"):
            ScheduleSpec()

    def test_blank_timezone_is_rejected(self):
        with pytest.raises(ValidationError, match="timezone must not be empty"):
            ScheduleSpec(cron="0 9 * * *", timezone="  ")

    def test_unknown_session_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            ScheduleSpec(cron="0 9 * * *", session_mode="clone")

    def test_cron_syntax_is_not_validated_here(self):
        # Semantic validation belongs to ScheduleManager: croniter is an optional extra and
        # core models must import without it.
        assert ScheduleSpec(cron="not a cron").cron == "not a cron"


class TestChatRequestEnvelope:
    def test_schedule_block_parses_from_a_chat_payload(self):
        req = BaseRunRequest.model_validate(
            {
                "prompt": "send the weekly report",
                "session_id": "s1",
                "user_id": "u1",
                "schedule": {"cron": "0 9 * * 1", "timezone": "Asia/Colombo", "session_mode": "new"},
            }
        )
        assert req.schedule.cron == "0 9 * * 1"
        assert req.schedule.session_mode == "new"

    def test_request_without_a_schedule_block_is_unchanged(self):
        req = BaseRunRequest.model_validate({"prompt": "hi", "session_id": "s1"})
        assert req.schedule is None
        assert req.scheduled_task_id is None
        assert req.scheduled_time is None

    def test_trigger_metadata_are_typed_fields_not_extras(self):
        # Typed fields keep the occurrence metadata out of the agent's additional context.
        req = BaseRunRequest.model_validate(
            {
                "prompt": "send the weekly report",
                "session_id": "s1",
                "scheduled_task_id": "t1",
                "scheduled_time": "2030-01-01T09:00:00Z",
            }
        )
        assert req.scheduled_task_id == "t1"
        assert req.scheduled_time == "2030-01-01T09:00:00Z"
        assert "scheduled_task_id" in type(req).model_fields

    def test_invalid_schedule_block_fails_the_request(self):
        with pytest.raises(ValidationError, match="exactly one of 'at'"):
            BaseRunRequest.model_validate({"prompt": "hi", "session_id": "s1", "schedule": {}})


class TestScheduledTask:
    def test_new_task_starts_active_with_no_occurrences(self):
        task = _task()
        assert task.status is ScheduleStatus.ACTIVE
        assert task.trigger_count == 0
        assert task.last_triggered_at is None
        assert task.last_request_id is None
        assert task.provider_ref is None

    def test_json_round_trip_preserves_every_field(self):
        task = _task(agent="planner", provider_ref="arn:aws:scheduler:::schedule/g/ak-t1", trigger_count=3)
        restored = ScheduledTask.model_validate(json.loads(json.dumps(task.model_dump(mode="json"))))
        assert restored == task

    def test_dumped_record_carries_only_json_primitives(self):
        # Store portability: every backend persists the dumped document as-is.
        dumped = _task().model_dump(mode="json")
        assert isinstance(dumped["created_at"], str)
        assert dumped["status"] == "active"
        assert dumped["spec"] == {"at": None, "cron": "0 9 * * 1", "timezone": "UTC", "session_mode": "reuse"}

    def test_page_defaults_to_no_next_cursor(self):
        page = ScheduledTaskPage(tasks=[_task()])
        assert page.next_cursor is None


class TestApplyTrigger:
    """The occurrence bookkeeping every store shares: each one loads a record, applies this, writes
    it back, so the rule is pinned once here rather than three times over."""

    def test_an_occurrence_advances_the_bookkeeping(self):
        task = _task()

        task.apply_trigger(request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False)

        assert task.last_triggered_at == "2030-02-01T09:00:00+00:00"
        assert task.last_request_id == "r-1"
        assert task.trigger_count == 1
        assert task.updated_at != "2030-01-01T00:00:00+00:00"
        # A recurring task has further occurrences, so it stays active.
        assert task.status is ScheduleStatus.ACTIVE

    def test_occurrences_accumulate(self):
        task = _task(trigger_count=2)

        task.apply_trigger(request_id=None, occurred_at="2030-02-01T09:00:00+00:00", completed=False)

        assert task.trigger_count == 3
        # An occurrence whose run id never arrived clears the previous one rather than keeping a
        # stale correlation.
        assert task.last_request_id is None

    def test_a_final_occurrence_completes_the_task(self):
        task = _task(spec=ScheduleSpec(at="2030-06-01T09:00:00"))

        task.apply_trigger(request_id="r-1", occurred_at="2030-06-01T09:00:00+00:00", completed=True)

        assert task.status is ScheduleStatus.COMPLETED

    def test_a_cancellation_outranks_a_completion(self):
        """A task cancelled between the fire and the record must not come back as completed."""
        task = _task(status=ScheduleStatus.CANCELLED)

        task.apply_trigger(request_id="r-1", occurred_at="2030-06-01T09:00:00+00:00", completed=True)

        assert task.status is ScheduleStatus.CANCELLED
        # The occurrence still happened, so it is still recorded.
        assert task.trigger_count == 1

    def test_it_returns_the_task_so_a_store_can_write_it_back_inline(self):
        task = _task()

        assert task.apply_trigger(request_id="r-1", occurred_at="2030-02-01T09:00:00+00:00", completed=False) is task
