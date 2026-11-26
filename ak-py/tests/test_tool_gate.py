"""`ToolGate` (spec `docs/specs/603-identity-rbac-registry/` section 9, iteration 21).

The gate is what a framework adapter asks before it offers or runs a tool. It decides nothing: `Runtime`
publishes one `ToolFilter` per run when an `authorization` block is configured, and the gate reads it. These
tests cover the gate on its own; each adapter's use of it is in `test_tool_gates_<adapter>.py`.
"""

from unittest.mock import MagicMock

import pytest

from agentkernel.core import ToolContext, ToolGate
from agentkernel.core.base import Session
from agentkernel.core.model import AccessLevel, Principal, ToolFilter

ALICE = Principal(subject="alice", provider="oidc", namespace="https://issuer.example")
REASON = "Tool 'refund' requires level admin; the current principal has write"


def _session(tool_filter: ToolFilter | None) -> Session:
    session = Session("s1")
    session._publish_run(ALICE, tool_filter)
    return session


def _filter() -> ToolFilter:
    return ToolFilter(level=AccessLevel.WRITE, allowed=frozenset({"lookup"}), reasons={"refund": REASON})


@pytest.fixture
def running():
    """Returns a function that makes a session the one of the current `ToolContext`, as a runner does for a run."""
    contexts: list[ToolContext] = []

    def _run(session: Session) -> Session:
        contexts.append(ToolContext(MagicMock(), MagicMock(), session, []).set())
        return session

    yield _run
    for context in reversed(contexts):
        context.reset()


class TestCurrent:
    def test_the_filter_published_on_the_session_handed_in(self):
        tool_filter = _filter()

        assert ToolGate.current(_session(tool_filter)) is tool_filter

    def test_a_run_nothing_gates_has_no_filter(self):
        assert ToolGate.current(_session(None)) is None

    def test_without_a_session_it_is_the_one_of_the_current_tool_context(self, running):
        tool_filter = _filter()
        running(_session(tool_filter))

        assert ToolGate.current() is tool_filter

    def test_outside_a_run_nothing_is_gated(self):
        # A native hook that fires with no run in progress (the application calling its agent directly).
        assert ToolGate.current() is None

    def test_the_session_handed_in_wins_over_the_current_one(self, running):
        running(_session(None))
        tool_filter = _filter()

        assert ToolGate.current(_session(tool_filter)) is tool_filter


class TestRefusal:
    def test_an_allowed_tool_is_not_refused(self):
        assert ToolGate.refusal("lookup", _session(_filter())) is None

    def test_a_denied_tool_is_refused_with_the_reason_the_filter_recorded(self):
        assert ToolGate.refusal("refund", _session(_filter())) == REASON

    def test_a_tool_the_filter_never_listed_is_refused(self):
        # The filter is over the tools the agent declares: one it does not declare is offered by no policy.
        assert ToolGate.refusal("drop_tables", _session(_filter())) == "Tool 'drop_tables' is not available to the current principal"

    def test_nothing_is_refused_in_a_run_that_is_not_gated(self):
        assert ToolGate.refusal("refund", _session(None)) is None

    def test_nothing_is_refused_outside_a_run(self):
        assert ToolGate.refusal("refund") is None

    def test_without_a_session_the_current_run_is_asked(self, running):
        running(_session(_filter()))

        assert ToolGate.refusal("refund") == REASON
        assert ToolGate.refusal("lookup") is None


class TestAGateThatCannotAnswer:
    """Fail closed: a gate that breaks is no reason to run the tool, and no exception reaches the framework."""

    def test_a_filter_that_cannot_be_read_refuses_the_tool(self):
        class _Unreadable(Session):
            def get_tool_filter(self):
                raise RuntimeError("the cache is gone")

        assert ToolGate.refusal("lookup", _Unreadable("s1")) == "tool gate failed: RuntimeError"

    def test_a_filter_that_cannot_decide_refuses_the_tool(self):
        class _Undecided:
            def allows(self, name):
                raise KeyError(name)

        class _Session(Session):
            def get_tool_filter(self):
                return _Undecided()

        assert ToolGate.refusal("lookup", _Session("s1")) == "tool gate failed: KeyError"


class TestDenyResult:
    def test_it_is_the_reason_the_filter_gives(self):
        tool_filter = _filter()

        assert ToolGate.deny_result("refund", tool_filter) == REASON
        assert ToolGate.deny_result("unlisted", tool_filter) == tool_filter.reason("unlisted")
