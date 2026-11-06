"""
Session-level identity publication (spec `docs/specs/603-identity-rbac-registry/`, iteration 2).

Four things are pinned here. The `ak.` cache prefix is reserved: application code can read a
reserved key but cannot set, delete or clear one, which is what makes the published principal
unforgeable and keeps pending HITL decisions from being discarded by a `clear()`. `Session` fronts
the published principal, tool filter and owner through accessors, so no caller spells the keys.
`ToolContext` reads the same accessors. And a paused run records who paused it, so a resume can be
checked against that principal.
"""

import pickle
from unittest.mock import MagicMock

import pytest

from agentkernel.core.base import Session
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import AccessLevel, Principal, SessionOwner, ToolFilter
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import ToolContext
from agentkernel.core.util.key_value_cache import KeyValueCache


def _principal(**overrides) -> Principal:
    fields = {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
    fields.update(overrides)
    return Principal(**fields)


def _owner(**overrides) -> SessionOwner:
    fields = {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
    fields.update(overrides)
    return SessionOwner(**fields)


class TestReservedCacheKeys:
    def test_an_application_cannot_set_a_reserved_key(self):
        cache = KeyValueCache()
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            cache.set("ak.principal", "forged")
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            cache["ak.principal"] = "forged"
        assert "ak.principal" not in cache

    def test_an_application_cannot_delete_a_reserved_key(self):
        cache = KeyValueCache()
        cache._set_reserved("ak.thing", 1)
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            cache.delete("ak.thing")
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            del cache["ak.thing"]
        assert cache.get("ak.thing") == 1

    def test_update_refuses_a_reserved_key_and_writes_nothing(self):
        cache = KeyValueCache()
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            cache.update({"fine": 1, "ak.bad": 2})
        assert cache.keys() == []

    def test_reads_of_a_reserved_key_stay_open(self):
        cache = KeyValueCache()
        cache._set_reserved("ak.thing", {"a": 1})
        assert cache.get("ak.thing") == {"a": 1}
        assert cache["ak.thing"] == {"a": 1}
        assert cache.has("ak.thing")
        assert "ak.thing" in cache
        assert "ak.thing" in cache.keys()
        assert ("ak.thing", {"a": 1}) in cache.items()

    def test_clear_keeps_reserved_keys(self):
        cache = KeyValueCache()
        cache.set("app", 1)
        cache._set_reserved("ak.thing", 2)
        cache.clear()
        assert cache.keys() == ["ak.thing"]

    def test_clear_all_removes_reserved_keys_too(self):
        cache = KeyValueCache()
        cache.set("app", 1)
        cache._set_reserved("ak.thing", 2)
        cache._clear_all()
        assert len(cache) == 0

    def test_delete_reserved_reports_whether_the_key_existed(self):
        cache = KeyValueCache()
        cache._set_reserved("ak.thing", 2)
        assert cache._delete_reserved("ak.thing") is True
        assert cache._delete_reserved("ak.thing") is False

    def test_a_missing_application_key_is_still_a_key_error_on_del(self):
        with pytest.raises(KeyError):
            del KeyValueCache()["missing"]

    def test_the_empty_key_is_still_refused(self):
        with pytest.raises(ValueError, match="empty"):
            KeyValueCache().set("", 1)


class TestSessionPublication:
    def test_nothing_is_published_outside_a_run(self):
        session = Session("s1")
        assert session.get_principal() is None
        assert session.get_tool_filter() is None
        assert session.get_owner() is None

    def test_publish_then_unpublish(self):
        session = Session("s1")
        principal = _principal()
        tool_filter = ToolFilter(level=AccessLevel.WRITE, allowed=["search"])
        session._publish_run(principal, tool_filter)
        assert session.get_principal() == principal
        assert session.get_tool_filter() == tool_filter
        session._unpublish_run()
        assert session.get_principal() is None
        assert session.get_tool_filter() is None

    def test_publishing_without_a_filter_clears_a_stale_one(self):
        session = Session("s1")
        session._publish_run(_principal(), ToolFilter(level=AccessLevel.READ, allowed=[]))
        session._publish_run(_principal(), None)
        assert session.get_tool_filter() is None

    def test_the_principal_lives_in_the_volatile_cache_only(self):
        session = Session("s1")
        session._publish_run(_principal(), None)
        assert session.get_volatile_cache().get("ak.principal") == _principal()
        assert session.get_non_volatile_cache().get("ak.principal") is None
        assert "ak.principal" not in dict(session.get_all(volatile=False))

    def test_an_application_cannot_forge_or_remove_the_principal(self):
        session = Session("s1")
        session._publish_run(_principal(), None)
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            session.get_volatile_cache().set("ak.principal", _principal(subject="mallory"))
        with pytest.raises(ValueError, match="reserved for Agent Kernel"):
            session.get_volatile_cache().delete("ak.principal")
        session.get_volatile_cache().clear()
        assert session.get_principal() == _principal()


class TestSessionOwner:
    def test_the_first_owner_is_kept(self):
        session = Session("s1")
        session._record_owner(_owner())
        session._record_owner(_owner(subject="bob"))
        assert session.get_owner() == _owner()

    def test_the_owner_is_durable_and_stored_as_plain_data(self):
        """Stored as a dict, like paused runs: a pickled model would carry its class path into every
        persisted session and break a replica on an older release."""
        session = Session("s1")
        session._record_owner(_owner())
        durable = dict(session.get_all(volatile=False))
        assert durable["owner"] == {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
        restored = Session("s1")
        for key, value in pickle.loads(pickle.dumps(durable)).items():
            restored.set(key, value)
        assert restored.get_owner() == _owner()

    def test_the_owner_survives_session_clear(self):
        session = Session("s1")
        session._record_owner(_owner())
        session.set("openai", {"messages": []})
        session.clear()
        assert session.get("openai") is None
        assert session.get_owner() == _owner()

    def test_a_corrupted_owner_reads_as_none(self):
        session = Session("s1")
        session.set("owner", "garbage")
        assert session.get_owner() is None


class TestToolContextIdentity:
    @pytest.fixture
    def session(self):
        return Session("s1")

    @pytest.fixture
    def context(self, session):
        return ToolContext(MagicMock(spec=Runtime), MagicMock(), session, [])

    def test_nothing_outside_a_run(self, context):
        assert context.principal is None
        assert context.access_level is None

    def test_reads_the_published_run(self, session, context):
        session._publish_run(_principal(), ToolFilter(level=AccessLevel.WRITE, allowed=[]))
        assert context.principal == _principal()
        assert context.access_level is AccessLevel.WRITE

    def test_access_level_is_none_without_a_filter(self, session, context):
        session._publish_run(_principal(), None)
        assert context.principal == _principal()
        assert context.access_level is None


class TestPausedRunIdentity:
    def _pause(self, session: Session):
        return PausedRunState.add(session, agent="a", interruptions=[PausedInterruption(id="i1", kind="tool_call")])

    def test_a_pause_records_who_paused(self):
        session = Session("s1")
        session._publish_run(_principal(), None)
        record = self._pause(session)
        assert (record.subject, record.provider, record.namespace) == ("alice", "oidc", "https://issuer.example")
        stored = PausedRunState.get(session, record.id)
        assert stored is not None and (stored.subject, stored.namespace) == ("alice", "https://issuer.example")

    def test_an_anonymous_run_records_no_subject(self):
        session = Session("s1")
        session._publish_run(Principal.anonymous(), None)
        record = self._pause(session)
        assert (record.subject, record.provider, record.namespace) == (None, None, None)

    def test_a_pause_outside_a_published_run_records_no_subject(self):
        assert self._pause(Session("s1")).subject is None

    def test_pending_decisions_survive_an_application_clearing_the_cache(self):
        session = Session("s1")
        record = self._pause(session)
        session.get_non_volatile_cache().clear()
        assert [r.id for r in PausedRunState.list(session)] == [record.id]
