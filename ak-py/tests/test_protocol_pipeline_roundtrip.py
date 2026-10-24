"""End to end over the in_memory transport: an A2A message and an MCP tool call run on the agent runner (#780).

The executors enqueue and wait; a pump thread stands in for the agent runner and the Response
Handler, so the agent provably runs on that thread rather than in the request's. The in_memory
transport and store take the same code paths a broker deployment does: only the wire differs.
"""

import threading
import uuid

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest
from fastmcp import Client

from agentkernel.api.a2a.a2a import A2A
from agentkernel.api.http import RESTAPI
from agentkernel.api.mcp.akmcp import MCP
from agentkernel.core.base import Agent, Runner
from agentkernel.core.builder import A2ACardBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

AGENT_NAME = "pump-agent"
PUMP_THREAD = "agent-runner-pump"
BASE_URL = "http://ak.test"


class CountingRunner(Runner):
    """Replies with the prompt, the thread it ran on, and the session's turn count."""

    runs: list[tuple[str, str]] = []

    async def run(self, agent, session, requests):
        cache = session.get_non_volatile_cache()
        turn = (cache.get("turns") or 0) + 1
        cache.set("turns", turn)
        thread = threading.current_thread().name
        CountingRunner.runs.append((thread, session.id))
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"{prompt}|thread={thread}|turn={turn}")

    async def stream(self, agent, session, requests):  # pragma: no cover - a tagged message never streams
        raise AssertionError("a protocol request must take the single-reply path")
        yield


class CountingAgent(Agent):
    def __init__(self):
        super().__init__(AGENT_NAME, CountingRunner("CountingRunner"))

    def get_description(self) -> str:
        return "Round-trip test agent"

    def get_a2a_card(self):
        return A2ACardBuilder.build(name=AGENT_NAME, description="Round-trip test agent", skills=[])

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class Pump:
    """The agent runner and Response Handler, draining both queues on one named thread."""

    def __init__(self, stream: bool):
        transport = InMemoryTransport()
        self._runner = StreamAgentRunner(transport=transport) if stream else AgentRunner(transport=transport)
        self._responder = ResponseHandler(transport=transport)
        self._consumers = [
            (transport.create_consumer(QueueName.INPUT), self._runner.process),
            (transport.create_consumer(QueueName.OUTPUT), self._responder.process),
        ]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=PUMP_THREAD, daemon=True)
        self.errors: list[Exception] = []

    def __enter__(self) -> "Pump":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            for consumer, process in self._consumers:
                for message in consumer.fetch(10, 0.02):
                    try:
                        process(message)
                    except Exception as e:  # surfaced by the test instead of killing the pump
                        self.errors.append(e)
                    consumer.ack(message)


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    # A fast wait budget: up to 200 reads 20 ms apart.
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT", "200")
    monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__DELAY", "0.02")
    # The card's interface URL, which the A2A client sends to.
    monkeypatch.setenv("AK_A2A__URL", f"{BASE_URL}/a2a")
    AKConfig._reset()
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    CountingRunner.runs = []
    saved_a2a = (dict(A2A._cards), dict(A2A._executors), A2A._built, A2A._client)
    saved_mcp = (MCP._fastmcp, MCP._built, dict(MCP._executors), MCP._client)
    A2A._cards, A2A._executors, A2A._built, A2A._client = {}, {}, False, None
    MCP._fastmcp, MCP._built, MCP._executors, MCP._client = None, False, {}, None
    agent = CountingAgent()
    Runtime.current().register(agent)
    yield
    Runtime.current().deregister(agent)
    A2A._cards, A2A._executors, A2A._built, A2A._client = saved_a2a
    MCP._fastmcp, MCP._built, MCP._executors, MCP._client = saved_mcp
    InMemoryResponseStore.reset()
    InMemoryTransport.reset()
    AKConfig._reset()


def _configure(monkeypatch, mode=None, **env):
    if mode:
        monkeypatch.setenv("AK_EXECUTION__MODE", mode)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()


async def _a2a_send(texts: list[str], context_id: str) -> list[str]:
    """Send each text as one A2A message:send in the same context, the way an A2A client does."""
    app = RESTAPI.build_app(handlers=[])
    agent_url = f"{BASE_URL}/a2a/{AGENT_NAME}"
    replies = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL, timeout=10) as http:
        card = await A2ACardResolver(http, base_url=agent_url).get_agent_card()
        # The factory picks the card's HTTP+JSON interface and sends the A2A-Version: 1.0 header.
        client = ClientFactory(ClientConfig(streaming=False, httpx_client=http, supported_protocol_bindings=["HTTP+JSON"])).create(card)
        for text in texts:
            message = Message(message_id=str(uuid.uuid4()), context_id=context_id, role=Role.ROLE_USER, parts=[Part(text=text)])
            async for item in client.send_message(SendMessageRequest(message=message)):
                replies.append(get_message_text(item.message))
    return replies


async def _mcp_call(prompts: list[str], session_id: str) -> list[str]:
    replies = []
    async with Client(MCP.get()) as client:
        for prompt in prompts:
            result = await client.call_tool(AGENT_NAME, {"prompt": prompt, "session_id": session_id})
            replies.append(result.content[0].text)
    return replies


class TestA2A:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", [None, "stream"])
    async def test_message_send_runs_on_the_runner_and_keeps_the_session(self, monkeypatch, mode):
        _configure(monkeypatch, mode, AK_A2A__ENABLED="true")
        context_id = f"a2a-{uuid.uuid4()}"

        with Pump(stream=mode == "stream") as pump:
            replies = await _a2a_send(["first", "second"], context_id)

        assert pump.errors == []
        assert replies == [f"first|thread={PUMP_THREAD}|turn=1", f"second|thread={PUMP_THREAD}|turn=2"]
        assert CountingRunner.runs == [(PUMP_THREAD, context_id), (PUMP_THREAD, context_id)]


class TestMCP:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", [None, "async", "stream"])
    async def test_call_tool_runs_on_the_runner_and_keeps_the_session(self, monkeypatch, mode):
        _configure(monkeypatch, mode, AK_MCP__ENABLED="true", AK_MCP__EXPOSE_AGENTS="true")
        session_id = f"mcp-{uuid.uuid4()}"

        with Pump(stream=mode == "stream") as pump:
            replies = await _mcp_call(["first", "second"], session_id)

        assert pump.errors == []
        assert replies == [f"first|thread={PUMP_THREAD}|turn=1", f"second|thread={PUMP_THREAD}|turn=2"]
        assert CountingRunner.runs == [(PUMP_THREAD, session_id), (PUMP_THREAD, session_id)]

    @pytest.mark.asyncio
    async def test_a2a_and_mcp_share_one_session_through_the_queue(self, monkeypatch):
        """One session id is one AK session (and one queue group), whichever surface it came in by."""
        _configure(monkeypatch, AK_A2A__ENABLED="true", AK_MCP__ENABLED="true", AK_MCP__EXPOSE_AGENTS="true")
        session_id = f"shared-{uuid.uuid4()}"

        with Pump(stream=False) as pump:
            [via_a2a] = await _a2a_send(["hello"], session_id)
            [via_mcp] = await _mcp_call(["again"], session_id)

        assert pump.errors == []
        assert via_a2a.endswith("turn=1")
        assert via_mcp.endswith("turn=2")
