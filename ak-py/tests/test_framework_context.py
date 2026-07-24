import socket

import pytest

from agentkernel.core.base import Runner, Session
from agentkernel.core.model import AgentReplyText

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class DummyRunner(Runner):
    """Minimal Runner used to exercise the base framework_context plumbing directly."""

    def __init__(self, name: str = "dummy"):
        super().__init__(name)

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class CountingRunner(DummyRunner):
    """Loads the framework_context, increments a counter, and writes it back via the helpers."""

    async def run(self, agent, session, requests):
        incoming = self._load_framework_context(session)
        produced = dict(incoming or {})
        produced["count"] = produced.get("count", 0) + 1
        self._store_framework_context(session, incoming, produced)
        return AgentReplyText(response=str(produced["count"]))


class TestFrameworkContextLoad:
    def test_absent_key_loads_none(self):
        runner = DummyRunner()
        session = Session("s")
        assert runner._load_framework_context(session) is None

    def test_none_session_loads_none(self):
        runner = DummyRunner()
        assert runner._load_framework_context(None) is None

    def test_present_empty_dict_loads_empty_dict(self):
        runner = DummyRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {})
        assert runner._load_framework_context(session) == {}

    def test_load_returns_deep_copy(self):
        """Mutating the loaded object must not touch the stored object (crash-isolation)."""
        runner = DummyRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"a": {"n": 1}})

        loaded = runner._load_framework_context(session)
        loaded["a"]["n"] = 99
        loaded["b"] = "new"

        assert session.get(FRAMEWORK_CONTEXT) == {"a": {"n": 1}}


class TestFrameworkContextStore:
    def test_absent_key_never_written(self):
        """incoming is None (key absent this turn) → never overwrite the key."""
        runner = DummyRunner()
        session = Session("s")
        runner._store_framework_context(session, None, {"a": 1})
        assert session.get(FRAMEWORK_CONTEXT) is None

    def test_none_session_noop(self):
        runner = DummyRunner()
        # Must not raise when there is no session.
        runner._store_framework_context(None, {"a": 1}, {"b": 2})

    def test_present_empty_is_preserved(self):
        """A caller-set {} is 'present' and must be written back, not dropped as None."""
        runner = DummyRunner()
        session = Session("s")
        runner._store_framework_context(session, {}, None)
        assert session.get(FRAMEWORK_CONTEXT) == {}

    def test_shallow_merge_last_write_wins(self):
        runner = DummyRunner()
        session = Session("s")
        runner._store_framework_context(session, {"a": 1, "b": 2}, {"b": 9, "c": 3})
        assert session.get(FRAMEWORK_CONTEXT) == {"a": 1, "b": 9, "c": 3}

    def test_nested_replaced_wholesale_not_deep_merged(self):
        runner = DummyRunner()
        session = Session("s")
        runner._store_framework_context(session, {"nested": {"x": 1, "y": 2}}, {"nested": {"z": 3}})
        assert session.get(FRAMEWORK_CONTEXT) == {"nested": {"z": 3}}

    def test_untouched_caller_keys_preserved(self):
        runner = DummyRunner()
        session = Session("s")
        runner._store_framework_context(session, {"seeded": "keep"}, {})
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": "keep"}


class TestFrameworkContextRoundTrip:
    @pytest.mark.asyncio
    async def test_round_trip_across_turns(self):
        runner = CountingRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"count": 0})

        await runner.run(None, session, [])
        assert session.get(FRAMEWORK_CONTEXT) == {"count": 1}

        await runner.run(None, session, [])
        assert session.get(FRAMEWORK_CONTEXT) == {"count": 2}


class TestFrameworkContextPicklability:
    def test_non_picklable_raises_named_typeerror(self):
        runner = DummyRunner()
        session = Session("s")
        with pytest.raises(TypeError) as exc:
            runner._store_framework_context(session, {}, {"bad": lambda: 1})
        message = str(exc.value)
        assert "framework_context is not picklable" in message
        assert "'bad'" in message
        assert session.id in message

    def test_non_picklable_leaves_previous_value_intact(self):
        """The picklability check runs before session.set, so a failure preserves the prior value."""
        runner = DummyRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"ok": 1})

        sock = socket.socket()
        try:
            with pytest.raises(TypeError):
                runner._store_framework_context(session, {"ok": 1}, {"conn": sock})
        finally:
            sock.close()

        assert session.get(FRAMEWORK_CONTEXT) == {"ok": 1}
