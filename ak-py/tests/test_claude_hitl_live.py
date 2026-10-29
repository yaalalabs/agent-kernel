"""Opt-in Claude CLI pause/resume smoke test; requires real Claude credentials."""

import os
import pickle

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from agentkernel.core import Runtime, Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentPausedReplyAny, AgentRequestText, ResumeDecision
from agentkernel.core.paused_run import PausedRunState
from agentkernel.framework.claude.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder


def _has_claude_credentials() -> bool:
    return any(os.getenv(key) for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"))


@pytest.mark.skipif(
    os.getenv("AK_RUN_CLAUDE_LIVE_TESTS") != "1" or not _has_claude_credentials(),
    reason="Set AK_RUN_CLAUDE_LIVE_TESTS=1 and configure Claude credentials to run the live CLI test",
)
@pytest.mark.asyncio
async def test_deferred_tool_survives_a_new_runner_and_resumes_once():
    calls: list[int] = []

    async def approve_action(value: int) -> str:
        """Record one approved action."""
        calls.append(value)
        return f"approved {value}"

    spec = ClaudeAgentSpec(
        name="approval_smoke",
        options=ClaudeAgentOptions(
            system_prompt="Call the approve_action tool with value 7 before replying. Do not answer without calling it.",
            tools=[],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=3,
        ),
        tools=ClaudeToolBuilder.bind([approve_action], needs_approval=True),
    )
    session = Session("claude-live-hitl")

    with Runtime(SessionStoreBuilder.build()):
        first_agent = ClaudeModule([spec]).get_agent(spec.name)
        paused = await first_agent.runner.run(first_agent, session, [AgentRequestText(prompt="Please do the action now.")])
        assert isinstance(paused, AgentPausedReplyAny), paused
        assert calls == []

        # Restore the AK session and adapter as another worker would.
        session = pickle.loads(pickle.dumps(session))
        resumed_agent = ClaudeModule([spec]).get_agent(spec.name)
        record = PausedRunState.get(session, paused.run_id)
        decision = ResumeDecision(id=paused.interruptions[0].id, status="approved")
        reply = await resumed_agent.runner.resume(resumed_agent, session, [], [decision], record)

    assert not isinstance(reply, AgentPausedReplyAny), reply
    assert calls == [7]
    assert PausedRunState.get(session, paused.run_id) is None
