from __future__ import annotations

import array
import asyncio
import base64
import functools
import inspect
import json
import logging
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any, Callable, List
from uuid import uuid4

from google.adk.agents import BaseAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, State
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import ValidationError

from agentkernel.core.model import (
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

from ...core import Agent as AKBaseAgent
from ...core import Module, PostHook, PreHook
from ...core import RealtimeRunner as BaseRealtimeRunner
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder
from ...core import ToolContext as AKToolContext
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
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "adk"

_log = logging.getLogger("ak.adk")


class GoogleADKSession:
    """
    Manages Google ADK user sessions and underlying session service.
    """

    def __init__(self):
        """
        Initialize the session store and logging for Google ADK sessions.
        """
        self._session_service = InMemorySessionService()
        self._log = logging.getLogger("ak.adk.session")
        self._session = None

    @property
    def session_service(self) -> BaseSessionService:
        """
        Return the in-memory session service instance.
        """
        return self._session_service

    async def create_session(self, app_name: str, user_id: str, session_id: str) -> Any:
        if self._session is None:
            self._session = await self._session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
        return self._session

    async def update_session_state(self, invocation_id: str, author: str, state: dict) -> None:
        if self._session:
            event = Event(
                invocation_id=invocation_id,
                author=author,
                actions=EventActions(state_delta=state),
                timestamp=time.time(),
            )
            await self._session_service.append_event(self._session, event)

    async def get_state(self) -> dict:
        """
        Returns the caller-visible ADK session state, stripping the AK-internal ``ak_tool_context`` id and the
        ``app:`` / ``user:`` / ``temp:`` prefixed keys that are not session-scoped.
        :return: The accumulated session state, or an empty dict when no session exists.
        """
        if self._session is None:
            return {}
        refreshed = await self._session_service.get_session(
            app_name=self._session.app_name, user_id=self._session.user_id, session_id=self._session.id
        )
        state = dict(getattr(refreshed, "state", {}) or {})
        state.pop("ak_tool_context", None)
        return {k: v for k, v in state.items() if not k.startswith((State.APP_PREFIX, State.USER_PREFIX, State.TEMP_PREFIX))}


class GoogleADKRunner(BaseRunner):
    def __init__(self):
        """
        Initializes a GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.runner")

    @staticmethod
    def _session(session: Session) -> GoogleADKSession | None:
        """
        Returns the Google ADK session associated with the provided session.
        :param session: The session to retrieve the Google ADK session for.
        :return: GoogleADKSession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, GoogleADKSession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[types.Part]]:
        """
        Process requests and extract prompt text and ADK parts.
        :param requests: The requests to process.
        :return: Tuple of (prompt, parts).
        """
        prompt = ""
        parts = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                text = req.prompt
                prompt = prompt + "\n" + text if prompt else text
                parts.append(types.Part(text=text))

            if isinstance(req, (AgentRequestImage, AgentRequestFile)):
                base64_data = ""
                if isinstance(req, AgentRequestImage):
                    if not req.image_data:
                        raise ValueError("no image input provided")
                    base64_data = req.image_data

                elif isinstance(req, AgentRequestFile):
                    if not req.file_data:
                        raise ValueError("no file input provided")
                    base64_data = req.file_data

                if base64_data.startswith(("http://", "https://", "s3://")):
                    parts.append(types.Part(file_data=types.FileData(file_uri=base64_data)))
                    continue

                if base64_data.startswith("data:"):
                    mime_type = base64_data.split(";")[0][5:]
                else:
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for image input")
                    mime_type = req.mime_type

                raw_data = base64.b64decode(base64_data.split(",")[-1]) if base64_data.startswith("data:") else base64.b64decode(base64_data)
                parts.append(types.Part(inline_data=types.Blob(mime_type=mime_type, data=raw_data)))

            if isinstance(req, AgentRequestVoice):
                if not req.audio_data:
                    raise ValueError("no audio input provided")

                audio_data = req.audio_data
                if audio_data.startswith(("http://", "https://", "s3://")):
                    parts.append(types.Part(file_data=types.FileData(file_uri=audio_data)))
                    continue

                if audio_data.startswith("data:"):
                    mime_type = audio_data.split(";")[0][5:]
                else:
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for voice input, either in the base64 or explicitly")
                    mime_type = req.mime_type

                raw_data = base64.b64decode(audio_data.split(",")[-1]) if audio_data.startswith("data:") else base64.b64decode(audio_data)
                parts.append(types.Part(inline_data=types.Blob(mime_type=mime_type, data=raw_data)))

        return prompt, parts

    async def _setup_session_context(
        self, agent: Any, session: Session, requests: list[AgentRequest], injected: dict | None = None
    ) -> tuple[str, Runner, AKToolContext, GoogleADKSession]:
        """
        Setup ADK session and tool context.
        :param agent: The ADK agent.
        :param session: The AgentKernel session.
        :param requests: The requests.
        :param injected: The per-run framework context to seed into the ADK session state, or None.
        :return: Tuple of (user_id, runner, tool_context, adk_session). The caller is responsible for
                 entering/exiting the returned tool_context around the runner's actual execution, since
                 tools invoked by the agent look up this context by id from the cache while the agent is
                 running. The returned adk_session lets the caller read state back without re-fetching.
        """
        app_name = "AgentKernel"
        user_id = "AgentKernel"
        adk_session = self._session(session)

        ctx: AKToolContext = AKToolContext(Runtime.current(), agent, session, requests)
        await adk_session.create_session(app_name=app_name, user_id=user_id, session_id=session.id)
        # Assigned last so a caller key of the same name cannot replace the id tools resolve their context by.
        state = dict(injected or {})
        state["ak_tool_context"] = ctx.id
        await adk_session.update_session_state(ctx.id, agent.name, state)

        runner = Runner(agent=agent.agent, app_name=app_name, session_service=adk_session.session_service)
        return user_id, runner, ctx, adk_session

    @staticmethod
    async def get_response(runner: Runner, user_id: str, session_id: str, parts: list[types.Part]) -> str:
        """
        Send a message to the agent and return the final response text asynchronously.
        :param runner: The Google ADK Runner to use for the agent.
        :param user_id: The user ID to use for the agent.
        :param session_id: The session ID to use for the agent.
        :param parts: The message parts to send to the agent.
        :return: The final response text from the agent.
        """
        new_message = types.Content(role="user", parts=parts)
        response_text = ""

        if hasattr(runner, "run_async"):
            # Drain the stream instead of breaking early: stopping early cancels ADK's still-running root agent
            # task, and with sub-agents the last final response is the one to return.
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=new_message):
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
        else:
            for event in runner.run(user_id=user_id, session_id=session_id, new_message=new_message):
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
                    break
        return response_text

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the ADK agent with provided multi modal inputs.
        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        prompt = ""
        try:
            prompt, parts = self._process_requests(requests)

            if not parts:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            incoming = self._load_framework_context(session)
            user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming)
            with ctx:
                reply = await self.get_response(runner=runner, session_id=session.id, parts=parts, user_id=user_id)

            # Write back the full ADK state, so keys a tool added during the run also round-trip. Done after
            # the run, so a framework error leaves the stored context intact.
            if incoming is not None:
                produced = await adk_session.get_state()
                self._store_framework_context(session, incoming, produced)

            output_schema = getattr(agent.agent, "output_schema", None)
            if output_schema is not None:
                try:
                    parsed = output_schema.model_validate_json(reply)
                    return AgentReplyAny(content=parsed.model_dump(mode="json"), prompt=prompt)
                except ValidationError:
                    self._log.warning(f"Agent '{agent.name}' has output_schema set but reply is not valid JSON for it; returning text")
            return AgentReplyText(response=reply, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the Google ADK agent response as Agent Kernel stream events.

        ADK has no message-start signal or message id — only `partial=True` text fragments, then a
        `partial=False` aggregated event — so ids are generated here and boundaries are derived from
        partials. Non-partial text is not re-emitted unless no partials arrived. Reasoning
        (`Part.thought`) uses a separate id; tool calls use `FunctionCall.id` and are emitted after
        message boundaries. Open ids are locals — the runner is shared across sessions.

        :param agent: The ADK agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        prompt, parts = self._process_requests(requests)

        if not parts:
            return

        incoming = self._load_framework_context(session)
        user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming)
        new_message = types.Content(role="user", parts=parts)
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        if hasattr(runner, "run_async"):
            with ctx:
                message_id: str | None = None  # open message id; local, never on self
                reasoning_id: str | None = None
                reasoning_streamed = False
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session.id,
                    new_message=new_message,
                    run_config=run_config,
                ):
                    chunk, thinking = self._event_text(event)

                    if getattr(event, "partial", False) and thinking:
                        reasoning_streamed = True
                        if reasoning_id is None:
                            reasoning_id = uuid4().hex
                            yield ReasoningStart(message_id=reasoning_id)
                        yield ReasoningDelta(message_id=reasoning_id, content=thinking)
                    elif thinking and not reasoning_streamed:
                        whole_reasoning = uuid4().hex
                        yield ReasoningStart(message_id=whole_reasoning)
                        yield ReasoningDelta(message_id=whole_reasoning, content=thinking)
                        yield ReasoningEnd(message_id=whole_reasoning)

                    if chunk and reasoning_id is not None:
                        yield ReasoningEnd(message_id=reasoning_id)
                        reasoning_id = None

                    if getattr(event, "partial", False):
                        if chunk:
                            if message_id is None:
                                message_id = uuid4().hex
                                yield MessageStart(message_id=message_id)
                            yield TextDelta(message_id=message_id, content=chunk)
                    elif message_id is not None:
                        yield MessageEnd(message_id=message_id)
                        message_id = None
                    elif chunk:
                        whole = uuid4().hex
                        yield MessageStart(message_id=whole)
                        yield TextDelta(message_id=whole, content=chunk)
                        yield MessageEnd(message_id=whole)

                    tool_events = self._tool_events(event)
                    if tool_events and reasoning_id is not None:
                        yield ReasoningEnd(message_id=reasoning_id)
                        reasoning_id = None
                    for tool_event in tool_events:
                        yield tool_event

                if reasoning_id is not None:
                    yield ReasoningEnd(message_id=reasoning_id)
                if message_id is not None:
                    yield MessageEnd(message_id=message_id)

                # After a normal drain only — disconnect/error leaves stored context intact.
                if incoming is not None:
                    try:
                        produced = await adk_session.get_state()
                        self._store_framework_context(session, incoming, produced)
                    except Exception as e:
                        self._log_framework_context_stream_failure(session, e)

    @staticmethod
    def _event_text(event: Event) -> tuple[str, str]:
        """
        Split one ADK event's text into answer and reasoning (`Part.thought`).

        :param event: One event from `Runner.run_async`.
        :return: `(answer, reasoning)`, either or both empty.
        """
        if not event.content or not event.content.parts:
            return "", ""
        answer: list[str] = []
        reasoning: list[str] = []
        for part in event.content.parts:
            text = getattr(part, "text", "") or ""
            if not text:
                continue
            (reasoning if getattr(part, "thought", False) else answer).append(text)
        return "".join(answer), "".join(reasoning)

    def _tool_events(self, event: Event) -> list[StreamEvent]:
        """
        Translate an ADK event's function calls and responses into AK tool events.

        Arguments arrive complete (no per-token stream). Entries without an `id` are skipped —
        a generated id would not match the response.

        :param event: One event from `Runner.run_async`.
        :return: The AK events this event's tool activity produces, or an empty list.
        """
        events: list[StreamEvent] = []

        for call in event.get_function_calls():
            call_id = getattr(call, "id", None)
            if not call_id:
                self._log.debug(f"ADK function call '{getattr(call, 'name', '?')}' carries no id; not emitted")
                continue
            events.append(ToolCallStart(tool_call_id=call_id, name=getattr(call, "name", None) or ""))
            arguments = self._as_json(getattr(call, "args", None), "arguments")
            if arguments:
                events.append(ToolCallArgs(tool_call_id=call_id, delta=arguments))
            events.append(ToolCallEnd(tool_call_id=call_id))

        for response in event.get_function_responses():
            call_id = getattr(response, "id", None)
            if not call_id:
                self._log.debug(f"ADK function response '{getattr(response, 'name', '?')}' carries no id; not emitted")
                continue
            events.append(ToolCallResult(tool_call_id=call_id, content=self._as_json(getattr(response, "response", None), "result")))

        return events

    def _as_json(self, value: Any, what: str) -> str:
        """
        Serialise an ADK tool payload dict to JSON.

        On encode failure returns `""` so a mid-stream exception does not fail the run.

        :param value: The `args` or `response` dict, or None.
        :param what: What is being serialised, for the log line.
        :return: JSON text, or `""` if missing/unencodable.
        """
        if value is None:
            return ""
        try:
            return json.dumps(value, default=str)
        except Exception as e:
            self._log.warning(f"ADK tool {what} could not be serialised; it is emitted empty: {e!r}")
            return ""


class GoogleADKAgent(AKBaseAgent):
    """
    GoogleADKAgent class provides an agent wrapping for Google ADK Agent SDK based agents.
    """

    def __init__(self, name: str, runner: GoogleADKRunner, agent: BaseAgent, realtime_runner_cls: type[BaseRealtimeRunner] | None = None):
        """
        Initializes a GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The Google ADK agent instance.
        :param realtime_runner_cls: Optional realtime adapter class for this agent.
        """
        super().__init__(name, runner, realtime_runner_cls=realtime_runner_cls)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> BaseAgent:
        """
        Returns the GoogleADK agent instance.
        """
        return self._agent

    def get_description(self):
        """
        Returns the description of the agent.
        """
        return self.agent.description

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the ADK agent's description.
        Called by the base Agent._setup_system_prompt() at init when multimodal is enabled.
        """
        if hasattr(self._agent, "description") and self._agent.description and prompt not in self._agent.description:
            self._agent.description += "\n" + prompt

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable and wraps it with GoogleADKToolBuilder before attaching,
        so the base Agent._attach_system_tools() can pass raw functions generically.
        :param tool: Raw Python callable or already-wrapped ADK FunctionTool.
        """
        # Delegate to the tool builder to handle binding
        self._append_tools(self._agent, GoogleADKToolBuilder.bind([tool]))

    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        # TODO Add A2A card support
        pass


class GoogleADKModule(Module):
    """
    GoogleADKModule class provides a module for Google ADK-based agents.
    """

    def __init__(self, agents: list[BaseAgent], runner: GoogleADKRunner = None, realtime_runner_cls: type[BaseRealtimeRunner] | None = None):
        """
        Initializes a Google ADK Module instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        :param realtime_runner_cls: Optional realtime runner class for WebSocket connections.
        """
        super().__init__()
        self.realtime_runner_cls = realtime_runner_cls or GoogleADKRealtimeRunner
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().adk()
        else:
            self.runner = GoogleADKRunner()
        self.load(agents)

    def _wrap(self, agent: BaseAgent, agents: List[BaseAgent]) -> AKBaseAgent:
        """
        Wraps the provided agent in a GoogleADKAgent instance.
        :param agent: The agent to wrap.
        :param agents: List of agents in the module.
        :return: GoogleADKAgent instance.
        """
        rt_cls = self.realtime_runner_cls if AKConfig.get().execution.mode == ExecutionMode.REALTIME else None
        return GoogleADKAgent(agent.name, self.runner, agent, realtime_runner_cls=rt_cls)

    def load(self, agents: list[BaseAgent]) -> "GoogleADKModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: GoogleADKModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: BaseAgent, hooks: list[PreHook]) -> "GoogleADKModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: BaseAgent, hooks: list[PostHook]) -> "GoogleADKModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: GoogleADKModule instance.
        """
        super().get_agent(agent.name).post_hooks.extend(hooks)
        return self


class GoogleADKToolBuilder(ToolBuilder):
    """
    Tool builder for Google ADK.

    Wraps generic tool functions into ADK-compatible FunctionTool instances.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to ADK FunctionTool instances.

        :param funcs: List of generic tool functions to bind.
        :return: List of ADK-compatible FunctionTool instances.
        """
        tools = []
        for func in funcs:
            tools.append(FunctionTool(cls._wrap(func)))
        return tools

    @classmethod
    def _wrap(cls, func: Callable) -> Callable:
        """
        Wraps a generic tool function to ensure it can be used with the Google ADK.

        :param func: The generic tool function to wrap.
        :return: A wrapped version of the function that is compatible with the Google ADK.
        :raises TypeError: If the function is not callable.
        """
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")

        signature = inspect.signature(func)
        parameters = list(signature.parameters.values())

        # ADK-aware tools declare `tool_context` themselves and expect the live ADK
        # context to reach them, so it has to be forwarded. Generic tools do not, and
        # for those the parameter is consumed here purely to activate the AK context.
        declares_tool_context = "tool_context" in signature.parameters
        tool_context_position = list(signature.parameters).index("tool_context") if declares_tool_context else -1

        def forwarded_kwargs(args: tuple[Any, ...], kwargs: dict[str, Any], tool_context: ToolContext | None) -> dict[str, Any]:
            """
            Builds the keyword arguments for the wrapped function.

            :param args: Positional arguments the wrapper was called with.
            :param kwargs: Keyword arguments the wrapper was called with.
            :param tool_context: The ADK tool context supplied to the wrapper.
            :return: The keyword arguments to pass to the wrapped function.
            """
            if not declares_tool_context or "tool_context" in kwargs:
                return kwargs
            # The caller already bound tool_context positionally; do not bind it twice.
            if len(args) > tool_context_position:
                return kwargs
            return {**kwargs, "tool_context": tool_context}

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, tool_context: ToolContext | None = None, **kwargs: Any) -> Any:
                tctx: AKToolContext | None = None
                try:
                    if tool_context and tool_context.state and tool_context.state.get("ak_tool_context"):
                        tctx = AKToolContext.fetch(tool_context.state["ak_tool_context"]).set()
                    return await func(*args, **forwarded_kwargs(args, kwargs, tool_context))
                finally:
                    if tctx:
                        tctx.reset()

        else:

            @functools.wraps(func)
            def wrapper(*args: Any, tool_context: ToolContext | None = None, **kwargs: Any) -> Any:
                tctx: AKToolContext | None = None
                try:
                    if tool_context and tool_context.state and tool_context.state.get("ak_tool_context"):
                        tctx = AKToolContext.fetch(tool_context.state["ak_tool_context"]).set()
                    return func(*args, **forwarded_kwargs(args, kwargs, tool_context))
                finally:
                    if tctx:
                        tctx.reset()

        # Only add a tool_context parameter if the original function does not already
        # declare one, and insert it before any **kwargs (VAR_KEYWORD) parameter to
        # maintain a valid inspect.Signature ordering.
        if not declares_tool_context:
            tool_context_param = inspect.Parameter(
                "tool_context",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
            )

            insert_index = None
            for idx, param in enumerate(parameters):
                if param.kind is inspect.Parameter.VAR_KEYWORD:
                    insert_index = idx
                    break

            if insert_index is not None:
                parameters.insert(insert_index, tool_context_param)
            else:
                parameters.append(tool_context_param)

        wrapper.__signature__ = signature.replace(parameters=parameters)
        return wrapper


# Gemini Live takes 16 kHz PCM16 input but returns 24 kHz output, while the LiveKit edge speaks a
# single 24 kHz rate in both directions. Inbound audio is resampled here so the shared edge needs
# no per-provider rate plumbing.
GEMINI_INPUT_SAMPLE_RATE = 16000
EDGE_SAMPLE_RATE = 24000


class GoogleADKRealtimeRunner(BaseRealtimeRunner):
    """Drives a persistent Gemini Live (BidiGenerateContent) socket behind the realtime pool.

    Mirrors ``OpenAIRealtimeAdapter``: the pool calls :meth:`connect` once per session and then
    pushes audio/text through :meth:`append_audio` / :meth:`send_text`. Model events are reported
    back through the callback the pool supplied, so the pool keeps owning queue emission and this
    class never imports pipeline types.
    """

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.realtime")
        self._callback: Callable | None = None
        self._connection = None
        self._cm = None
        self._listen_task: asyncio.Task | None = None
        # Gemini reports output transcription separately from the audio turn, so a turn's
        # transcript is accumulated here and published once on turn_complete.
        self._transcript: list[str] = []
        # call_id -> function name, needed to build the FunctionResponse Gemini expects.
        self._tool_names: dict[str, str] = {}

    @staticmethod
    def _realtime_model(agent: Any) -> str:
        """The Gemini Live model named by the agent definition.

        Deliberately no adapter-level default: the model is the agent's choice, and a silent
        fallback would run a different model than the one the caller declared.
        """
        model = getattr(getattr(agent, "agent", None), "model", None)
        name = model if isinstance(model, str) else getattr(model, "model", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"Agent '{getattr(agent, 'name', '?')}' must define a Gemini Live model to run in REALTIME mode")
        return name

    def _connect_config(self, agent: Any) -> types.LiveConnectConfig:
        """Build the Live session config from the ADK agent's instruction and tools."""
        sdk_agent = getattr(agent, "agent", None)
        instructions = getattr(sdk_agent, "instruction", None) or getattr(sdk_agent, "description", None)

        declarations = []
        for tool in getattr(sdk_agent, "tools", None) or []:
            try:
                declaration = tool._get_declaration()
            except Exception as e:
                self._log.warning(f"Could not build a Live declaration for tool {getattr(tool, 'name', '?')}: {e!r}")
                declaration = None
            if declaration is not None:
                declarations.append(declaration)

        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=instructions)]) if instructions else None,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def connect(self, session: Session, agent: AKBaseAgent, callback: Callable) -> None:
        from google import genai

        self._callback = callback
        client = genai.Client()
        model = self._realtime_model(agent)
        self._log.info(f"Connecting to Gemini Live (model={model})")

        self._cm = client.aio.live.connect(model=model, config=self._connect_config(agent))
        self._connection = await self._cm.__aenter__()
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            # receive() ends each turn at turn_complete, so the persistent socket is drained one
            # turn at a time; the outer loop re-enters it for the next turn.
            while True:
                async for message in self._connection.receive():
                    await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log.error(f"Gemini Live socket error: {e}")

    async def _handle_message(self, message: types.LiveServerMessage) -> None:
        server_content = getattr(message, "server_content", None)
        if server_content is not None:
            if getattr(server_content, "interrupted", False):
                await self._callback("interrupt", {})
            transcription = getattr(server_content, "output_transcription", None)
            if transcription is not None and transcription.text:
                self._transcript.append(transcription.text)
            model_turn = getattr(server_content, "model_turn", None)
            if model_turn and model_turn.parts:
                for part in model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and inline.data:
                        audio_b64 = base64.b64encode(inline.data).decode("utf-8")
                        await self._callback("audio_delta", {"delta": audio_b64})
            if getattr(server_content, "turn_complete", False):
                transcript = "".join(self._transcript).strip()
                self._transcript.clear()
                await self._callback("done", {"status": "completed", "transcript": transcript})

        tool_call = getattr(message, "tool_call", None)
        if tool_call and tool_call.function_calls:
            for call in tool_call.function_calls:
                self._tool_names[call.id] = call.name
                await self._callback("tool_call", {"call_id": call.id, "name": call.name, "arguments": json.dumps(call.args or {})})

    async def append_audio(self, base64_audio: str) -> None:
        if self._connection:
            pcm16 = self._resample_pcm16(base64.b64decode(base64_audio), EDGE_SAMPLE_RATE, GEMINI_INPUT_SAMPLE_RATE)
            await self._connection.send_realtime_input(audio=types.Blob(data=pcm16, mime_type=f"audio/pcm;rate={GEMINI_INPUT_SAMPLE_RATE}"))

    async def send_text(self, text: str) -> None:
        if self._connection:
            await self._connection.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)

    async def send_tool_result(self, call_id: str, result: str) -> None:
        if self._connection:
            name = self._tool_names.pop(call_id, call_id)
            await self._connection.send_tool_response(function_responses=types.FunctionResponse(id=call_id, name=name, response={"output": result}))

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._connection and self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._connection = None
            self._cm = None

    @staticmethod
    def _resample_pcm16(data: bytes, source_rate: int, target_rate: int) -> bytes:
        """Linearly resample little-endian mono PCM16 audio from ``source_rate`` to ``target_rate``."""
        if not data or source_rate == target_rate:
            return data
        samples = array.array("h")
        samples.frombytes(data[: len(data) - (len(data) % 2)])
        if not samples:
            return b""
        if sys.byteorder == "big":
            samples.byteswap()

        ratio = source_rate / target_rate
        out_count = int(len(samples) / ratio)
        out = array.array("h", bytes(out_count * 2))
        for i in range(out_count):
            position = i * ratio
            left = int(position)
            right = min(left + 1, len(samples) - 1)
            fraction = position - left
            out[i] = int(samples[left] + (samples[right] - samples[left]) * fraction)

        if sys.byteorder == "big":
            out.byteswap()
        return out.tobytes()
