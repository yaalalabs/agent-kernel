"""
The paused-run record and its accessor (spec `docs/specs/606-human-in-the-loop/`, iteration 2).

What matters here is durability and resolution: a record must survive a real session-store round
trip, and a set of decisions must resolve to exactly one run — including when the caller names no
run id, which is the only thing the AG-UI protocol can do. The last test pins accepted behaviour
rather than a bug: an application clearing the non-volatile cache discards pending decisions.
"""

import logging

import pytest

from agentkernel.core.base import Runner, Session
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import AgentReplyText
from agentkernel.core.paused_run import AK_PAUSED_RUNS_KEY, PausedRun, PausedRunState
from agentkernel.core.session.in_memory import InMemorySessionStore


def _interruptions(*ids: str) -> list[PausedInterruption]:
    return [PausedInterruption(id=id_, kind="tool_call", tool_name="refund") for id_ in ids]


@pytest.fixture(autouse=True)
def _reset_warn_once():
    """The in-memory warning is class-level state, so it leaks between tests unless reset."""
    PausedRunState._in_memory_warned = False
    yield
    PausedRunState._in_memory_warned = False


class TestAddAndRead:
    def test_add_assigns_an_id_and_returns_the_stored_record(self):
        session = Session("s1")
        record = PausedRunState.add(session, agent="refunds", interruptions=_interruptions("i1"), payload={"state": "blob"})

        assert record.id
        assert record.agent == "refunds"
        assert PausedRunState.get(session, record.id) == record

    def test_created_at_is_iso_utc(self):
        record = PausedRunState.add(Session("s1"), agent="a", interruptions=_interruptions("i1"))
        assert record.created_at.endswith("+00:00")

    def test_list_is_empty_when_nothing_paused(self):
        assert PausedRunState.list(Session("s1")) == []

    def test_a_session_can_hold_more_than_one_paused_run(self):
        """Agent Kernel does not limit this; how many a framework can really hold is its business."""
        session = Session("s1")
        first = PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        second = PausedRunState.add(session, agent="a", interruptions=_interruptions("i2"))

        assert [r.id for r in PausedRunState.list(session)] == [first.id, second.id]

    def test_get_returns_none_for_an_unknown_run(self):
        assert PausedRunState.get(Session("s1"), "no-such-run") is None

    def test_clear_removes_only_its_own_record(self):
        session = Session("s1")
        first = PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        second = PausedRunState.add(session, agent="a", interruptions=_interruptions("i2"))

        PausedRunState.clear(session, first.id)

        assert [r.id for r in PausedRunState.list(session)] == [second.id]

    def test_clear_is_silent_for_an_unknown_run(self):
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        PausedRunState.clear(session, "no-such-run")

        assert len(PausedRunState.list(session)) == 1


class TestResolvingARun:
    def test_find_by_interruption_resolves_one_record(self):
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        target = PausedRunState.add(session, agent="a", interruptions=_interruptions("i2", "i3"))

        assert PausedRunState.find_by_interruption(session, ["i3"]) == target

    def test_find_by_interruption_returns_none_when_ids_span_two_records(self):
        """One resume addresses one run; the caller reports this rather than guessing."""
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i2"))

        assert PausedRunState.find_by_interruption(session, ["i1", "i2"]) is None

    def test_find_by_interruption_returns_none_when_nothing_matches(self):
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))

        assert PausedRunState.find_by_interruption(session, ["unknown"]) is None

    def test_find_by_interruption_returns_none_for_no_ids(self):
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))

        assert PausedRunState.find_by_interruption(session, []) is None

    def test_duplicate_interruption_id_across_runs_is_rejected(self):
        """Resolution by interruption id only works while the ids are unique across records."""
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))

        with pytest.raises(ValueError, match="already holds a paused run using interruption id"):
            PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))

    def test_duplicate_interruption_id_within_one_run_is_rejected(self):
        """The cross-record check cannot see this one: the ids are compared against what is stored."""
        session = Session("s1")

        with pytest.raises(ValueError, match="repeating interruption id"):
            PausedRunState.add(session, agent="a", interruptions=_interruptions("i1", "i1"))

    def test_a_rejected_record_is_not_stored(self):
        session = Session("s1")

        with pytest.raises(ValueError):
            PausedRunState.add(session, agent="a", interruptions=_interruptions("i1", "i1"))

        assert PausedRunState.list(session) == []


class TestDurability:
    @pytest.mark.asyncio
    async def test_record_survives_a_session_store_round_trip(self):
        """The point of the whole record: a decision may arrive in another process entirely."""
        store = InMemorySessionStore()
        session = store.new("s1")
        record = PausedRunState.add(session, agent="refunds", interruptions=_interruptions("i1"), payload={"state": "blob"})
        store.store(session)

        reloaded = store.load("s1")

        assert PausedRunState.get(reloaded, record.id) == record

    def test_a_non_picklable_payload_is_rejected_at_the_write(self):
        with pytest.raises(TypeError, match="not picklable"):
            PausedRunState.add(Session("s1"), agent="a", interruptions=_interruptions("i1"), payload={"handle": lambda: None})

    def test_the_offending_entry_is_named(self):
        with pytest.raises(TypeError, match="'handle'"):
            PausedRunState.add(Session("s1"), agent="a", interruptions=_interruptions("i1"), payload={"handle": lambda: None})

    def test_clearing_the_non_volatile_cache_discards_pending_decisions(self):
        """Accepted behaviour, pinned so it is known rather than discovered in production."""
        session = Session("s1")
        PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))

        session.get_non_volatile_cache().clear()

        assert PausedRunState.list(session) == []

    def test_warns_once_when_the_session_store_is_process_local(self, caplog):
        session = Session("s1")
        with caplog.at_level(logging.WARNING, logger="ak.paused_run"):
            PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
            PausedRunState.add(session, agent="a", interruptions=_interruptions("i2"))

        assert sum("session.type is 'in_memory'" in r.message for r in caplog.records) == 1


class TestCorruptedCache:
    """The cache is application space, so a read validates rather than trusts."""

    def test_an_unreadable_entry_is_dropped_not_raised(self, caplog):
        session = Session("s1")
        good = PausedRunState.add(session, agent="a", interruptions=_interruptions("i1"))
        session.get_non_volatile_cache().set(AK_PAUSED_RUNS_KEY, [good, {"nonsense": True}])

        with caplog.at_level(logging.WARNING, logger="ak.paused_run"):
            records = PausedRunState.list(session)

        assert [r.id for r in records] == [good.id]
        assert any("unreadable paused-run record" in r.message for r in caplog.records)

    def test_a_non_list_value_is_ignored(self, caplog):
        session = Session("s1")
        session.get_non_volatile_cache().set(AK_PAUSED_RUNS_KEY, "not a list")

        with caplog.at_level(logging.WARNING, logger="ak.paused_run"):
            assert PausedRunState.list(session) == []

    def test_a_record_stored_as_a_dict_is_revalidated(self):
        """Pickle round trips keep the model, but a hand-written or migrated entry may be a dict."""
        session = Session("s1")
        raw = PausedRun(id="r1", agent="a", created_at="2026-01-01T00:00:00+00:00", interruptions=_interruptions("i1"))
        session.get_non_volatile_cache().set(AK_PAUSED_RUNS_KEY, [raw.model_dump()])

        assert PausedRunState.get(session, "r1") == raw


class TestRunnerSurface:
    class _Bare(Runner):
        async def run(self, agent, session, requests):
            return AgentReplyText(response="ok")

        async def stream(self, agent, session, requests):
            raise NotImplementedError()
            yield

    def test_supports_pause_defaults_to_false(self):
        """Unlike supports_streaming, because resume() is a raising default rather than abstract."""
        assert self._Bare("bare").supports_pause is False

    @pytest.mark.asyncio
    async def test_resume_raises_and_names_the_runner(self):
        runner = self._Bare("bare")
        with pytest.raises(NotImplementedError, match="'bare'"):
            await runner.resume(None, Session("s1"), [], [], None)

    @pytest.mark.asyncio
    async def test_resume_stream_raises_and_names_the_runner(self):
        runner = self._Bare("bare")
        with pytest.raises(NotImplementedError, match="'bare'"):
            async for _ in runner.resume_stream(None, Session("s1"), [], [], None):
                pass
