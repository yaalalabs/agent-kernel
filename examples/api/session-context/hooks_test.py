"""
Unit test for HistoryTrimHook, exercised directly against the core primitives.

Unlike app_test.py (which drives the real OpenAI Agents SDK over HTTP), this test needs no
network access or OPENAI_API_KEY: it fabricates the OpenAI framework session directly and
proves that Session.get_framework_session() hands back a *live* reference - mutating it
through its own methods is visible on the next call, with no session.set(...) needed.
"""

import pytest
from agentkernel.core.base import Agent as BaseAgent
from agentkernel.core.base import Runner as BaseRunner
from agentkernel.core.base import Session
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.framework.openai.openai import FRAMEWORK, OpenAISession

from hooks import HistoryTrimHook


class _StubRunner(BaseRunner):
    """Runner whose name matches FRAMEWORK ("openai"), the key OpenAISession is stored under."""

    def __init__(self):
        super().__init__(FRAMEWORK)

    async def run(self, agent, session, requests):
        raise NotImplementedError()

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


@pytest.mark.asyncio
async def test_history_trim_hook_mutates_the_live_framework_session():
    session = Session("hooks-unit-test-session")
    agent = _StubAgent("qa_assistant", _StubRunner())

    openai_session = OpenAISession()
    await openai_session.add_items([{"role": "user", "content": f"msg-{i}"} for i in range(30)])
    session.set(FRAMEWORK, openai_session)

    hook = HistoryTrimHook()
    reply = AgentReplyText(response="ok")

    # _activate() is what Runtime.run()/stream() use internally to set Agent.current() for the
    # duration of a hook/tool call - reproducing that scope here is what makes
    # session.get_framework_session() resolvable in this test.
    with agent._activate():
        returned = await hook.on_run(session, [AgentRequestText(prompt="hi")], agent, reply)

        # The hook never called session.set(...); get_framework_session() must still reflect
        # the in-place mutation because it's the exact same object reference.
        trimmed = session.get_framework_session()

    assert returned is reply
    assert trimmed is openai_session
    items = await trimmed.get_items()
    assert len(items) == HistoryTrimHook.THRESHOLD
    assert items[0]["content"] == f"msg-{30 - HistoryTrimHook.THRESHOLD}"  # oldest items dropped
    assert items[-1]["content"] == "msg-29"  # most recent item retained


@pytest.mark.asyncio
async def test_history_trim_hook_is_a_noop_under_the_limit():
    session = Session("hooks-unit-test-session-2")
    agent = _StubAgent("qa_assistant", _StubRunner())

    openai_session = OpenAISession()
    await openai_session.add_items([{"role": "user", "content": "only message"}])
    session.set(FRAMEWORK, openai_session)

    hook = HistoryTrimHook()
    with agent._activate():
        await hook.on_run(session, [AgentRequestText(prompt="hi")], agent, AgentReplyText(response="ok"))
        items = await session.get_framework_session().get_items()

    assert len(items) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
