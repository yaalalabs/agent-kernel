from __future__ import annotations

import base64
import copy
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, ClassVar, List, Mapping
from uuid import uuid4

from agent_framework import Agent, AgentSession, Content, Message
from agent_framework import tool as maf_tool

from ...core import Agent as BaseAgent
from ...core import Module, Runner, Runtime, Session, ToolBuilder, ToolContext
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
)
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "maf"

_log = logging.getLogger("ak.maf.runner")


class MAFSession:
    """
    Stores the MAF-specific session data: the serialized native `AgentSession` (`AgentSession.to_dict()`),
    kept as a plain dict so the AK session store can persist it.
    """

    def __init__(self) -> None:
        self._state: dict[str, Any] | None = None

    def get_state(self) -> dict[str, Any] | None:
        """
        :return: The serialized native session, or None before the first successful run.
        """
        return self._state

    def set_state(self, state: dict[str, Any]) -> None:
        """
        :param state: The serialized native session to persist.
        """
        self._state = state


class MAFRunner(Runner):
    """
    MAFRunner class provides a runner for Microsoft Agent Framework-based agents.
    """

    def __init__(self) -> None:
        # Must match the session key: Session.get_framework_session() resolves it via the runner name.
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> MAFSession | None:
        """
        Retrieves the MAFSession from the AgentKernel session, initializing it if not present.
        :param session: The AK session, or None.
        :return: The MAF session data stored under the framework key, or None without a session.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, MAFSession())

    @staticmethod
    def _attachment_content(data: str, mime_type: str | None, kind: str) -> Content:
        """
        Converts one image or file attachment into a MAF Content item.
        :param data: A URL, a data URI, or raw base64 data.
        :param mime_type: The MIME type declared on the request, if any.
        :param kind: "image" or "file", used in error messages.
        :return: A URI Content item for URLs, otherwise a data Content item.
        """
        if data.startswith(("http://", "https://", "s3://")):
            return Content.from_uri(uri=data, media_type=mime_type)
        if data.startswith("data:"):
            header, _, payload = data.partition(",")
            return Content.from_data(data=base64.b64decode(payload), media_type=header[5:].split(";")[0])
        if not mime_type:
            raise ValueError(f"MIME type is required for raw {kind} data but was not provided.")
        return Content.from_data(data=base64.b64decode(data), media_type=mime_type)

    @classmethod
    def _process_requests(cls, requests: list[AgentRequest]) -> tuple[str, list[str | Content]]:
        """
        Process requests and extract prompt text and MAF Content items.
        :param requests: The requests to process.
        :return: Tuple of (prompt, contents of the single user message sent to MAF).
        """
        prompt_parts: list[str] = []
        inputs: list[str | Content] = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                prompt_parts.append(req.prompt)
                inputs.append(req.prompt)

            elif isinstance(req, AgentRequestImage):
                if not req.image_data:
                    raise ValueError("no image input provided")
                prompt_parts.append(f"[Image attached: {req.name or 'image'}]")
                inputs.append(cls._attachment_content(req.image_data, req.mime_type, "image"))

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")
                prompt_parts.append(f"[File attached: {req.name or 'file'}]")
                inputs.append(cls._attachment_content(req.file_data, req.mime_type, "file"))

        return "\n".join(prompt_parts), inputs

    def _prepare_session(self, session: Session | None, options: Mapping[str, Any]) -> tuple[dict[str, Any], AgentSession | None, dict | None]:
        """
        Restores the native MAF session and injects the framework context for one run.
        :param session: The AK session, or None for a stateless run.
        :param options: The run options resolved for this run.
        :return: Tuple of (native run kwargs, native session or None, framework context loaded this turn).
        """
        if session is None:
            return self._native_kwargs(options), None, None

        state = self._session(session).get_state()
        native_session = AgentSession.from_dict(state) if state else AgentSession(session_id=session.id)

        # Tools reach the framework context as `FunctionInvocationContext.session.state["ak_context"]`.
        incoming = self._load_framework_context(session)
        native_session.state.pop("ak_context", None)
        if incoming is not None:
            # Deep copy so in-place tool mutations do not alter `incoming`.
            native_session.state["ak_context"] = copy.deepcopy(incoming)

        return self._native_kwargs(options, session=native_session), native_session, incoming

    def _finalize_session(self, session: Session | None, native_session: AgentSession | None, incoming: dict | None) -> None:
        """
        Writes the framework context and the native MAF session back to the AK session after a successful run.
        The context is popped from the native state first: AK persists it as the framework context, so keeping
        it in the MAF snapshot would store it twice.
        :param session: The AK session, or None for a stateless run.
        :param native_session: The native session used for the run, or None.
        :param incoming: The framework context loaded this turn, or None.
        """
        if session is None or native_session is None:
            return
        produced = native_session.state.pop("ak_context", None)
        self._store_framework_context(session, incoming, produced)
        self._session(session).set_state(native_session.to_dict())

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent with the provided multi modal inputs.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, inputs = self._process_requests(requests)

            if not inputs:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options)

            # One user message, so text and attachments reach the model as a single turn.
            result = await agent.agent.run(Message("user", inputs), **kwargs)

            # Only write back after a successful run.
            self._finalize_session(session, native_session, incoming)

            structured = AgentReplyAny.from_output(getattr(result, "value", None), prompt)
            if structured is not None:
                return structured

            output = getattr(result, "text", None)
            return AgentReplyText(response=str(result) if output is None else output, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the MAF agent response as Agent Kernel stream events.

        Text and reasoning streams are keyed by the update's native `message_id` (or a generated id when MAF
        supplies none); tool events are correlated by MAF's own `call_id`. `streams` / `open_calls` / `call_ids`
        are locals — the runner is shared across sessions.

        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            _, inputs = self._process_requests(requests)

            if not inputs:
                return

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options)

            stream_result = await agent.agent.run(Message("user", inputs), stream=True, **kwargs)

            fallback_id = uuid4().hex
            streams: dict[str, str] = {}  # native content type -> id of the open text/reasoning stream
            open_calls: dict[str, None] = {}  # insertion-ordered set of call ids awaiting a result
            call_ids: dict[Any, str] = {}  # tool_call_index -> call id; the None key holds the latest call

            async for update in stream_result:
                for event in self._map_update(update, fallback_id, streams, open_calls, call_ids):
                    yield event
            for event in self._close_streams(streams, open_calls):
                yield event

            # After a normal drain only — disconnect/error leaves the stored session and context intact.
            try:
                self._finalize_session(session, native_session, incoming)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    def _map_update(
        self, update: Any, fallback_id: str, streams: dict[str, str], open_calls: dict[str, None], call_ids: dict[Any, str]
    ) -> list[StreamEvent]:
        """
        Translates one native `AgentResponseUpdate` into AK events. Unmapped content types produce nothing.
        :param update: The native update.
        :param fallback_id: The stream id used when MAF supplies no message id.
        :param streams: Native content type -> id of the open text/reasoning stream. Mutated in place.
        :param open_calls: Call ids awaiting a result. Mutated in place.
        :param call_ids: `tool_call_index` -> call id seen so far. Mutated in place.
        :return: The AK events this update produces, in order.
        """
        native_id = getattr(update, "message_id", None)
        events: list[StreamEvent] = []
        for item in getattr(update, "contents", None) or []:
            item_type = getattr(item, "type", "")
            if item_type in ("text", "text_reasoning"):
                events.extend(self._delta_events(item_type, item, native_id, fallback_id, streams))
            elif item_type == "function_call":
                events.extend(self._function_call_events(item, open_calls, call_ids))
            elif item_type == "function_result":
                events.extend(self._function_result_events(item, open_calls))
        return events

    def _delta_events(self, item_type: str, item: Content, native_id: str | None, fallback_id: str, streams: dict[str, str]) -> list[StreamEvent]:
        """
        Maps a text or reasoning chunk, opening its stream (and closing the previous one) when the id changes.
        A missing native id continues the open stream instead of splitting it.
        :param item_type: "text" or "text_reasoning".
        :param item: The Content chunk.
        :param native_id: The update's native message id, or None.
        :param fallback_id: The stream id used when MAF supplies no message id.
        :param streams: Native content type -> id of the open stream. Mutated in place.
        :return: The boundary events, if any, followed by the delta.
        """
        text = getattr(item, "text", None)
        if not text:
            return []
        is_text = item_type == "text"
        current = streams.get(item_type)
        stream_id = native_id or current or fallback_id
        events: list[StreamEvent] = []
        if stream_id != current:
            if current is not None:
                events.append(MessageEnd(message_id=current) if is_text else ReasoningEnd(message_id=current))
            events.append(MessageStart(message_id=stream_id) if is_text else ReasoningStart(message_id=stream_id))
            streams[item_type] = stream_id
        events.append(TextDelta(message_id=stream_id, content=text) if is_text else ReasoningDelta(message_id=stream_id, content=text))
        return events

    def _function_call_events(self, item: Content, open_calls: dict[str, None], call_ids: dict[Any, str]) -> list[StreamEvent]:
        """
        Maps a function_call chunk: opens the call on its first chunk, then streams its arguments.
        :param item: The function_call Content chunk.
        :param open_calls: Call ids awaiting a result. Mutated in place.
        :param call_ids: `tool_call_index` -> call id seen so far. Mutated in place.
        :return: The tool-call events for this chunk.
        """
        call_id = self._tool_call_id(item, call_ids)
        if call_id is None:
            return []
        events: list[StreamEvent] = []
        if call_id not in open_calls:
            events.append(ToolCallStart(tool_call_id=call_id, name=getattr(item, "name", None) or ""))
            open_calls[call_id] = None
        args = getattr(item, "arguments", None)
        if args:
            events.append(ToolCallArgs(tool_call_id=call_id, delta=self._as_text(args)))
        return events

    def _function_result_events(self, item: Content, open_calls: dict[str, None]) -> list[StreamEvent]:
        """
        Maps a function_result: closes the call if it is still open, then emits its result.
        :param item: The function_result Content item.
        :param open_calls: Call ids awaiting a result. Mutated in place.
        :return: The tool-result events.
        """
        call_id = getattr(item, "call_id", None)
        if not call_id:
            return []
        events: list[StreamEvent] = []
        if call_id in open_calls:
            del open_calls[call_id]
            events.append(ToolCallEnd(tool_call_id=call_id))
        events.append(ToolCallResult(tool_call_id=call_id, content=self._as_text(getattr(item, "result", None))))
        return events

    @staticmethod
    def _tool_call_id(item: Content, call_ids: dict[Any, str]) -> str | None:
        """
        Returns the id of the tool call a streamed function_call chunk belongs to.
        Chat Completions-style clients send the id and name on a call's first chunk only; the argument chunks after
        it carry an empty id plus `tool_call_index`, the only key that ties parallel calls' chunks to their call.
        :param item: The function_call Content chunk.
        :param call_ids: `tool_call_index` -> call id seen so far; the None key holds the latest call. Mutated in place.
        :return: The call id, or None when the chunk cannot be tied to a call.
        """
        index = (getattr(item, "additional_properties", None) or {}).get("tool_call_index")
        call_id = getattr(item, "call_id", None)
        if call_id:
            call_ids[index] = call_id
            call_ids[None] = call_id
            return call_id
        return call_ids.get(index) or call_ids.get(None)

    @staticmethod
    def _close_streams(streams: dict[str, str], open_calls: dict[str, None]) -> list[StreamEvent]:
        """
        Closes every stream still open once the native stream is drained.
        :param streams: Native content type -> id of the open text/reasoning stream.
        :param open_calls: Call ids still awaiting a result.
        :return: The closing events: tool calls without a result, then reasoning, then text.
        """
        events: list[StreamEvent] = [ToolCallEnd(tool_call_id=call_id) for call_id in open_calls]
        if "text_reasoning" in streams:
            events.append(ReasoningEnd(message_id=streams["text_reasoning"]))
        if "text" in streams:
            events.append(MessageEnd(message_id=streams["text"]))
        return events

    @staticmethod
    def _as_text(value: Any) -> str:
        """
        :param value: A tool argument payload or result.
        :return: The value itself when it is a string, otherwise its JSON encoding.
        """
        return value if isinstance(value, str) else json.dumps(value, default=str)


class MAFAgent(BaseAgent):
    """
    MAFAgent class provides an agent wrapping for Microsoft Agent Framework-based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "messages": "built from the AgentRequest list by the runner",
        "stream": "managed by the runner based on the execution mode",
        "session": "managed by the runner based on the AK session",
    }

    def __init__(self, name: str, runner: MAFRunner, agent: Agent):
        """
        Initializes a MAFAgent instance.
        :param name: The name the agent is registered under.
        :param runner: The runner that executes the agent.
        :param agent: The native MAF agent.
        """
        super().__init__(name, runner)
        self._agent = agent
        if getattr(self._agent, "default_options", None) is None:
            self._agent.default_options = {}
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> Agent:
        """
        :return: The native MAF agent.
        """
        return self._agent

    def get_description(self) -> str:
        """
        :return: The native agent's description, falling back to its instructions.
        """
        return getattr(self.agent, "description", None) or self.agent.default_options.get("instructions", "") or ""

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends the given prompt text to the MAF agent's instructions, once.
        Called by the base Agent._setup_system_prompt() at init; the containment check keeps a native agent
        wrapped more than once from accumulating the same suffix.
        :param prompt: The instruction text to append.
        """
        if not prompt:
            return
        current = self.agent.default_options.get("instructions", "") or ""
        if prompt not in current:
            self.agent.default_options["instructions"] = f"{current}\n{prompt}" if current else prompt

    def attach_tool(self, tool: Any) -> None:
        """
        Wraps a raw callable with MAFToolBuilder and adds it to the agent's default tools.
        MAF rejects duplicate tool names at run time, so a tool whose name is already taken is skipped: silently
        when it wraps the same function (the native agent was wrapped before), with a warning otherwise.
        :param tool: Raw Python callable to attach.
        """
        tools = self.agent.default_options.setdefault("tools", [])
        for wrapped in MAFToolBuilder.bind([tool]):
            existing = next((t for t in tools if getattr(t, "name", None) == wrapped.name), None)
            if existing is None:
                tools.append(wrapped)
            elif getattr(existing, "func", None) is not tool:
                _log.warning(
                    "Agent '%s' already has a tool named '%s'; MAF rejects duplicate tool names, so Agent Kernel's "
                    "system tool was not attached. Rename or remove the application's tool to enable it.",
                    self.name,
                    wrapped.name,
                )

    def get_a2a_card(self) -> Any:
        """
        :return: The A2A AgentCard for the agent, with one skill per attached tool.
        """
        from a2a.types import AgentSkill

        skills = []
        tools = self.agent.default_options.get("tools", []) or []
        for t in tools:
            name = getattr(t, "name", "tool")
            desc = getattr(t, "description", "")
            skills.append(AgentSkill(id=name, name=name, description=desc, tags=[]))
        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class MAFModule(Module):
    """
    MAFModule class provides a module for Microsoft Agent Framework-based agents.
    """

    def __init__(self, agents: list[Agent], runner: MAFRunner | None = None):
        """
        Initializes a MAFModule instance.
        :param agents: List of MAF agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().maf()
        else:
            self.runner = MAFRunner()
        self.load(agents)

    def _wrap(self, agent: Agent, agents: List[Agent]) -> BaseAgent:
        """
        Wraps a native MAF agent in a MAFAgent.
        :param agent: The native MAF agent; it must have an explicit name.
        :param agents: All agents in the module.
        :return: The MAFAgent wrapper.
        """
        if getattr(agent, "name", None) is None:
            raise ValueError("MAF agents passed to MAFModule must have an explicit name= — AK registers agents by name immediately.")
        return MAFAgent(agent.name, self.runner, agent)

    def load(self, agents: list[Agent]) -> MAFModule:
        """
        Loads and registers the native MAF agents, replacing the current ones.
        :param agents: List of native MAF agents.
        :return: This module.
        """
        super().load(agents)
        return self


class MAFToolBuilder(ToolBuilder):
    """
    Tool builder for Microsoft Agent Framework.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind generic tool functions to MAF ``@tool`` definitions.
        :param funcs: List of generic tool functions to bind.
        :return: List of MAF tool definitions.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(maf_tool(func))
        return tools
