from __future__ import annotations

import base64
import copy
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, List
from uuid import uuid4

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import BinaryContent, DocumentUrl, FunctionToolset, ImageUrl, Tool
from pydantic_ai.messages import ModelMessagesTypeAdapter, UserContent
from pydantic_core import to_jsonable_python

from ...core import Agent as BaseAgent
from ...core import Module, PostHook, PreHook
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
)
from ...core.util.error_util import user_facing_error_message
from ...trace import Trace

FRAMEWORK = "pydanticai"

_log = logging.getLogger("ak.pydanticai.runner")


class PydanticAISession:
    """
    PydanticAISession stores the running message history for Pydantic AI-based agents.

    History is kept in jsonable form rather than as raw ``ModelMessage`` objects, so a
    pickled session survives Pydantic AI releases.
    """

    def __init__(self):
        """
        Initializes a PydanticAISession instance.
        """
        self._messages: list[dict] = []

    @property
    def messages(self) -> list[dict]:
        """
        Returns the stored message history in jsonable form.
        """
        return self._messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        """
        Sets the stored message history (jsonable form).
        :param value: The jsonable message history to store.
        """
        self._messages = value


class PydanticAIRunner(BaseRunner):
    """
    PydanticAIRunner class provides a runner for Pydantic AI-based agents.
    """

    def __init__(self):
        """
        Initializes a PydanticAIRunner instance.
        """
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> PydanticAISession | None:
        """
        Returns the Pydantic AI session associated with the provided session.
        :param session: The session to retrieve the Pydantic AI session for.
        :return: PydanticAISession instance.
        """
        if session is None:
            return None
        return session.get(FRAMEWORK) or session.set(FRAMEWORK, PydanticAISession())

    @staticmethod
    def _process_requests(requests: list[AgentRequest]) -> tuple[str, list[UserContent]]:
        """
        Process requests and extract prompt text and Pydantic AI multi-modal content.
        :param requests: The requests to process.
        :return: Tuple of (prompt, content).
        """
        prompt = ""
        content: list[UserContent] = []

        for req in requests:
            if isinstance(req, AgentRequestAny):
                continue

            if isinstance(req, AgentRequestText):
                text = req.prompt
                prompt = prompt + "\n" + text if prompt else text
                content.append(text)

            elif isinstance(req, AgentRequestImage):
                if not req.image_data:
                    raise ValueError("no image input provided")

                if req.image_data.startswith(("http://", "https://", "s3://")):
                    content.append(ImageUrl(url=req.image_data))
                else:
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
                    content.append(BinaryContent(data=base64.b64decode(req.image_data), media_type=req.mime_type))

            elif isinstance(req, AgentRequestFile):
                if not req.file_data:
                    raise ValueError("no file input provided")

                if req.file_data.startswith(("http://", "https://", "s3://")):
                    content.append(DocumentUrl(url=req.file_data))
                else:
                    if not req.mime_type:
                        raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                    content.append(BinaryContent(data=base64.b64decode(req.file_data), media_type=req.mime_type))

        return prompt, content

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the Pydantic AI agent with the provided multi modal inputs.
        :param agent: The Pydantic AI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution.
        """
        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)

            if not content:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

            # Deep copy so in-place tool mutations do not alter `incoming`.
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            result = await agent.agent.run(content, message_history=history, deps=produced)

            if fw_session is not None:
                fw_session.messages = to_jsonable_python(result.all_messages())

            self._store_framework_context(session, incoming, produced)

            structured = AgentReplyAny.from_output(result.output, prompt)
            if structured is not None:
                return structured

            reply_text = "" if result.output is None else str(result.output)
            return AgentReplyText(response=reply_text, prompt=prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the Pydantic AI agent response as Agent Kernel stream events.

        Uses `run_stream_events()` so text, thinking, and tool-call parts are all reachable.
        Part events drive the streams (`text` / `thinking` / `tool-call`); ids come from the
        part or `tool_call_id` (or a generated id for text/thinking). `open_parts` / `carried`
        are locals — the runner is shared across sessions. `function_tool_call` is ignored
        because the part events already cover the call.

        :param agent: The Pydantic AI agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        """
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)

            if not content:
                return

            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)

            open_parts: dict[int, tuple[str, str]] = {}  # live index -> (kind, id); local, never on self
            carried: dict[str, str] = {}  # kind -> id when a stream continues across a part boundary
            run_result: Any = None

            async with agent.agent.run_stream_events(content, message_history=history, deps=produced) as events:
                async for event in events:
                    kind = getattr(event, "event_kind", None)
                    if kind == "agent_run_result":
                        run_result = getattr(event, "result", None)
                        continue
                    for stream_event in self._map_event(kind, event, open_parts, carried):
                        yield stream_event

            for index in list(open_parts):
                for stream_event in self._close_part(index, open_parts, carried):
                    yield stream_event
            for part_kind, stream_id in list(carried.items()):
                del carried[part_kind]
                yield MessageEnd(message_id=stream_id) if part_kind == "text" else ReasoningEnd(message_id=stream_id)

            if fw_session is not None and run_result is not None:
                fw_session.messages = to_jsonable_python(run_result.all_messages())
            elif fw_session is not None:
                _log.warning("Pydantic AI stream drained without an agent_run_result event; conversation history was not persisted")

            # After a normal drain only — disconnect/error leaves stored context intact.
            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    def _map_event(self, kind: str | None, event: Any, open_parts: dict[int, tuple[str, str]], carried: dict[str, str]) -> list[StreamEvent]:
        """
        Translate one Pydantic AI run event into AK events.

        Both tool-result kinds map: a structured-output run's final answer is an ordinary tool call
        whose result arrives as `output_tool_result`, so dropping it would leave the call dangling.
        Unmapped kinds (including `function_tool_call`) produce nothing.

        :param kind: The event's `event_kind` discriminator.
        :param event: The run event.
        :param open_parts: Live index → `(kind, id)` map. Mutated in place.
        :param carried: Kind → id map of streams held open across a part boundary.
        :return: The AK events this run event produces, or an empty list.
        """
        if kind == "part_start":
            return self._open_part(event, open_parts, carried)
        if kind == "part_delta":
            return self._delta_part(event, open_parts)
        if kind == "part_end":
            return self._close_part(event.index, open_parts, carried, getattr(event, "next_part_kind", None))
        if kind in ("function_tool_result", "output_tool_result"):
            return self._tool_result(event)
        return []

    def _open_part(self, event: Any, open_parts: dict[int, tuple[str, str]], carried: dict[str, str]) -> list[StreamEvent]:
        """
        Open a part's stream, or continue one held open from the previous part.

        Adjacent parts of the same kind reuse the id (no new boundary). A second `part_start`
        on a live index replaces the previous part and closes it first.

        :param event: A `part_start` run event.
        :param open_parts: Live index → `(kind, id)` map. Mutated in place.
        :param carried: Kind → id map of streams held open across a part boundary.
        :return: The AK events that open (or continue) this part.
        """
        index = event.index
        part = getattr(event, "part", None)
        part_kind = getattr(part, "part_kind", None)

        events: list[StreamEvent] = []
        if index in open_parts:
            events.extend(self._close_part(index, open_parts, carried))

        if part_kind in ("text", "thinking"):
            continuing = getattr(event, "previous_part_kind", None) == part_kind and part_kind in carried
            message_id = carried.pop(part_kind) if continuing else (getattr(part, "id", None) or uuid4().hex)
            open_parts[index] = (part_kind, message_id)
            if not continuing:
                events.append(MessageStart(message_id=message_id) if part_kind == "text" else ReasoningStart(message_id=message_id))
            content = getattr(part, "content", None)
            if content:
                events.append(
                    TextDelta(message_id=message_id, content=content)
                    if part_kind == "text"
                    else ReasoningDelta(message_id=message_id, content=content)
                )
            return events

        if part_kind == "tool-call":
            tool_call_id = getattr(part, "tool_call_id", None)
            if not tool_call_id:
                _log.debug("Pydantic AI tool-call part carries no tool_call_id; not emitted")
                return events
            open_parts[index] = ("tool-call", tool_call_id)
            events.append(ToolCallStart(tool_call_id=tool_call_id, name=getattr(part, "tool_name", None) or ""))
            arguments = self._as_json(getattr(part, "args", None), "arguments")
            if arguments:
                events.append(ToolCallArgs(tool_call_id=tool_call_id, delta=arguments))
            return events

        return events

    def _delta_part(self, event: Any, open_parts: dict[int, tuple[str, str]]) -> list[StreamEvent]:
        """
        Forward one delta onto the stream its index opened.

        Deltas for an index that never opened are dropped.

        :param event: A `part_delta` run event.
        :param open_parts: Live index → `(kind, id)` map.
        :return: The AK delta events, or an empty list.
        """
        index = event.index
        opened = open_parts.get(index)
        if opened is None:
            _log.debug(f"Pydantic AI delta for part {index} that never opened; not emitted")
            return []

        part_kind, stream_id = opened
        delta = getattr(event, "delta", None)

        if part_kind == "text":
            content = getattr(delta, "content_delta", None)
            return [TextDelta(message_id=stream_id, content=content)] if content else []
        if part_kind == "thinking":
            content = getattr(delta, "content_delta", None)
            return [ReasoningDelta(message_id=stream_id, content=content)] if content else []

        arguments = self._as_json(getattr(delta, "args_delta", None), "arguments")
        return [ToolCallArgs(tool_call_id=stream_id, delta=arguments)] if arguments else []

    def _close_part(
        self, index: int, open_parts: dict[int, tuple[str, str]], carried: dict[str, str], next_part_kind: str | None = None
    ) -> list[StreamEvent]:
        """
        Close the stream an index opened, unless the next part continues it.

        :param index: The part index to close.
        :param open_parts: Live index → `(kind, id)` map. Mutated in place.
        :param carried: Kind → id map; a continued stream is parked here.
        :param next_part_kind: Kind of the following part, when known.
        :return: Closing AK events, or empty when held open / never live.
        """
        opened = open_parts.pop(index, None)
        if opened is None:
            return []
        part_kind, stream_id = opened
        if part_kind in ("text", "thinking") and next_part_kind == part_kind:
            carried[part_kind] = stream_id
            return []
        if part_kind == "text":
            return [MessageEnd(message_id=stream_id)]
        if part_kind == "thinking":
            return [ReasoningEnd(message_id=stream_id)]
        return [ToolCallEnd(tool_call_id=stream_id)]

    def _tool_result(self, event: Any) -> list[StreamEvent]:
        """
        Map a `function_tool_result` onto `ToolCallResult`.

        :param event: A `function_tool_result` run event.
        :return: A single `ToolCallResult`, or empty if there is no `tool_call_id`.
        """
        part = getattr(event, "part", None)
        tool_call_id = getattr(part, "tool_call_id", None)
        if not tool_call_id:
            _log.debug("Pydantic AI tool result carries no tool_call_id; not emitted")
            return []
        content = getattr(part, "content", None)
        if content is None:
            content = getattr(event, "content", None)
        return [ToolCallResult(tool_call_id=tool_call_id, content=self._as_text(content))]

    @staticmethod
    def _as_text(value: Any) -> str:
        """
        Render a tool result as text for the client.

        :param value: The tool result payload.
        :return: String content for `ToolCallResult`.
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(to_jsonable_python(value), default=str)
        except Exception:
            return str(value)

    @staticmethod
    def _as_json(value: Any, what: str) -> str:
        """
        Serialise a tool-argument payload (string or dict) to JSON text.

        On encode failure returns `""` so a mid-stream exception does not fail the run.

        :param value: Arguments as a string, dict, or None.
        :param what: What is being serialised, for the log line.
        :return: JSON/string fragment, or `""` if missing/unencodable.
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, default=str)
        except Exception as e:
            _log.warning(f"Pydantic AI tool {what} could not be serialised; it is emitted empty: {e!r}")
            return ""


class PydanticAIAgent(BaseAgent):
    """
    PydanticAIAgent class provides an agent wrapping for Pydantic AI-based agents.
    """

    def __init__(self, name: str, runner: PydanticAIRunner, agent: PydanticAgent):
        """
        Initializes a PydanticAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The Pydantic AI agent instance.
        """
        super().__init__(name, runner)
        self._agent = agent
        self._attach_system_tools()
        self._setup_system_prompt()

    @property
    def agent(self) -> PydanticAgent:
        """
        Returns the Pydantic AI agent instance.
        """
        return self._agent

    def get_description(self) -> str:
        """
        Returns the description of the agent, falling back to its static instructions when the
        agent was constructed without ``description=``.
        """
        if self.agent.description:
            return self.agent.description
        try:
            instructions = getattr(self.agent, "_instructions", None) or []
            return " ".join(i for i in instructions if isinstance(i, str))
        except Exception:
            return ""

    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends additional instructions to the Pydantic AI agent's system prompt via the
        ``agent.instructions(func)`` decorator API. Pydantic AI instructions have no public read
        path, so no de-duplication is possible; safe because this runs once per Agent init.
        """
        if prompt:
            self._agent.instructions(lambda: prompt)

    def attach_tool(self, tool: Any) -> None:
        """
        Accepts a raw Callable, wraps it with PydanticAIToolBuilder, and registers it on the
        agent's function toolset. Called by the base Agent._attach_system_tools() at init to
        register system tools (e.g., the multimodal attachment-analysis tool).
        :param tool: Raw Python callable to attach.
        """
        wrapped = PydanticAIToolBuilder.bind([tool])
        # Register on the agent's own FunctionToolset. AK never uses the ``toolsets=`` constructor
        # parameter, so the agent always exposes exactly one FunctionToolset (its own), reachable
        # via the public ``toolsets`` property.
        function_toolset = next((ts for ts in self._agent.toolsets if isinstance(ts, FunctionToolset)), None)
        if function_toolset is None:
            return
        for w in wrapped:
            if w.name not in function_toolset.tools:
                function_toolset.add_tool(w)

    def get_a2a_card(self) -> Any:
        """
        Returns the A2A AgentCard associated with the agent.
        """
        from a2a.types import AgentSkill

        skills = []

        def visitor(ts: Any) -> None:
            # Only FunctionToolset (and subclasses) expose a public synchronous ``tools`` dict; the
            # general async ``get_tools(ctx)`` path needs a RunContext that isn't available here, so
            # non-FunctionToolset leaves (e.g. MCP servers) are silently skipped. AK never attaches
            # those to a wrapped agent, so this is complete in practice.
            if isinstance(ts, FunctionToolset):
                for name, tool in ts.tools.items():
                    skills.append(AgentSkill(id=name, name=name, description=tool.description or "", tags=[]))

        # ``apply()`` recurses into CombinedToolset/WrapperToolset members, so every real leaf
        # toolset is reached regardless of nesting. Do not index ``[0]`` — the toolset count varies.
        for toolset in self.agent.toolsets:
            toolset.apply(visitor)

        return A2ACardBuilder.build(name=self.name, description=self.get_description(), skills=skills)


class PydanticAIModule(Module):
    """
    PydanticAIModule class provides a module for Pydantic AI-based agents.
    """

    def __init__(self, agents: list[PydanticAgent], runner: PydanticAIRunner = None):
        """
        Initializes a PydanticAIModule instance.
        :param agents: List of agents in the module.
        :param runner: Custom runner associated with the module.
        """
        super().__init__()
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().pydanticai()
        else:
            self.runner = PydanticAIRunner()
        self.load(agents)

    def _wrap(self, agent: PydanticAgent, agents: List[PydanticAgent]) -> BaseAgent:
        """
        Wraps the provided agent in a PydanticAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: PydanticAIAgent instance.
        :raises ValueError: If the agent has no explicit name.
        """
        if agent.name is None:
            raise ValueError(
                "Pydantic AI agents passed to PydanticAIModule must have an explicit name= — "
                "AK registers agents by name immediately, before any run triggers Pydantic AI's "
                "call-frame name inference."
            )
        return PydanticAIAgent(agent.name, self.runner, agent)

    def load(self, agents: list[PydanticAgent]) -> PydanticAIModule:
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: PydanticAIModule instance.
        """
        super().load(agents)
        return self

    def pre_hook(self, agent: PydanticAgent, hooks: list[PreHook]) -> "PydanticAIModule":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: PydanticAIModule instance.
        """
        super().get_agent(agent.name).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: PydanticAgent, hooks: list[PostHook]) -> "PydanticAIModule":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: PydanticAIModule instance.
        """
        super().get_agent(agent.name).post_hooks.extend(hooks)
        return self


class PydanticAIToolBuilder(ToolBuilder):
    """
    Tool builder for Pydantic AI. Wraps generic tool functions into Pydantic AI ``Tool``
    objects; AK tools reach execution context via ``ToolContext.get()``, not ``RunContext``.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Tool]:
        """
        Bind generic tool functions to Pydantic AI ``Tool`` definitions.

        :param funcs: List of generic tool functions to bind.
        :return: List of Pydantic AI ``Tool`` definitions.
        :raises TypeError: If any item in funcs is not callable.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(Tool(func))
        return tools
