"""The mock agent: replies with an echo of the prompt after a random delay, so the benchmark measures AK, not a model."""

import asyncio
import os
import random
import uuid
from collections.abc import AsyncGenerator

from agentkernel.core import Agent, AgentReplyAny, AgentRequestText, MessageEnd, MessageStart, Runner, TextDelta

AGENT_NAME = "bench"
MIN_DELAY_ENV, MAX_DELAY_ENV = "AK_BENCH_MOCK_AGENT_MIN_DELAY_S", "AK_BENCH_MOCK_AGENT_MAX_DELAY_S"


def mock_delays() -> tuple[float, float] | None:
    """(min, max) seconds that ak-bench deploy passed in from its `mock_agent` config (checked there), else None for the real agent."""
    low, high = os.environ.get(MIN_DELAY_ENV) or None, os.environ.get(MAX_DELAY_ENV) or None
    # A half-configured mock is a broken deployment, never a silent fall-back to the real (billed) agent.
    if (low is None) != (high is None):
        raise RuntimeError(f"set both {MIN_DELAY_ENV} and {MAX_DELAY_ENV} for the mock agent, or neither for the real agent")
    return None if low is None else (float(low), float(high))


class MockRunner(Runner):
    """Sleeps a uniform random delay in [min, max] seconds, then echoes the prompt. Keeps no state besides the delays."""

    def __init__(self):
        super().__init__("MockRunner")
        self._min, self._max = mock_delays()

    async def run(self, agent, session, requests) -> AgentReplyAny:
        await asyncio.sleep(random.uniform(self._min, self._max))
        return AgentReplyAny(content={"echo": self._prompt(requests)})

    async def stream(self, agent, session, requests) -> AsyncGenerator:
        await asyncio.sleep(random.uniform(self._min, self._max))
        message_id = str(uuid.uuid4())
        yield MessageStart(message_id=message_id)
        yield TextDelta(message_id=message_id, content=self._prompt(requests))
        yield MessageEnd(message_id=message_id)

    @staticmethod
    def _prompt(requests) -> str:
        return next((r.prompt for r in requests if isinstance(r, AgentRequestText)), "")


class MockAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, MockRunner())

    def get_description(self) -> str:
        return "Benchmark mock agent"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass
