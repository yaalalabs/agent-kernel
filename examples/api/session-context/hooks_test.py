"""
Unit test for HistoryTrimHook, exercised through Runtime.run() - the public path used by REST/CLI
apps - rather than the framework internals it relies on.

Unlike app_test.py (which drives the real OpenAI Agents SDK over HTTP), this test needs no
network access or OPENAI_API_KEY: it fabricates the OpenAI framework session directly and
proves that Session.get_framework_session() hands back a *live* reference - mutating it
through its own methods is visible on the next call, with no session.set(...) needed.
"""

import pytest
from agentkernel.core.base import Agent as BaseAgent
from agentkernel.core.base import Runner as BaseRunner
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.openai.openai import FRAMEWORK, OpenAISession

from hooks import HistoryTrimHook


class _StubRunner(BaseRunner):
    """Runner whose name matches FRAMEWORK ("openai"), the key OpenAISession is stored under."""

    def __init__(self):
        super().__init__(FRAMEWORK)

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _StubAgent(BaseAgent):
    def get_description(self):
        return ""

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


async def _run_with_history(num_items: int) -> tuple[AgentReplyText, list]:
    """Runs the stub agent (with HistoryTrimHook registered as a post-hook) through
    Runtime.run() against a session pre-seeded with num_items OpenAI-native history items."""
    runtime = Runtime(InMemorySessionStore())
    agent = _StubAgent("qa_assistant", _StubRunner())
    agent.post_hooks.append(HistoryTrimHook())

    session = runtime.sessions().new("hooks-unit-test-session")
    openai_session = OpenAISession()
    await openai_session.add_items([{"role": "user", "content": f"msg-{i}"} for i in range(num_items)])
    session.set(FRAMEWORK, openai_session)

    # Runtime.run() is what REST/CLI apps call; it sets Agent.current() for the duration of the
    # call (pre-hooks, the runner, and post-hooks), which is what makes
    # session.get_framework_session() resolvable inside HistoryTrimHook. Driving the hook this
    # way exercises the real pipeline instead of reproducing Runtime's internals.
    reply = await runtime.run(agent, session, [AgentRequestText(prompt="hi")])

    # get_framework_session() only resolves while an agent is active, so re-fetch after run()
    # returns via the plain key the OpenAI adapter stores it under - same live object either way.
    stored = session.get(FRAMEWORK)
    assert stored is openai_session
    items = await stored.get_items()
    return reply, items


@pytest.mark.asyncio
async def test_history_trim_hook_caps_the_live_framework_session():
    reply, items = await _run_with_history(30)

    assert isinstance(reply, AgentReplyText)
    assert reply.response == "ok"
    assert len(items) == HistoryTrimHook.THRESHOLD
    assert items[0]["content"] == f"msg-{30 - HistoryTrimHook.THRESHOLD}"  # oldest items dropped
    assert items[-1]["content"] == "msg-29"  # most recent item retained


@pytest.mark.asyncio
async def test_history_trim_hook_is_a_noop_under_the_limit():
    _, items = await _run_with_history(1)

    assert len(items) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
