from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, List, Type

from agents import Agent, Runner, function_tool
from openai.types.responses.response_output_item_added_event import ResponseOutputItemAddedEvent
from openai.types.responses.response_output_item_done_event import ResponseOutputItemDoneEvent
from openai.types.responses.response_reasoning_summary_text_delta_event import ResponseReasoningSummaryTextDeltaEvent
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook
from ...core import RealtimeRunner as BaseRealtimeRunner
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from ...core.model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentRequestVoice,
    ExecutionMode,
)
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "openai"

_log = logging.getLogger("ak.openai.runner")


class OpenAISession:
    """
    OpenAISession class provides a session for OpenAI Agents SDK-based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAISession instance.
        """
        self._items = []

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """
        Retrieve items stored in this session.
        :param limit: Optional limit on the number of items to retrieve.
        :return: List of items in the session.
        """
        if limit is not None:
            if limit <= 0:
                return []
            return self._items[-limit:]
        return self._items

    async def add_items(self, items: List[dict]) -> None:
        """
        Add items to this session.
        :param items: List of items to add.
        """
        self._items.extend(items)

    async def pop_item(self) -> dict | None:
        """
        Remove and return the most recent item from this session.
        :return: The most recent item, or None if the session is empty.
        """
        if self._items:
            return self._items.pop()
        return None

    async def clear_session(self) -> None:
        """
        Clear all items for this session.
        """
        self._items.clear()


class OpenAIRunner(BaseRunner):
    """
    OpenAIRunner class provides a runner for OpenAI Agents SDK based agents.
    """

    def __init__(self):
        """
        Initializes an OpenAIRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> OpenAISession | None:
        """
        Returns the OpenAI session associated with the provided session.
        :param session: The session to retrieve the OpenAI session for.
        :return: OpenAISession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, OpenAISession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[dict]]:
        """
        Process requests and extract prompt text and message content.
        :param requests: The requests to process.
        :return: Tuple of (prompt, message_content).
        """
        prompt = ""
        message_content = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                text = req.prompt
                prompt = prompt + "\n" + text if prompt else text
                message_content.append({"role": "user", "content": text})

            elif isinstance(req, AgentRequestImage):
                if not req.image_data:
                    raise ValueError("no image input provided")

                image_url = req.image_data
                if not image_url.startswith(("http://", "https://", "s3://", "data:")):
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                    mime_type = req.mime_type
                    image_url = f"data:{mime_type};base64,{image_url}"

                message_content.append({"role": "user", "content": [{"type": "input_image", "detail": "auto", "image_url": image_url}]})

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")

                file_url = req.file_data
                if file_url.startswith(("http://", "https://", "s3://")):
                    message_content.append({"role": "user", "content": [{"type": "input_file", "file_url": file_url}]})
                else:
                    mime_type = req.mime_type
                    if not file_url.startswith(("data:")):
                        if not req.mime_type:
                            raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                        file_url = f"data:{mime_type};base64,{file_url}"

                message_content.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_file", "filename": req.name, "file_data": file_url}],
                    }
                )

            elif isinstance(req, AgentRequestVoice):
                if not req.audio_data:
                    raise ValueError("no audio input provided")

                audio_data = req.audio_data
                if audio_data.startswith(("http://", "https://", "s3://")):
                    # The Responses API audio part takes inline base64 only; a remote reference
                    # has no native mapping here rather than a silently wrong shape.
                    raise ValueError("remote audio URLs are not supported as OpenAI audio input; provide base64 audio data")

                if audio_data.startswith("data:"):
                    mime_type = audio_data.split(";")[0][5:]
                    audio_data = audio_data.split(",", 1)[-1]
                else:
                    mime_type = req.mime_type or "audio/wav"

                # Responses accepts only mp3/wav, so the MIME subtype is normalised to those names.
                audio_format = {"mpeg": "mp3", "mp3": "mp3", "wav": "wav", "x-wav": "wav", "wave": "wav"}.get(mime_type.split("/")[-1])
                if audio_format is None:
                    raise ValueError(f"unsupported audio format '{mime_type}' for OpenAI audio input; supported: mp3, wav")

                message_content.append(
                    {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": audio_data, "format": audio_format}}]}
                )

        return prompt, message_content

    @staticmethod
    def _get_run_input(prompt: str, message_content: list[dict]) -> Any:
        """
        Determine the input format for OpenAI agent (text-only vs multimodal).

        A single text request is passed as the bare prompt string; anything else is passed as the
        message list the SDK needs for structured content. The choice is about shape only — the
        session goes with either, so a turn carrying an attachment is remembered like any other.

        :param prompt: The prompt text.
        :param message_content: The message content list.
        :return: The input to hand to the SDK runner.
        """
        if len(message_content) == 1 and isinstance(message_content[0].get("content"), str):
            return prompt
        return message_content

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the OpenAI agent with provided multi modal inputs.
        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, message_content = self._process_requests(requests)

            if not message_content:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            input_data = self._get_run_input(prompt, message_content)
            # Injected as the run context, so tools read and write it via RunContextWrapper.context.
            # A deep copy is passed in so tools mutating it in place don't also mutate `incoming`.
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            reply = (await Runner.run(agent.agent, input_data, session=self._session(session), context=produced)).final_output

            self._store_framework_context(session, incoming, produced)

            structured = AgentReplyAny.from_output(reply, prompt)
            if structured is not None:
                return structured

            reply_text = "" if reply is None else str(reply)
            return AgentReplyText(response=reply_text, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the OpenAI agent response as Agent Kernel stream events.

        Two SDK stream-event kinds are read — neither alone is enough:

        - **Raw response events** carry message/reasoning boundaries and text deltas. They are the
          only source for a *start* (`message_output_created` fires too late).
        - **Run item events** carry tool calls (and handoffs). Arguments arrive whole on
          `tool_called`, so the call is opened, filled, and closed in one go.

        Correlation ids come from the SDK (`item.id`, `call_id`); nothing is generated or stored
        on the shared `Runner` between events.

        :param agent: The OpenAI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, message_content = self._process_requests(requests)

            if not message_content:
                return

            input_data = self._get_run_input(prompt, message_content)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            result = Runner.run_streamed(agent.agent, input_data, session=self._session(session), context=produced)

            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    for stream_event in self._map_raw_response(event.data):
                        yield stream_event
                elif event.type == "run_item_stream_event":
                    for stream_event in self._map_run_item(event.name, event.item):
                        yield stream_event

            # Only after the stream drains normally, so a disconnect or framework error leaves the stored
            # context intact. Deliberately not in a finally.
            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    @staticmethod
    def _map_raw_response(data: Any) -> list[StreamEvent]:
        """
        Translate one raw OpenAI response event into AK events.

        `response.output_item.added` / `.done` bracket both prose and reasoning (item `type`
        decides which). Empty deltas are dropped.

        :param data: The `event.data` payload of a `raw_response_event`.
        :return: The AK events this raw event produces, or an empty list when unmapped.
        """
        if isinstance(data, ResponseOutputItemAddedEvent):
            item = data.item
            if item.type == "message":
                return [MessageStart(message_id=item.id, role=item.role)]
            if item.type == "reasoning":
                return [ReasoningStart(message_id=item.id)]
            return []
        if isinstance(data, ResponseOutputItemDoneEvent):
            item = data.item
            if item.type == "message":
                return [MessageEnd(message_id=item.id)]
            if item.type == "reasoning":
                return [ReasoningEnd(message_id=item.id)]
            return []
        if isinstance(data, ResponseTextDeltaEvent):
            return [TextDelta(message_id=data.item_id, content=data.delta)] if data.delta else []
        if isinstance(data, ResponseReasoningSummaryTextDeltaEvent):
            return [ReasoningDelta(message_id=data.item_id, content=data.delta)] if data.delta else []
        return []

    @staticmethod
    def _map_run_item(name: str, item: Any) -> list[StreamEvent]:
        """
        Translate one `RunItemStreamEvent` into AK events.

        Maps `tool_called` / `tool_output` and the handoff pair (`handoff_requested` /
        `handoff_occured` — SDK spelling). Handoffs share tool-call shapes (`call_id`, `name`,
        `arguments` / output), so they reuse the same branches. Hosted-tool and MCP names, plus
        `message_output_created` / `reasoning_item_created` (already covered by raw events), stay
        unmapped. Items without a `call_id` emit nothing.

        :param name: The `RunItemStreamEvent.name` discriminator.
        :param item: The `RunItem` the event wraps.
        :return: The AK events this item produces, or an empty list when unmapped.
        """
        if name not in ("tool_called", "tool_output", "handoff_requested", "handoff_occured"):
            return []

        raw = getattr(item, "raw_item", None)
        call_id = OpenAIRunner._raw_field(raw, "call_id")
        if not call_id:
            _log.debug(f"OpenAI '{name}' item carries no call_id; not emitted")
            return []

        if name in ("tool_called", "handoff_requested"):
            tool_name = OpenAIRunner._raw_field(raw, "name") or ""
            arguments = OpenAIRunner._raw_field(raw, "arguments")
            events: list[StreamEvent] = [ToolCallStart(tool_call_id=call_id, name=tool_name)]
            if arguments:
                events.append(ToolCallArgs(tool_call_id=call_id, delta=arguments))
            events.append(ToolCallEnd(tool_call_id=call_id))
            return events

        # Prefer raw_item.output (what the model saw) over item.output (native tool return).
        content = OpenAIRunner._raw_field(raw, "output")
        if content is None:
            content = getattr(item, "output", None)
        return [ToolCallResult(tool_call_id=call_id, content="" if content is None else str(content))]

    @staticmethod
    def _raw_field(raw: Any, field: str) -> Any:
        """
        Read one field off a `RunItem.raw_item` (Pydantic model on some paths, dict on others).

        :param raw: The item's `raw_item` value.
        :param field: Field name to read.
        :return: The field value, or `None` if missing.
        """
        if isinstance(raw, dict):
            return raw.get(field)
        return getattr(raw, field, None)


class OpenAIRealtimeAdapter(BaseRealtimeRunner):
    """
    OpenAIRealtimeAdapter implements RealtimeRunner for the OpenAI Realtime WebSocket API.
    """

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._connection = None
        self._callback = None
        self._cm = None
        self._listen_task = None
        # The edge publishes one transcript per turn (on done), so deltas are accumulated here
        # rather than sent one-per-token, which would flood the output queue.
        self._transcript: list[str] = []

    @staticmethod
    def _realtime_model(agent: BaseAgent) -> str:
        """The realtime model named by the agent definition.

        Deliberately no adapter-level default: the model is the agent's choice, and a silent
        fallback would run a different model than the one the caller declared.
        """
        model = getattr(getattr(agent, "agent", None), "model", None)
        if not isinstance(model, str) or not model:
            raise ValueError(f"Agent '{getattr(agent, 'name', '?')}' must define a realtime model to run in REALTIME mode")
        return model

    async def connect(self, session: Session, agent: BaseAgent, callback: Callable) -> None:
        from openai import AsyncOpenAI

        self._callback = callback
        client = AsyncOpenAI()
        model = self._realtime_model(agent)

        self._audio_queue = asyncio.Queue()
        self._cm = client.realtime.connect(model=model)
        self._connection = await self._cm.__aenter__()

        sdk_agent = getattr(agent, "agent", None)
        instructions = getattr(sdk_agent, "instructions", None) or "You are a helpful assistant."

        tools_payload = []
        if sdk_agent and hasattr(sdk_agent, "tools"):
            for tool in sdk_agent.tools:
                if type(tool).__name__ == "FunctionTool":
                    tools_payload.append(
                        {"type": "function", "name": tool.name, "description": tool.description, "parameters": tool.params_json_schema}
                    )

        await self._connection.send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": instructions,
                    "tools": tools_payload,
                    "audio": {"input": {"turn_detection": {"type": "server_vad", "interrupt_response": True, "create_response": True}}},
                },
            }
        )

        self._pacing_task = asyncio.create_task(self._pacing_loop())
        self._listen_task = asyncio.create_task(self._listen())

    async def _pacing_loop(self) -> None:
        """Emit model audio at playback rate, with control events behind their own audio.

        ``_audio_queue`` carries a base64 audio string for a delta, or an ``(event_type, data)``
        tuple for a terminal/control event. Routing ``done``/``interrupt`` through this queue
        (rather than calling back from ``_listen`` directly) keeps them from overtaking the
        audio that is still being paced out — the output queue is FIFO per session, so an event
        emitted early would reach the edge before the audio it belongs to.
        """
        import base64
        import time

        item_start_time = 0.0
        audio_played_ms = 0.0

        while True:
            try:
                item = await self._audio_queue.get()
                if not isinstance(item, str):
                    event_type, data = item
                    await self._callback(event_type, data)
                    if event_type in ("done", "interrupt"):
                        audio_played_ms = 0.0
                    continue

                if audio_played_ms == 0.0:
                    item_start_time = time.time()

                await self._callback("audio_delta", {"delta": item})

                audio_bytes = base64.b64decode(item)
                duration_ms = (len(audio_bytes) / 2) / 24.0
                audio_played_ms += duration_ms

                elapsed_ms = (time.time() - item_start_time) * 1000.0
                target_elapsed_ms = audio_played_ms - 50.0
                sleep_ms = target_elapsed_ms - elapsed_ms
                if sleep_ms > 0:
                    await asyncio.sleep(sleep_ms / 1000.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _log.error(f"Error in pacing loop: {e}")

    async def _listen(self) -> None:
        try:
            async for event in self._connection:
                event_type = event.type
                if event_type == "response.output_audio.delta":
                    self._audio_queue.put_nowait(event.delta)
                elif event_type == "response.output_audio_transcript.delta":
                    self._transcript.append(event.delta)
                elif event_type == "input_audio_buffer.speech_started":
                    # Barge-in: drop audio not yet played, then queue the interrupt behind it so
                    # it cannot overtake audio already in flight to the edge.
                    while not self._audio_queue.empty():
                        self._audio_queue.get_nowait()
                    self._audio_queue.put_nowait(("interrupt", {}))
                elif event_type == "response.done":
                    response = getattr(event, "response", None)
                    status = getattr(response, "status", None)
                    transcript = "".join(self._transcript).strip() if status == "completed" else ""
                    self._transcript.clear()
                    self._audio_queue.put_nowait(("done", {"status": status, "transcript": transcript}))
                elif event_type == "response.function_call_arguments.done":
                    await self._callback(
                        "tool_call",
                        {
                            "call_id": getattr(event, "call_id", None),
                            "name": getattr(event, "name", None),
                            "arguments": getattr(event, "arguments", "{}"),
                        },
                    )
                elif event_type == "error":
                    _log.error(f"OpenAI Realtime socket error: {getattr(event, 'error', 'unknown')}")
        except Exception as e:
            _log.error(f"OpenAI Realtime socket error: {e}")

    async def append_audio(self, base64_audio: str) -> None:
        if self._connection:
            await self._connection.send({"type": "input_audio_buffer.append", "audio": base64_audio})

    async def send_text(self, text: str) -> None:
        if self._connection:
            await self._connection.send(
                {"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}
            )
            await self._connection.send({"type": "response.create"})

    async def send_tool_result(self, call_id: str, result: str) -> None:
        if self._connection:
            await self._connection.send(
                {"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": call_id, "output": result}}
            )
            await self._connection.send({"type": "response.create"})

    async def disconnect(self) -> None:
        if hasattr(self, "_pacing_task") and self._pacing_task:
            self._pacing_task.cancel()
        if self._listen_task:
            self._listen_task.cancel()
        if self._connection:
            await self._cm.__aexit__(None, None, None)
            self._connection = None


class OpenAIAgent(BaseAgent):
    """
    OpenAIAgent class provides an agent wrapping for OpenAI Agent SDK-based agents.
    """

    def __init__(self, name: str, runner: OpenAIRunner, agent: Agent, realtime_runner_cls: Type[BaseRealtimeRunner] = None):
        """
        Initializes an OpenAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The OpenAI agent instance.
        :param realtime_runner_cls: Optional realtime adapter class for this agent.
        """
        super().__init__(name, runner, realtime_runner_cls=realtime_runner_cls)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        """
        Returns the OpenAI agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.instructions

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the OpenAI agent's instructions.
        Called by the base Agent._setup_system_prompt() at init when multimodal is enabled.
        """
        if hasattr(self._agent, "instructions") and self._agent.instructions:
            if prompt not in self._agent.instructions:
                self._agent.instructions += "\n" + prompt

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable and wraps it with OpenAIToolBuilder before attaching,
        so the base Agent._attach_system_tools() can pass raw functions generically.
        :param tool: Raw Python callable or already-wrapped OpenAI function_tool.
        """
        # Delegate to the tool builder to handle binding
        self._append_tools(self._agent, OpenAIToolBuilder.bind([tool]))

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []
        for tool in self.agent.tools:
            skills.append(AgentSkill(id=tool.name, name=tool.name, description=tool.description, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.agent.instructions, skills=skills)


class OpenAIModule(Module):
    """
    OpenAIModule class provides a module for OpenAI Agents SDK based agents.
    """

    def __init__(
        self,
        agents: list[Agent],
        runner: OpenAIRunner = None,
        realtime_runner_cls: Type[BaseRealtimeRunner] = None,
    ):
        """
        Initializes an OpenAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        :param realtime_runner_cls: Optional realtime runner class for WebSocket connections.
        """
        super().__init__()
        self.realtime_runner_cls = realtime_runner_cls or OpenAIRealtimeAdapter
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().openai()
        else:
            self.runner = OpenAIRunner()
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps the provided agent in an OpenAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: OpenAIAgent instance.
        """
        rt_cls = self.realtime_runner_cls if AKConfig.get().execution.mode == ExecutionMode.REALTIME else None
        return OpenAIAgent(agent.name, self.runner, agent, realtime_runner_cls=rt_cls)

    def load(self, agents: list[Agent]) -> OpenAIModule:
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: OpenAIModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: Agent, hooks: list[PreHook]) -> "OpenAIModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: OpenAIModule instance.
        """
        super().get_agent(agent.name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: Agent, hooks: list[PostHook]) -> "OpenAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: OpenAIModule instance.
        """
        super().get_agent(agent.name).post_hooks.extend(hooks)
        return self


class OpenAIToolBuilder(ToolBuilder):
    """
    Tool builder for OpenAI Agents SDK.

    Wraps generic tool functions into OpenAI-compatible tool definitions
    using the ``function_tool`` helper from the OpenAI Agents SDK.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to OpenAI Agents SDK tool definitions.

        :param funcs: List of generic tool functions to bind.
        :return: List of OpenAI-compatible tool definitions.
        :raises TypeError: If any item in funcs is not callable.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(function_tool(func))
        return tools
