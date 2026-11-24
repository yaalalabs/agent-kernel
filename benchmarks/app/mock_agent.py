"""The mock agent: replies with an echo of the prompt after a random delay, so the benchmark measures AK, not a model."""

import asyncio
import random
import uuid
from collections.abc import AsyncGenerator

from agentkernel.core.base import Agent, Runner
from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
from agentkernel.core.model import AgentReplyAny, AgentRequestText
from bench_config import BenchAppConfig

AGENT_NAME = "bench"


class MockRunner(Runner):
    """Sleeps a uniform random delay in [min, max] seconds, then echoes the prompt. Keeps no state besides the delays."""

    def __init__(self):
        super().__init__("MockRunner")
        self._min, self._max = BenchAppConfig.get().mock_delays

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
