"""
An AK system tool that acts as the caller works inside a live call (#928), on both framework adapters.

The real ``create_schedule`` tool, attached by the real attach path, is run by the real OpenAI Agents SDK realtime session
(a scripted ``RealtimeModel``) and by ADK's real ``run_live()`` (a fake live model), through the real ``RealtimeConnection``
and, for the last case, the real pool thread and ``dispatch``. What is asserted is whose identity the tool acted as: the
principal of the input that came before it, the anonymous principal refused, and a changed principal followed.

This is what a refactor of how the pool publishes identity and scopes a run must not break.
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from agents.realtime import (
    RealtimeAgent,
    RealtimeModel,
    RealtimeModelToolCallEvent,
    RealtimeModelTurnEndedEvent,
    RealtimeModelTurnStartedEvent,
)
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.base_llm import BaseLlm
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agentkernel.core import Session
from agentkernel.core.model import AgentRequestText, BaseRunRequest, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.framework.adk.adk import GoogleADKModule
from agentkernel.framework.openai.openai import OpenAIModule
from agentkernel.pipeline.realtime_pool import RealtimeConnection, RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.schedule.manager import ScheduleManager
from agentkernel.schedule.provider.base import ScheduleProvider
from agentkernel.schedule.store.in_memory import InMemoryScheduleStore
from agentkernel.schedule.tools import get_schedule_tools

HUMAN = Principal(subject="human", provider="realtime:livekit", namespace="lk-key")
GUEST = Principal(subject="guest", provider="realtime:livekit", namespace="lk-key")
ARGS = json.dumps({"prompt": "remind me", "at": "2030-06-01T09:00:00"})


class _Provider(ScheduleProvider):
    def create(self, task, body_template):
        return f"ref-{task.task_id}"

    def update(self, task, body_template):
        pass

    def delete(self, provider_ref):
        pass

    def get(self, provider_ref):
        return {}


@pytest.fixture
def manager(monkeypatch):
    """A real ``ScheduleManager`` over the in-memory store, and the real schedule tools attached to every agent."""
    store = InMemoryScheduleStore()
    store.clear()
    instance = ScheduleManager(provider=_Provider(), store=store)
    monkeypatch.setattr(ScheduleManager, "get", classmethod(lambda cls: instance))
    tools = get_schedule_tools()
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: tools))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    InMemoryTransport.reset()
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
    ThreadRunner.shutdown_event.clear()
    yield instance
    store.clear()
    InMemoryTransport.reset()
    RealtimeConnectionPool.reset()
    ThreadRunner.shutdown_event.clear()


async def _until(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


# --- OpenAI: a scripted RealtimeModel, as tests/test_openai_realtime.py drives the real SDK session ----


class ScriptedModel(RealtimeModel):
    """Plays one scripted response per request. Events reach the session from one listener task created while connecting,
    as the real websocket transport does: that is the task whose context the SDK's tool tasks inherit."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.sent: list[Any] = []
        self.listeners: list[Any] = []
        self._open_calls: set[str] = set()
        self._inbox: asyncio.Queue | None = None
        self._listener: asyncio.Task | None = None

    async def connect(self, options):
        self._inbox = asyncio.Queue()
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self):
        while True:
            step = await self._inbox.get()
            await asyncio.sleep(0.01)  # a real model answers after the SDK has recorded the tool output
            await step(self)

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    async def send_event(self, event):
        self.sent.append(event)
        if isinstance(event, RealtimeModelSendUserInput):
            self._respond()
        elif isinstance(event, RealtimeModelSendToolOutput):
            self._open_calls.discard(event.tool_call.call_id)
            if event.start_response and not self._open_calls:
                self._respond()

    def _respond(self):
        if self.steps:
            self._inbox.put_nowait(self.steps.pop(0))

    async def emit(self, event):
        for listener in list(self.listeners):
            await listener.on_event(event)

    async def close(self):
        if self._listener is not None and self._listener is not asyncio.current_task():
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)

    def tool_outputs(self) -> dict[str, dict]:
        return {e.tool_call.call_id: json.loads(e.output) for e in self.sent if isinstance(e, RealtimeModelSendToolOutput)}


def _calls_create_schedule(response_id: str, call_id: str):
    async def step(model: ScriptedModel):
        await model.emit(RealtimeModelTurnStartedEvent(response_id=response_id))
        model._open_calls.add(call_id)
        await model.emit(RealtimeModelToolCallEvent(name="create_schedule", call_id=call_id, arguments=ARGS))
        await model.emit(RealtimeModelTurnEndedEvent(response_id=response_id))

    return step


def _says_nothing(response_id: str):
    async def step(model: ScriptedModel):
        await model.emit(RealtimeModelTurnStartedEvent(response_id=response_id))
        await model.emit(RealtimeModelTurnEndedEvent(response_id=response_id))

    return step


def _openai_agent(model: ScriptedModel):
    module = OpenAIModule([RealtimeAgent(name="voice", instructions="Speak.")])
    agent = module.get_agent("voice")
    agent.run_options.update(model=model)
    return agent


class TestOpenAIRealtime:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("principal", [HUMAN, None], ids=["caller", "anonymous"])
    async def test_the_tool_acts_as_the_input_principal_or_refuses_an_anonymous_one(self, manager, principal):
        with Runtime(InMemorySessionStore()) as runtime:
            model = ScriptedModel(_calls_create_schedule("r1", "c1"), _says_nothing("r2"))
            agent = _openai_agent(model)
            assert "create_schedule" in [tool.name for tool in agent.agent.tools]
            conn = RealtimeConnection("call-1", agent, runtime, Session("call-1"), asyncio.get_running_loop())
            conn.update_delivery_context("req", None, None, {})
            await conn.connect()
            try:
                conn.publish_principal(principal)  # what dispatch() does per input, ahead of the input itself
                conn.send_text(AgentRequestText(prompt="remind me later"))
                await _until(lambda: "c1" in model.tool_outputs())
            finally:
                await conn.close()

        output = model.tool_outputs()["c1"]
        if principal is None:
            assert output == {"error": "scheduling requires an authenticated principal"}
            return
        task = manager.get_task(output["task_id"], "human")
        assert (task.principal["subject"], task.principal["provider"], task.principal["namespace"]) == ("human", "realtime:livekit", "lk-key")
        assert task.session_id == "call-1"

    @pytest.mark.asyncio
    async def test_each_tool_call_acts_as_the_principal_of_the_input_before_it(self, manager):
        """Through the real pool thread and ``dispatch``: the principal changes between two inputs of one call."""
        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            with Runtime(InMemorySessionStore()) as runtime:
                model = ScriptedModel(
                    _calls_create_schedule("r1", "c1"), _says_nothing("r2"), _calls_create_schedule("r3", "c2"), _says_nothing("r4")
                )
                agent = _openai_agent(model)
                handler = SimpleNamespace(service=SimpleNamespace(agent=agent, runtime=runtime, session=Session("call-2")))
                chat_service = SimpleNamespace(prepare_agent_handler=lambda session_id, agent_name: handler)

                def dispatch(principal, text):
                    body = BaseRunRequest(prompt="", session_id="call-2", requests=[AgentRequestText(prompt=text)], principal=principal)
                    pool.dispatch(body, "req", None, {"integration": "livekit"}, chat_service)

                await asyncio.to_thread(dispatch, HUMAN, "first")
                await _until(lambda: "c1" in model.tool_outputs())
                await asyncio.to_thread(dispatch, GUEST, "second")
                await _until(lambda: "c2" in model.tool_outputs())
                outputs = model.tool_outputs()
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(5)

        assert manager.get_task(outputs["c1"]["task_id"], "human").principal["subject"] == "human"
        assert manager.get_task(outputs["c2"]["task_id"], "guest").principal["subject"] == "guest"
        with pytest.raises(PermissionError):  # the guest cannot reach the human's task
            manager.get_task(outputs["c1"]["task_id"], "guest")


# --- ADK: run_live() with a fake live model that calls the tool ---------------------------------------


class _FakeConnection(BaseLlmConnection):
    def __init__(self, script):
        self.script, self.closed = script, False

    async def send_history(self, history):
        pass

    async def send_content(self, content):
        pass

    async def send_realtime(self, blob):
        pass

    async def receive(self):
        for response in self.script:
            yield response
        while not self.closed:
            await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True


class _CallsCreateSchedule(BaseLlm):
    model: str = "fake-live"

    async def generate_content_async(self, llm_request, stream=False):
        raise NotImplementedError("live only")
        yield

    @asynccontextmanager
    async def connect(self, llm_request):
        call = types.FunctionCall(id="c1", name="create_schedule", args=json.loads(ARGS))
        connection = _FakeConnection([LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))])
        try:
            yield connection
        finally:
            connection.closed = True


async def _adk_tool_results(session: Session) -> list[dict]:
    """The responses ADK recorded for the tool calls it ran, read back from the ADK session the adapter keeps on the AK session."""
    adk_session = session.get("adk")
    refreshed = await adk_session.session_service.get_session(app_name="AgentKernel", user_id="AgentKernel", session_id=session.id)
    return [json.loads(r.response["result"]) for event in refreshed.events for r in event.get_function_responses()]


class TestADKRealtime:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("principal", [HUMAN, None], ids=["caller", "anonymous"])
    async def test_the_tool_acts_as_the_input_principal_or_refuses_an_anonymous_one(self, manager, principal):
        with Runtime(InMemorySessionStore()) as runtime:
            module = GoogleADKModule([LlmAgent(name="voice", model=_CallsCreateSchedule())])
            module.run_options(module.get_agent("voice").agent, run_config=RunConfig(response_modalities=["AUDIO"]))
            agent = module.get_agent("voice")
            session = Session("call-3")
            conn = RealtimeConnection("call-3", agent, runtime, session, asyncio.get_running_loop())
            conn.update_delivery_context("req", None, None, {})
            conn.publish_principal(principal)  # ahead of the first input, as dispatch() does
            await asyncio.sleep(0)
            await conn.connect()
            try:
                results = []
                for _ in range(500):
                    results = await _adk_tool_results(session)
                    if results:
                        break
                    await asyncio.sleep(0.01)
            finally:
                await conn.close()

        assert len(results) == 1, "ADK did not run the tool"
        if principal is None:
            assert results[0] == {"error": "scheduling requires an authenticated principal"}
            return
        task = manager.get_task(results[0]["task_id"], "human")
        assert task.principal["subject"] == "human" and task.session_id == "call-3"
