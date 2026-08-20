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

            # `deps` is Pydantic AI's only caller-dependency slot and AK owns it, so tools and instruction
            # functions read and mutate the context via RunContext.deps.
            # A deep copy is passed in so tools mutating it in place don't also mutate `incoming`.
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

        **`run_stream_events()` replaces `run_stream()` + `stream_text(delta=True)`.** The old pair
        could only ever yield prose: `stream_text` is text-only by construction, so tool calls and a
        thinking model's reasoning were unreachable no matter what the consumer wanted. The
        replacement yields the run's whole event stream, and it must be used as an async context
        manager — the background run task is cleaned up on exit, and it does not start until the
        first iteration.

        **Every stream is driven by the part events, and the ids come from the framework.** Pydantic
        AI brackets each part of a response with `part_start` / `part_delta` / `part_end`, which is
        one shape serving all three of AK's streams — the part's own `part_kind` decides which:

        - `text` → `MessageStart` / `TextDelta` / `MessageEnd`
        - `thinking` → `ReasoningStart` / `ReasoningDelta` / `ReasoningEnd`, kept apart from the
          answer because §4 rule 5 keeps reasoning out of `StreamChunk.delta`
        - `tool-call` → `ToolCallStart` / `ToolCallArgs` / `ToolCallEnd`, and `function_tool_result`
          supplies the matching `ToolCallResult`

        **`index` alone cannot be the id, which is the one place this deviates from §10's sketch.**
        `PartStartEvent.index` is the part's position *within one response*, so a run that calls a
        tool and then answers restarts at 0 and two unrelated messages would collide on one id — an
        AG-UI client would splice them into one bubble. The SDK is explicit that a repeated index
        *replaces* the part rather than continuing it. So `open_parts` maps each live index to the AK
        id allocated when it opened: a text or thinking part takes the provider's `part.id` when there
        is one and a generated id otherwise, and a tool call takes its own `tool_call_id`, which is
        never generated because the result has to correlate to it. A repeat at the same index closes
        the old stream before opening a new one, so nothing is left dangling.

        `open_parts` is a **local**, and passed in rather than held on `self`: one runner instance
        serves every agent and every concurrent session, so on `self` one run would close another's
        message or two runs would share an id (spec §10).

        **`function_tool_call` is deliberately ignored.** The part events above already opened, filled
        and closed the call, so mapping it too would emit every tool call twice — the same reason
        OpenAI ignores `message_output_created`.

        The two things that used to live inside the old `async with` block still run only after the
        stream drains normally: the session-message bookkeeping, which now reads `all_messages()` off
        the `agent_run_result` event captured as it passed rather than off the context manager's
        value, and `_store_framework_context`. Neither is in a `finally`, so a client disconnect
        leaves the stored context and history untouched.

        Note: a streaming run stops at the first ``output_type`` match, so structured outputs
        may truncate differently than the non-streaming ``run()`` path.

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

            # Locals, never on self — see the docstring. `open_parts` maps a live part index to the
            # (kind, id) it opened with; `run_result` is the final event's result, kept for the
            # history write-back once the stream has drained.
            open_parts: dict[int, tuple[str, str]] = {}
            run_result: Any = None

            async with agent.agent.run_stream_events(content, message_history=history, deps=produced) as events:
                async for event in events:
                    kind = getattr(event, "event_kind", None)
                    if kind == "agent_run_result":
                        run_result = getattr(event, "result", None)
                        continue
                    for stream_event in self._map_event(kind, event, open_parts):
                        yield stream_event

            # Closing whatever the stream never closed itself. Reached only on a clean drain: a client
            # disconnect raises GeneratorExit at a yield above and unwinds past this.
            for index in list(open_parts):
                for stream_event in self._close_part(index, open_parts):
                    yield stream_event

            if fw_session is not None and run_result is not None:
                fw_session.messages = to_jsonable_python(run_result.all_messages())

            # Only after the stream drains normally, so a disconnect or mid-stream error leaves the stored
            # context intact. Deliberately not in a finally.
            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)
        finally:
            if context is not None:
                context.reset()

    def _map_event(self, kind: str | None, event: Any, open_parts: dict[int, tuple[str, str]]) -> list[StreamEvent]:
        """Translate one Pydantic AI run event into AK events.

        Discriminates on `event_kind`, which is the SDK's own field — only AK's event model uses
        `type`. An event kind with no branch maps to nothing: `function_tool_call` because the part
        events already carried the call, and `final_result`, `output_tool_call`, `output_tool_result`,
        `enqueued_messages` and the two `deferred_tool_*` kinds because AK has no event for them.

        :param kind: The event's `event_kind` discriminator.
        :param event: The run event.
        :param open_parts: The caller's live index → (kind, id) map, mutated here.
        :return: The AK events this run event produces, empty when it maps to nothing.
        """
        if kind == "part_start":
            return self._open_part(event, open_parts)
        if kind == "part_delta":
            return self._delta_part(event, open_parts)
        if kind == "part_end":
            return self._close_part(event.index, open_parts)
        if kind == "function_tool_result":
            return self._tool_result(event)
        return []

    def _open_part(self, event: Any, open_parts: dict[int, tuple[str, str]]) -> list[StreamEvent]:
        """Open a part's stream, closing any part already live at that index first.

        The SDK states that a second `part_start` on one index replaces the first, so the old stream
        is terminated rather than left open — a consumer that already rendered its deltas needs the
        boundary.
        """
        index = event.index
        part = getattr(event, "part", None)
        part_kind = getattr(part, "part_kind", None)

        events: list[StreamEvent] = []
        if index in open_parts:
            events.extend(self._close_part(index, open_parts))

        if part_kind == "text":
            message_id = getattr(part, "id", None) or uuid4().hex
            open_parts[index] = ("text", message_id)
            events.append(MessageStart(message_id=message_id))
            content = getattr(part, "content", None)
            if content:
                events.append(TextDelta(message_id=message_id, content=content))
            return events

        if part_kind == "thinking":
            message_id = getattr(part, "id", None) or uuid4().hex
            open_parts[index] = ("thinking", message_id)
            events.append(ReasoningStart(message_id=message_id))
            content = getattr(part, "content", None)
            if content:
                events.append(ReasoningDelta(message_id=message_id, content=content))
            return events

        if part_kind == "tool-call":
            # Never generated: the result correlates on this id, so a made-up one could not match.
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

        # builtin-tool-call, builtin-tool-return, compaction, file — no AK event carries these.
        return events

    def _delta_part(self, event: Any, open_parts: dict[int, tuple[str, str]]) -> list[StreamEvent]:
        """Forward one delta onto the stream its index opened.

        A delta for an index that never opened is dropped rather than guessed at: without the part
        that started it there is no id to correlate to, and inventing one would strand the fragment
        in a message no boundary describes.
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

    def _close_part(self, index: int, open_parts: dict[int, tuple[str, str]]) -> list[StreamEvent]:
        """Close the stream an index opened, if it is still live."""
        opened = open_parts.pop(index, None)
        if opened is None:
            return []
        part_kind, stream_id = opened
        if part_kind == "text":
            return [MessageEnd(message_id=stream_id)]
        if part_kind == "thinking":
            return [ReasoningEnd(message_id=stream_id)]
        return [ToolCallEnd(tool_call_id=stream_id)]

    def _tool_result(self, event: Any) -> list[StreamEvent]:
        """Map a `function_tool_result` onto `ToolCallResult`.

        The id is read off the result part, where both `ToolReturnPart` and `RetryPromptPart` carry a
        required `tool_call_id` — a retry is a result too, and hiding it would leave the call looking
        unanswered. The part's own content is preferred over the event's, so what a UI renders is what
        the model was handed.
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
        """Render a tool result as the text a client shows. Strings pass through untouched."""
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
        """Serialise a tool-argument payload, which arrives as a string on some providers and a parsed
        dict on others.

        The `except` is deliberately broad, for the reason the ADK adapter documents: `default=str`
        hands any unencodable value to arbitrary `__str__`, and this runs mid-stream where an escaping
        exception turns an in-flight response into a failed run. The arguments are the expendable
        part — dropping them still leaves the call bracketed and correlated.
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
