import logging
import socket

import pytest

from agentkernel.core.base import Runner, Session
from agentkernel.core.hooks import PostHook, PreHook
from agentkernel.core.model import AgentReplyText
from agentkernel.core.session.serde import BinarySerde

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


class SeedingPreHook(PreHook):
    """Pre-hook that seeds the context before the runner loads it, the documented seeding path."""

    def __init__(self, seed: dict):
        self._seed = seed

    async def on_run(self, session, agent, requests):
        session = Session.current()
        if session.get_framework_context() is None:
            session.set_framework_context(dict(self._seed))
        return requests

    def name(self) -> str:
        return "seeding-prehook"


class ObservingPostHook(PostHook):
    """Post-hook that reads the written-back context, and records what it saw."""

    def __init__(self):
        self.observed: dict | None = None

    async def on_run(self, session, requests, agent, agent_reply):
        self.observed = Session.current().get_framework_context()
        return agent_reply

    def name(self) -> str:
        return "observing-posthook"


class TestSessionFrameworkContextAccessors:
    def test_get_on_fresh_session_returns_none_and_leaves_key_absent(self):
        """A plain read must not flip a session from 'no context' into 'present but empty'."""
        session = Session("s")

        assert session.get_framework_context() is None
        assert FRAMEWORK_CONTEXT not in dict(session.get_all())
        assert DummyRunner()._load_framework_context(session) is None

    def test_get_returns_the_live_object(self):
        """Hooks get the live dict, so an edit is the stored context (contrast: the runner gets a copy)."""
        session = Session("s")
        session.set_framework_context({"a": 1})

        session.get_framework_context()["a"] = 2

        assert session.get_framework_context() == {"a": 2}

    @pytest.mark.parametrize("value", [None, [], "x", 42, AgentReplyText(response="not a dict")])
    def test_set_rejects_non_dict(self, value):
        session = Session("s")

        with pytest.raises(TypeError) as exc:
            session.set_framework_context(value)

        message = str(exc.value)
        assert "framework_context must be a dict" in message
        assert type(value).__name__ in message
        assert session.id in message
        assert session.get_framework_context() is None

    def test_set_accepts_empty_dict_as_present(self):
        session = Session("s")

        assert session.set_framework_context({}) == {}
        assert session.get_framework_context() == {}

    def test_clear_removes_the_key_and_is_idempotent(self):
        session = Session("s")
        session.set_framework_context({"a": 1})

        session.clear_framework_context()
        assert session.get_framework_context() is None

        session.clear_framework_context()
        assert session.get_framework_context() is None

    def test_context_survives_serde_round_trip(self):
        """The durability claim: the key is a normal durable key, not pre-initialized state."""
        session = Session("s")
        session.set_framework_context({"cart": ["apple"]})

        restored = BinarySerde.loads(BinarySerde.dumps(session))

        assert restored.get_framework_context() == {"cart": ["apple"]}

    def test_session_clear_drops_the_context(self):
        """Session.clear() rebuilds from the two caches only, so a reset session has no context."""
        session = Session("s")
        session.set_framework_context({"a": 1})

        session.clear()

        assert session.get_framework_context() is None

    @pytest.mark.asyncio
    async def test_pre_hook_seed_reaches_the_runner_and_post_hook_sees_the_write_back(self):
        """Hooks are the accessors' scope: the pre-hook's seed is injected, the post-hook sees the result."""
        session = Session("s")
        pre_hook = SeedingPreHook({"count": 0})
        post_hook = ObservingPostHook()
        runner = CountingRunner()

        async with session:
            await pre_hook.on_run(None, None, [])
            reply = await runner.run(None, session, [])
            await post_hook.on_run(None, [], None, reply)

        assert post_hook.observed == {"count": 1}


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

    @pytest.mark.parametrize("stored", [["a", "b"], "ctx", 42])
    def test_non_dict_stored_value_raises_named_typeerror(self, stored):
        """A non-dict is rejected at load, before it can reach adapter injection code."""
        runner = DummyRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, stored)

        with pytest.raises(TypeError) as exc:
            runner._load_framework_context(session)

        message = str(exc.value)
        assert "framework_context must be a dict" in message
        assert type(stored).__name__ in message
        assert session.id in message

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

    def test_stream_failure_is_logged_not_raised(self, caplog):
        """Stream write-back failures are logged so the turn's session store still runs."""
        runner = DummyRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"ok": 1})

        with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            try:
                runner._store_framework_context(session, {"ok": 1}, {"bad": lambda: 1})
            except Exception as e:
                runner._log_framework_context_stream_failure(session, e)

        assert session.get(FRAMEWORK_CONTEXT) == {"ok": 1}
        assert any("framework_context write-back was skipped" in r.message and session.id in r.message for r in caplog.records)

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
