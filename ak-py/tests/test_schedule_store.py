"""Scheduled-task stores (#629 Phase 3: the in_memory backend).

The distributed backends (redis, valkey, dynamodb) arrive with their own cases in a later phase;
these pin the contract every backend has to satisfy.
"""

import pytest

from agentkernel.core.config import AKConfig, _ScheduleConfig
from agentkernel.core.model import ScheduleSpec
from agentkernel.core.util.factory import AKConfigError
from agentkernel.schedule.model import ScheduledTask, ScheduleStatus
from agentkernel.schedule.store.base import ScheduleStore, ScheduleStoreBuilder
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore


def _task(task_id: str, user_id: str = "u1", updated_at: str = "2030-01-01T00:00:00+00:00", **overrides) -> ScheduledTask:
    fields = {
        "task_id": task_id,
        "user_id": user_id,
        "prompt": "send the weekly report",
        "session_id": f"s-{task_id}",
        "spec": ScheduleSpec(cron="0 9 * * 1"),
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": updated_at,
    }
    fields.update(overrides)
    return ScheduledTask(**fields)


class TestInMemoryScheduleStore:
    @pytest.fixture(autouse=True)
    def store(self):
        store = InMemoryScheduleStore()
        store.clear()
        yield store
        store.clear()

    def test_create_then_get_round_trips_the_record(self, store):
        store.create(_task("t1", agent="planner"))

        loaded = store.get("t1")
        assert loaded.user_id == "u1"
        assert loaded.agent == "planner"
        assert loaded.spec.cron == "0 9 * * 1"

    def test_get_unknown_task_returns_none(self, store):
        assert store.get("missing") is None

    def test_stored_records_are_isolated_from_the_caller(self, store):
        task = _task("t1")
        store.create(task)

        task.prompt = "mutated after storing"
        assert store.get("t1").prompt == "send the weekly report"

    def test_update_overwrites_the_whole_record(self, store):
        store.create(_task("t1"))

        store.update(_task("t1", prompt="new prompt", provider_ref="ref-1", status=ScheduleStatus.PAUSED))

        loaded = store.get("t1")
        assert loaded.prompt == "new prompt"
        assert loaded.provider_ref == "ref-1"
        assert loaded.status is ScheduleStatus.PAUSED

    def test_delete_removes_the_record_and_tolerates_a_missing_one(self, store):
        store.create(_task("t1"))

        store.delete("t1")
        store.delete("t1")

        assert store.get("t1") is None

    def test_list_returns_most_recently_updated_first(self, store):
        store.create(_task("old", updated_at="2030-01-01T00:00:00+00:00"))
        store.create(_task("new", updated_at="2030-02-01T00:00:00+00:00"))

        tasks, next_offset = store.list()

        assert [task.task_id for task in tasks] == ["new", "old"]
        assert next_offset is None

    def test_list_filters_by_owner(self, store):
        store.create(_task("mine", user_id="u1"))
        store.create(_task("theirs", user_id="u2"))

        tasks, _ = store.list(user_id="u1")

        assert [task.task_id for task in tasks] == ["mine"]

    def test_list_pages_with_offset_and_limit(self, store):
        for index in range(3):
            store.create(_task(f"t{index}", updated_at=f"2030-01-0{index + 1}T00:00:00+00:00"))

        first_page, next_offset = store.list(limit=2)
        second_page, final_offset = store.list(limit=2, offset=next_offset)

        assert [task.task_id for task in first_page] == ["t2", "t1"]
        assert next_offset == 2
        assert [task.task_id for task in second_page] == ["t0"]
        assert final_offset is None

    def test_record_trigger_advances_the_occurrence_fields(self, store):
        store.create(_task("t1"))

        store.record_trigger("t1", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=False)

        loaded = store.get("t1")
        assert loaded.trigger_count == 1
        assert loaded.last_triggered_at == "2030-03-01T09:00:00+00:00"
        assert loaded.last_request_id == "r1"
        # Recording is activity, so it restamps the record the listing orders by.
        assert loaded.updated_at != "2030-01-01T00:00:00+00:00"
        assert loaded.status is ScheduleStatus.ACTIVE

    def test_record_trigger_completes_a_final_occurrence(self, store):
        store.create(_task("t1", spec=ScheduleSpec(at="2030-03-01T09:00:00")))

        store.record_trigger("t1", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=True)

        assert store.get("t1").status is ScheduleStatus.COMPLETED

    def test_record_trigger_for_an_unknown_task_is_ignored(self, store):
        # A trigger can outlive the record it came from; it must not raise into the run.
        store.record_trigger("missing", request_id="r1", occurred_at="2030-03-01T09:00:00+00:00", completed=False)

    def test_clear_removes_every_record(self, store):
        store.create(_task("t1"))

        store.clear()

        assert store.list() == ([], None)


class _CustomScheduleStore(InMemoryScheduleStore):
    """Bring-your-own store used to pin dotted-path resolution."""


class TestScheduleStoreBuilder:
    @pytest.fixture(autouse=True)
    def _reset_config(self):
        AKConfig._reset()
        yield
        AKConfig._reset()

    @staticmethod
    def _configure(monkeypatch, store_type: str) -> None:
        config = AKConfig.get().model_copy(update={"schedule": _ScheduleConfig.model_validate({"store": {"type": store_type}})})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

    def test_builds_the_in_memory_store(self, monkeypatch):
        self._configure(monkeypatch, "in_memory")

        assert isinstance(ScheduleStoreBuilder.build(), InMemoryScheduleStore)

    def test_builds_a_bring_your_own_store_from_a_dotted_path(self, monkeypatch):
        self._configure(monkeypatch, f"{_CustomScheduleStore.__module__}._CustomScheduleStore")

        assert isinstance(ScheduleStoreBuilder.build(), _CustomScheduleStore)

    def test_unknown_short_name_is_a_config_error(self, monkeypatch):
        self._configure(monkeypatch, "postgres")

        with pytest.raises(AKConfigError, match="unknown schedule store type 'postgres'"):
            ScheduleStoreBuilder.build()

    def test_dotted_path_to_a_non_store_is_a_config_error(self, monkeypatch):
        self._configure(monkeypatch, "agentkernel.schedule.model.ScheduledTask")

        with pytest.raises(AKConfigError, match="not a ScheduleStore subclass"):
            ScheduleStoreBuilder.build()

    def test_unconfigured_capability_cannot_build_a_store(self, monkeypatch):
        config = AKConfig.get().model_copy(update={"schedule": None})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: config))

        with pytest.raises(ValueError, match="Scheduling is not configured"):
            ScheduleStoreBuilder.build()

    def test_every_abstract_method_is_implemented_by_the_builtin(self):
        # A backend that silently inherits an abstract method would fail at first use, not at build.
        assert not (set(ScheduleStore.__abstractmethods__) - set(vars(InMemoryScheduleStore)))
