"""Tool gates on a realtime call (spec `docs/specs/603-identity-rbac-registry/` sections 8.4 and 9, iteration 23).

A realtime call has no `Runtime.run` around a tool call: the framework's native session runs its own tools, and
the connection publishes the identity those calls act as. So the connection publishes a tool filter too, and the
gates the OpenAI and ADK adapters put on their native agents read it, as they do on a turn.

One call can have several participants (a LiveKit room), each speaking into the same session, so the filter is
the room's: a tool is offered only when every participant who has spoken may use it, at the lowest level among
them. Which participant spoke last decides nothing, so no participant can borrow another's level.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from agents import function_tool
from agents.realtime import RealtimeAgent
from agents.realtime.model import RealtimeModel
from agents.realtime.model_events import RealtimeModelToolCallEvent, RealtimeModelTurnEndedEvent, RealtimeModelTurnStartedEvent
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agentkernel import Agent, Runner, Session
from agentkernel.core.config import AKConfig, _RealtimeConfig
from agentkernel.core.model import AccessLevel, AgentReplyText, AgentRequestText, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.framework.adk.adk import GoogleADKModule
from agentkernel.framework.openai.openai import OpenAIModule
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.realtime.base import RealtimeRunner
from agentkernel.realtime.connection import RealtimeConnection

ALICE = Principal(subject="alice", provider="realtime:livekit", namespace="lk-key", groups=["support"])
BOB = Principal(subject="bob", provider="realtime:livekit", namespace="lk-key", groups=["callers"])
CAROL = Principal(subject="carol", provider="realtime:livekit", namespace="lk-key")

# alice may write, bob may only read, carol holds nothing. `refund` is a write tool. A realtime sender is granted
# through a group (or `provider:`), never `user:`, which matches only a subject an identity provider verified.
GRANTS = [
    {"subjects": ["group:support"], "agents": ["voice"], "level": "write"},
    {"subjects": ["group:callers"], "agents": ["voice"], "level": "read"},
]
TOOLS = [{"agent": "voice", "tiers": {"refund": "write"}}]
REFUND_FOR_READ = "Tool 'refund' requires level write; the current principal has read"


@pytest.fixture(autouse=True)
def _pipeline(monkeypatch):
    async def send_inline(send, *args):
        return send(*args)

    monkeypatch.setattr("agentkernel.realtime.connection.asyncio.to_thread", send_inline)
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()


@pytest.fixture
def policy(authorization):
    authorization(grants=GRANTS, tools=TOOLS)


def _connection(agent: Agent, runtime: Runtime, session_id: str = "call-1") -> RealtimeConnection:
    connection = RealtimeConnection(
        session_id,
        agent,
        runtime,
        Session(session_id),
        asyncio.get_running_loop(),
        transport=QueueTransportFactory.create(),
        playback_lead_ms=_RealtimeConfig().playback_lead_ms,
    )
    connection.update_delivery_context("req", None, None, {})
    return connection


async def _speak(connection: RealtimeConnection, *principals: Principal | None) -> None:
    """Dispatch an input from each participant in turn; the publication lands on the connection's loop."""
    for principal in principals:
        connection.publish_principal(principal)
    await asyncio.sleep(0)


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


# --- the room's filter ------------------------------------------------------------------------------


class _Quiet(RealtimeRunner):
    def __init__(self):
        super().__init__("quiet")

    async def connect(self, session, agent, callback):
        pass

    async def append_audio(self, base64_audio):
        pass

    async def send_text(self, text):
        pass

    async def disconnect(self):
        pass


class _NoTurns(Runner):
    def __init__(self):
        super().__init__("no-turns")

    async def run(self, agent, session, requests):
        return AgentReplyText(response="")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Voice(Agent):
    """A voice agent with a read tool and a write tool."""

    def __init__(self):
        super().__init__("voice", _NoTurns(), realtime_runner_cls=_Quiet)

    def get_tool_names(self) -> list[str]:
        return ["lookup", "refund"]

    def get_description(self):
        return ""

    def attach_tool(self, tool):
        pass

    def override_system_prompt(self, prompt):
        pass


class TestTheRoomsFilter:
    @pytest.fixture
    def call(self, policy):
        """Returns a function opening a call to the voice agent; it needs the test's running loop."""
        runtime = Runtime(InMemorySessionStore())
        with runtime:
            yield lambda: _connection(_Voice(), runtime)

    @pytest.mark.asyncio
    async def test_one_caller_is_offered_what_their_level_allows(self, call):
        connection = call()
        await _speak(connection, ALICE)

        published = connection.session.get_tool_filter()
        assert (published.level, published.allowed) == (AccessLevel.WRITE, frozenset({"lookup", "refund"}))

    @pytest.mark.asyncio
    async def test_a_participant_with_a_lower_level_narrows_what_the_room_is_offered(self, call):
        connection = call()
        await _speak(connection, ALICE, BOB)

        published = connection.session.get_tool_filter()
        assert (published.level, published.allowed) == (AccessLevel.READ, frozenset({"lookup"}))
        assert published.reason("refund") == REFUND_FOR_READ

    @pytest.mark.asyncio
    async def test_who_spoke_last_decides_nothing(self, call):
        connection = call()
        # The race the spec left open: alice speaking after bob does not lend the room her level back.
        await _speak(connection, BOB, ALICE)
        after_alice = connection.session.get_tool_filter()
        await _speak(connection, BOB, ALICE)

        assert after_alice.allowed == connection.session.get_tool_filter().allowed == frozenset({"lookup"})
        assert connection.session.get_principal().subject == "alice"  # the identity a tool reads is still the speaker's

    @pytest.mark.asyncio
    async def test_a_participant_holding_no_level_leaves_the_room_no_tool(self, call):
        connection = call()
        await _speak(connection, ALICE, CAROL)

        published = connection.session.get_tool_filter()
        assert published.allowed == frozenset()
        assert published.reason("lookup") == "Tool 'lookup' is not available while a participant in this call holds no level on agent 'voice'"

    @pytest.mark.asyncio
    async def test_a_participant_the_authorizer_cannot_answer_for_leaves_no_tool_until_it_can(self, call, monkeypatch):
        # Failing closed: the room loses its tools, not keeps the last filter, and the next input asks again.
        from agentkernel.identity.authz.gate import AccessGate

        monkeypatch.setattr(RealtimeConnection, "RETRY_PAUSE_SECONDS", 0.0)
        connection = call()
        await _speak(connection, ALICE)
        asked: list[str] = []
        working = AccessGate.tool_filter

        def flaky(self, principal, agent, level=None):
            asked.append(principal.subject)
            if principal.subject == "bob" and asked.count("bob") == 1:
                raise RuntimeError("the policy engine is down")
            return working(self, principal, agent, level)

        monkeypatch.setattr(AccessGate, "tool_filter", flaky)
        await _speak(connection, BOB)
        while_down = connection.session.get_tool_filter()
        await _speak(connection, BOB)

        assert while_down.allowed == frozenset()
        assert while_down.reason("lookup") == "tool gate failed: RuntimeError"
        assert asked == ["bob", "bob"]
        published = connection.session.get_tool_filter()
        assert (published.level, published.allowed) == (AccessLevel.READ, frozenset({"lookup"}))

    @pytest.mark.asyncio
    async def test_a_participant_not_yet_answered_for_still_narrows_the_room_when_another_speaks(self, call, monkeypatch):
        # bob has spoken, so the room stays without tools while his decision is missing, whoever speaks next; it is
        # asked for again on his next input, and then the room is what both of them may use.
        from agentkernel.identity.authz.gate import AccessGate

        monkeypatch.setattr(RealtimeConnection, "RETRY_PAUSE_SECONDS", 0.0)
        connection = call()
        asked: list[str] = []
        working = AccessGate.tool_filter

        def flaky(self, principal, agent, level=None):
            asked.append(principal.subject)
            if principal.subject == "bob" and asked.count("bob") == 1:
                raise RuntimeError("the policy engine is down")
            return working(self, principal, agent, level)

        monkeypatch.setattr(AccessGate, "tool_filter", flaky)
        await _speak(connection, BOB, ALICE)
        after_alice = connection.session.get_tool_filter()
        await _speak(connection, ALICE)
        assert asked == ["bob", "alice"]  # alice's own repeated input asks nobody again
        await _speak(connection, BOB)

        assert after_alice.allowed == frozenset()
        assert after_alice.reason("refund") == "tool gate failed: RuntimeError"
        assert asked == ["bob", "alice", "bob"]
        published = connection.session.get_tool_filter()
        assert (published.level, published.allowed) == (AccessLevel.READ, frozenset({"lookup"}))
        assert published.reason("refund") == REFUND_FOR_READ

    @pytest.mark.asyncio
    async def test_a_participant_the_authorizer_failed_for_is_not_asked_again_until_the_pause_has_passed(self, call, monkeypatch):
        # Every audio chunk is an input: without a pause an authorizer that is down would be asked on each one.
        from agentkernel.identity.authz.gate import AccessGate

        connection = call()
        asked: list[str] = []
        working = AccessGate.tool_filter

        def down_once(self, principal, agent, level=None):
            asked.append(principal.subject)
            if len(asked) == 1:
                raise RuntimeError("the policy engine is down")
            return working(self, principal, agent, level)

        monkeypatch.setattr(AccessGate, "tool_filter", down_once)
        monkeypatch.setattr(RealtimeConnection, "RETRY_PAUSE_SECONDS", 3600.0)
        await _speak(connection, BOB, BOB, BOB)
        during_the_pause = connection.session.get_tool_filter()
        monkeypatch.setattr(RealtimeConnection, "RETRY_PAUSE_SECONDS", 0.0)
        await _speak(connection, BOB)

        assert during_the_pause.allowed == frozenset()
        assert during_the_pause.reason("lookup") == "tool gate failed: RuntimeError"
        assert asked == ["bob", "bob"]
        assert connection.session.get_tool_filter().allowed == frozenset({"lookup"})

    @pytest.mark.asyncio
    async def test_a_room_decision_that_fails_for_another_reason_leaves_no_tool_and_raises_nothing(self, call, monkeypatch):
        # Raising would hand the input back to the pool's queue; the room loses its tools and the next input asks again.
        connection = call()
        await _speak(connection, ALICE)
        working, calls = Runtime._acting, []

        def broken_once(agent, principal):
            calls.append(principal)
            if len(calls) == 1:
                raise RuntimeError("the acting principal could not be built")
            return working(agent, principal)

        monkeypatch.setattr(Runtime, "_acting", staticmethod(broken_once))
        await _speak(connection, BOB)
        while_broken = connection.session.get_tool_filter()
        await _speak(connection, BOB)

        assert while_broken.allowed == frozenset()
        assert while_broken.reason("lookup") == "tool gate failed: RuntimeError"
        assert connection.session.get_tool_filter().allowed == frozenset({"lookup"})

    @pytest.mark.asyncio
    async def test_closing_the_call_unpublishes_the_filter(self, call):
        connection = call()
        await _speak(connection, ALICE)

        await connection.close()

        assert connection.session.get_tool_filter() is None


class TestWithoutTheBlock:
    @pytest.mark.asyncio
    async def test_no_filter_is_published(self):
        runtime = Runtime(InMemorySessionStore())
        with runtime:
            connection = _connection(_Voice(), runtime)
            await _speak(connection, ALICE, BOB)

        assert connection.session.get_tool_filter() is None
        assert connection.session.get_principal().subject == "bob"


# --- OpenAI's native realtime session ------------------------------------------------------------


class _ScriptedRealtimeModel(RealtimeModel):
    """Answers the first user input with one response that calls the named tools, then stays quiet."""

    def __init__(self, *calls: str):
        self.calls = list(calls)
        self.sent: list = []
        self.listeners: list = []
        self._open: set[str] = set()
        self._tasks: list[asyncio.Task] = []

    async def connect(self, options):
        pass

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    async def send_event(self, event):
        self.sent.append(event)
        if isinstance(event, RealtimeModelSendUserInput) and self.calls:
            calls, self.calls = self.calls, []
            # Delivered from a task of its own, as the real transport's listener delivers every event.
            self._tasks.append(asyncio.create_task(self._respond(calls)))
        elif isinstance(event, RealtimeModelSendToolOutput):
            self._open.discard(event.tool_call.call_id)

    async def _respond(self, calls: list[str]):
        await asyncio.sleep(0.01)
        await self._emit(RealtimeModelTurnStartedEvent(response_id="r1"))
        for name in calls:
            self._open.add(f"call-{name}")
            await self._emit(RealtimeModelToolCallEvent(name=name, call_id=f"call-{name}", arguments=json.dumps({"order_id": "7"})))
        await self._emit(RealtimeModelTurnEndedEvent(response_id="r1"))

    async def _emit(self, event):
        for listener in list(self.listeners):
            await listener.on_event(event)

    async def close(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def tool_outputs(self) -> dict[str, str]:
        return {event.tool_call.name: event.output for event in self.sent if isinstance(event, RealtimeModelSendToolOutput)}


class TestOpenAIRealtime:
    @pytest.mark.asyncio
    async def test_a_tool_the_rooms_filter_denies_is_not_run(self, policy):
        ran: list[str] = []

        @function_tool
        async def lookup(order_id: str) -> str:
            """Look an order up."""
            ran.append("lookup")
            return f"order {order_id}"

        @function_tool
        async def refund(order_id: str) -> str:
            """Refund an order."""
            ran.append("refund")
            return f"refunded {order_id}"

        model = _ScriptedRealtimeModel("lookup", "refund")
        with Runtime(InMemorySessionStore()) as runtime:
            agent = OpenAIModule([RealtimeAgent(name="voice", instructions="Help.", tools=[lookup, refund])]).get_agent("voice")
            agent.run_options.update(model=model)
            connection = _connection(agent, runtime)
            await _speak(connection, ALICE, BOB)
            await connection.connect()
            try:
                connection.send_text(AgentRequestText(prompt="refund order 7"))
                await _until(lambda: len(model.tool_outputs()) == 2)
            finally:
                await connection.close()

        # The realtime session asks `is_enabled` on every call and runs no input guardrail for an ordinary one,
        # so the denied tool is one it does not find: refused, and the model is not told why.
        assert ran == ["lookup"]
        assert model.tool_outputs() == {"lookup": "order 7", "refund": "Tool refund not found"}


# --- ADK's live flow -------------------------------------------------------------------------------


class _RecordedConnection(BaseLlmConnection):
    def __init__(self, script):
        self.script, self.closed, self.sent = script, False, []

    async def send_history(self, history):
        pass

    async def send_content(self, content):
        self.sent.append(content)

    async def send_realtime(self, blob):
        pass

    async def receive(self):
        for response in self.script:
            yield response
        while not self.closed:
            await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True


class _CallingLiveModel(BaseLlm):
    """A Live model whose connection calls the named function tools once."""

    model: str = "calling-live"
    calls: list[str] = []
    opened: list = []

    async def generate_content_async(self, llm_request, stream=False):
        raise NotImplementedError("live only")
        yield

    @asynccontextmanager
    async def connect(self, llm_request):
        parts = [types.Part(function_call=types.FunctionCall(id=f"call-{name}", name=name, args={"order_id": "7"})) for name in self.calls]
        connection = _RecordedConnection([LlmResponse(content=types.Content(role="model", parts=parts))])
        self.opened.append(connection)
        try:
            yield connection
        finally:
            connection.closed = True

    def responses(self) -> dict[str, dict]:
        return {
            part.function_response.name: part.function_response.response
            for connection in self.opened
            for content in connection.sent
            for part in (getattr(content, "parts", None) or [])
            if part.function_response
        }


class TestADKRealtime:
    @pytest.mark.asyncio
    async def test_a_tool_the_rooms_filter_denies_is_not_run_and_the_model_is_told(self, policy, monkeypatch):
        monkeypatch.setattr(AKConfig.get().execution.realtime, "playback_lead_ms", _RealtimeConfig().playback_lead_ms)
        ran: list[str] = []

        def lookup(order_id: str) -> str:
            """Look an order up."""
            ran.append("lookup")
            return f"order {order_id}"

        def refund(order_id: str) -> str:
            """Refund an order."""
            ran.append("refund")
            return f"refunded {order_id}"

        model = _CallingLiveModel(calls=["lookup", "refund"], opened=[])
        with Runtime(InMemorySessionStore()) as runtime:
            agent = GoogleADKModule([LlmAgent(name="voice", model=model, tools=[lookup, refund])]).get_agent("voice")
            connection = _connection(agent, runtime)
            await _speak(connection, ALICE, BOB)
            await connection.connect()
            try:
                await _until(lambda: len(model.responses()) == 2)
            finally:
                await connection.close()

        assert ran == ["lookup"]
        assert model.responses() == {"lookup": {"result": "order 7"}, "refund": {"error": REFUND_FOR_READ}}
