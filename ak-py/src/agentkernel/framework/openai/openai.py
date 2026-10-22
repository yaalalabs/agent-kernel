from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, ClassVar, List, Mapping, Type

from agents import Agent, FunctionTool, Runner, function_tool
from agents.realtime import RealtimeAgent, RealtimeRunner, RealtimeSession
from agents.run_state import RunState
from openai.types.responses.response_output_item_added_event import ResponseOutputItemAddedEvent
from openai.types.responses.response_output_item_done_event import ResponseOutputItemDoneEvent
from openai.types.responses.response_reasoning_summary_text_delta_event import ResponseReasoningSummaryTextDeltaEvent
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

from ...core import Agent as BaseAgent
from ...core import Module
from ...core import RealtimeRunner as BaseRealtimeRunner
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder, ToolContext
from ...core.builder import A2ACardBuilder
from ...core.config import AKConfig
from ...core.event import (
    MessageEnd,
    MessageStart,
    PausedInterruption,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    RunPaused,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from ...core.model import (
    AgentPausedReplyAny,
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
    ResumeDecision,
)
from ...core.paused_run import PausedRun, PausedRunState
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
                    # A remote reference goes as ``file_url``; adding an inline ``file_data`` part
                    # for it too would send the URL as if it were base64 payload.
                    message_content.append({"role": "user", "content": [{"type": "input_file", "file_url": file_url}]})
                else:
                    if not file_url.startswith("data:"):
                        if not req.mime_type:
                            raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
                        file_url = f"data:{req.mime_type};base64,{file_url}"
                    message_content.append({"role": "user", "content": [{"type": "input_file", "filename": req.name, "file_data": file_url}]})

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
            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            # Injected as the run context, so tools read and write it via RunContextWrapper.context.
            # A deep copy is passed in so tools mutating it in place don't also mutate `incoming`.
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            # Resolved run options (max_turns, hooks, run_config, ...) first; the keys AK owns are written last.
            kwargs = self._native_kwargs(options, session=self._session(session), context=produced)
            result = await Runner.run(agent.agent, input_data, **kwargs)

            self._store_framework_context(session, incoming, produced)

            if result.interruptions:
                return self._paused_reply(agent, session, result)

            reply = result.final_output
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

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — the SDK's RunState is a self-contained, JSON-serialisable snapshot.
        """
        return True

    def _paused_reply(self, agent: Any, session: Session, result: Any) -> AgentPausedReplyAny:
        """
        Records a paused run and returns the reply that carries it back to the caller.

        Appends rather than replaces, which only this adapter can do: a `RunState` is a
        self-contained snapshot, and two were verified to resume independently
        (`research/verification.md`). The single-thread adapters replace, because their framework
        keeps one conversation per session and the earlier pause stops being resumable.

        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param result: The SDK result carrying non-empty `interruptions`.
        :return: The paused reply, carrying the assigned run id.
        """
        record = PausedRunState.add(
            session,
            agent=agent.name,
            runner=self.name,
            interruptions=[
                PausedInterruption(id=item.call_id, kind="tool_call", tool_name=item.name, arguments=item.arguments) for item in result.interruptions
            ],
            payload=result.to_state().to_json(),
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    @staticmethod
    def _reject_unresumable(decisions: list[ResumeDecision], requests: list[AgentRequest]) -> None:
        """
        Refuses the two things this SDK has no channel for, before the adapter's `try` opens.

        Both are raised here rather than in `Runtime` because neither is a framework-agnostic rule —
        `Runtime` would need to know what the OpenAI SDK accepts — and above the `try` because the
        `except Exception` below would turn either into a generic "something went wrong" reply.

        :param decisions: The human's decisions.
        :param requests: The hook-processed request list.
        :raises ValueError: If a decision carries a payload, or a prompt rides along with the resume.
        """
        with_payload = sorted(decision.id for decision in decisions if decision.payload is not None)
        if with_payload:
            raise ValueError(
                f"The OpenAI adapter cannot deliver a structured answer: decision(s) {with_payload} carry a payload, "
                f"and RunState.approve() takes no value. Model the question as a gated tool's arguments instead."
            )

        if any(isinstance(req, AgentRequestText) and req.prompt for req in requests):
            raise ValueError(
                "The OpenAI adapter cannot carry a prompt alongside a decision: Runner.run()'s input is either "
                "a RunState or new input, never both. Send the prompt as a separate turn once the run has resumed."
            )

    @staticmethod
    async def _restore(agent: Any, record: PausedRun) -> RunState:
        """
        Rebuilds the paused run's SDK state from the stored payload.

        Also above the `try`: a payload written by an older SDK fails `_schema_version` here, and
        that has to reach the caller naming the runner rather than arriving as a generic reply.

        `from_json` is async — it may re-resolve handoffs and hosted tools while rebuilding — which
        is the one place this adapter awaits something the rest of the SDK's state API does not.

        :param agent: The agent the record belongs to.
        :param record: The validated paused-run record.
        :return: The restored state, ready for decisions to be applied.
        :raises ValueError: If the payload no longer deserialises.
        """
        try:
            return await RunState.from_json(agent.agent, record.payload)
        except Exception as e:
            raise ValueError(
                f"Paused run '{record.id}' cannot be resumed: its stored OpenAI RunState no longer deserialises "
                f"({type(e).__name__}: {e}). This usually means the SDK was upgraded while the run was paused."
            ) from e

    def _apply(self, state: RunState, decisions: list[ResumeDecision]) -> None:
        """
        Renders each decision onto the restored state.

        `cancelled` reaches the model as a rejection carrying AK's own wording, because the SDK has
        only approve and reject: without it, "nobody decided" would be indistinguishable from "the
        human refused", which is the distinction the three-valued status exists to keep.

        :param state: The restored state.
        :param decisions: The human's decisions, already validated against the record by Runtime.
        :raises ValueError: If a decision names an interruption the restored state does not hold.
        """
        pending = {item.call_id: item for item in state.get_interruptions()}
        for decision in decisions:
            item = pending.get(decision.id)
            if item is None:
                raise ValueError(
                    f"Decision '{decision.id}' matches no interruption in the restored OpenAI state, "
                    f"which is waiting on: {sorted(i for i in pending if i)}."
                )
            if decision.status == "approved":
                state.approve(item)
            elif decision.status == "denied":
                state.reject(item, rejection_message=decision.message)
            else:
                state.reject(item, rejection_message=self.CANCELLED_DECISION_MESSAGE)

    async def resume(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AgentReply:
        """
        Continues a paused OpenAI run from the human's decisions.

        Mirrors `run()`'s envelope exactly — same tool context, same framework-context load and
        store, same resolved run options through `_native_kwargs` — so a resumed turn is not a
        second-class one: a tool called after the resume sees what a tool called before it saw.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        """
        self._reject_unresumable(decisions, requests)
        state = await self._restore(agent, record)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            self._apply(state, decisions)

            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            kwargs = self._native_kwargs(options, session=self._session(session), context=produced)
            result = await Runner.run(agent.agent, state, **kwargs)

            self._store_framework_context(session, incoming, produced)
            PausedRunState.clear(session, record.id)

            if result.interruptions:
                return self._paused_reply(agent, session, result)

            reply = result.final_output
            structured = AgentReplyAny.from_output(reply)
            if structured is not None:
                return structured
            return AgentReplyText(response="" if reply is None else str(reply))
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e))
        finally:
            if context is not None:
                context.reset()

    async def resume_stream(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Streaming counterpart of `resume()`, mapping events exactly as `stream()` does.

        A pause is detected only once the stream has drained, because `RunResultStreaming` fills
        `interruptions` as the run completes, not as events arrive.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued run produces, ending in RunPaused if it pauses again.
        """
        self._reject_unresumable(decisions, requests)
        state = await self._restore(agent, record)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            self._apply(state, decisions)

            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            kwargs = self._native_kwargs(options, session=self._session(session), context=produced)
            result = Runner.run_streamed(agent.agent, state, **kwargs)

            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    for stream_event in self._map_raw_response(event.data):
                        yield stream_event
                elif event.type == "run_item_stream_event":
                    for stream_event in self._map_run_item(event.name, event.item):
                        yield stream_event

            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)

            PausedRunState.clear(session, record.id)
            if result.interruptions:
                paused = self._paused_reply(agent, session, result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
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
            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            kwargs = self._native_kwargs(options, session=self._session(session), context=produced)
            result = Runner.run_streamed(agent.agent, input_data, **kwargs)

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

            if result.interruptions:
                paused = self._paused_reply(agent, session, result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
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


class OpenAIRealtimeRunner(BaseRealtimeRunner):
    """
    OpenAIRealtimeRunner implements RealtimeRunner on the OpenAI Agents SDK's own realtime runner.

    One native ``RealtimeRunner`` and ``RealtimeSession`` per connection. The SDK owns the
    conversation: the model connection, which agent is speaking, its tools and their results,
    handoffs (``RealtimeAgent.handoffs``, ``realtime_handoff``), guardrails, and interruption. This class only
    feeds caller audio and text to the session, and maps what the session reports onto the
    framework-neutral events the realtime pool paces and queues: audio, transcript, turn end,
    interruption, speaker change and failure.

    The wrapped agent must be a ``RealtimeAgent``. A tool that needs approval cannot run: the
    LiveKit edge has no route for a human's decision, so one declared up front is rejected at connect
    and one that arises later is rejected through the SDK and fails the connection. Agent Kernel
    hooks and guardrails do not run on this path; the SDK's own do.

    ``Module.run_options`` carries the native settings, and nothing else: ``model`` and ``config``
    reach ``RealtimeRunner(...)`` and ``model_config`` reaches ``RealtimeRunner.run(...)``, where the
    model name, the one session voice and the audio settings live. ``context`` is reserved: it is the
    session's framework context.
    """

    # Native settings an agent's run_options may name, by the call that takes them.
    RUNNER_OPTIONS: ClassVar[frozenset[str]] = frozenset({"model", "config"})
    SESSION_OPTIONS: ClassVar[frozenset[str]] = frozenset({"model_config"})
    RESERVED_OPTIONS: ClassVar[Mapping[str, str]] = {
        "starting_agent": "the native agent is the one the OpenAIAgent wraps",
        "context": "populated from the session's framework_context",
    }

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._session: RealtimeSession | None = None
        self._callback: Callable | None = None
        self._listen_task: asyncio.Task | None = None
        # True once disconnect() runs; the listener suppresses its error callback then so a normal
        # shutdown does not surface as a failure.
        self._closing = False
        # True from a turn's start until its end: while it is set, the user starting to speak cuts
        # off a response the model is still generating.
        self._response_in_flight = False
        # The agent whose turn it is, and every agent announced so far.
        self._speaker: str | None = None
        self._roster: list[str] = []

    def team(self, agent: BaseAgent) -> list[str]:
        """Every agent the native graph names publicly, the starting agent first.

        A ``RealtimeAgent`` in ``handoffs`` is followed; a ``realtime_handoff(...)`` names its target
        through its public ``agent_name`` and its agents beyond that are not reached, since the SDK
        keeps the target object private. An agent that cannot be listed early is announced in the
        change that first names it.
        """
        root = getattr(agent, "agent", None)
        if not isinstance(root, RealtimeAgent):
            return [agent.name]
        return [name for name, _ in self._reachable(root)]

    @staticmethod
    def _reachable(root: RealtimeAgent) -> list[tuple[str, RealtimeAgent | None]]:
        """Every agent ``root``'s public ``handoffs`` name, ``root`` first, nearest first.

        Each is the agent's name and, when the graph holds the agent itself, the agent.
        """
        reached: list[tuple[str, RealtimeAgent | None]] = [(root.name, root)]
        seen = {root.name}
        for _, node in reached:
            for item in getattr(node, "handoffs", None) or []:
                target = item if isinstance(item, RealtimeAgent) else None
                name = item.name if target is not None else getattr(item, "agent_name", None)
                if isinstance(name, str) and name and name not in seen:
                    seen.add(name)
                    reached.append((name, target))
        return reached

    async def connect(self, session: Session, agent: BaseAgent, callback: Callable) -> None:
        root = getattr(agent, "agent", None)
        if not isinstance(root, RealtimeAgent):
            raise TypeError(
                f"Agent '{agent.name}' wraps {type(root).__name__}; realtime mode runs an OpenAI Agents SDK RealtimeAgent "
                "(agents.realtime.RealtimeAgent), which carries its own tools and handoffs"
            )
        self._callback = callback
        self._speaker = agent.name
        self._roster = self.team(agent)
        runner_options, session_options = await self._options(agent, session)
        self._check_agents(root)
        context = self._load_framework_context(session)

        try:
            native = RealtimeRunner(root, **runner_options)
            self._session = await native.run(context=context, **session_options)
            await self._session.enter()
        except (Exception, asyncio.CancelledError):
            # The pool does not disconnect a connection whose connect failed, so what is open is closed here.
            await self.disconnect()
            raise

        self._listen_task = asyncio.create_task(self._listen())

    async def _options(self, agent: BaseAgent, session: Session) -> tuple[dict[str, Any], dict[str, Any]]:
        """The agent's run options, resolved once for this connection and split by the native call that takes them.

        :raises ValueError: Naming the agent and every key the realtime session cannot take.
        """
        options = await agent.resolve_run_options(session, [])
        rejected = {key: self.RESERVED_OPTIONS.get(key, "not a setting of the SDK's realtime runner") for key in options}
        rejected = {key: why for key, why in rejected.items() if key not in self.RUNNER_OPTIONS | self.SESSION_OPTIONS}
        if rejected:
            details = "; ".join(f"'{key}': {why}" for key, why in sorted(rejected.items()))
            accepted = ", ".join(sorted(self.RUNNER_OPTIONS | self.SESSION_OPTIONS))
            raise ValueError(
                f"Run option(s) cannot apply to a realtime session of agent '{agent.name}': {details}. A realtime session takes: {accepted}"
            )
        return (
            {key: value for key, value in options.items() if key in self.RUNNER_OPTIONS},
            {key: value for key, value in options.items() if key in self.SESSION_OPTIONS},
        )

    def _check_agents(self, root: RealtimeAgent) -> None:
        """Reject, before anything opens, what the realtime path cannot run, naming the agent and the tool.

        A tool that needs approval has no decision route on this edge.
        """
        for name, native in self._reachable(root):
            if native is None:
                continue
            for tool in native.tools or []:
                if isinstance(tool, FunctionTool) and tool.needs_approval is not False:
                    raise ValueError(
                        f"Tool '{tool.name}' of agent '{name}' needs approval, which a realtime session cannot get: "
                        "the LiveKit edge has no route for a human's decision"
                    )

    async def _listen(self) -> None:
        """Report the session's events to the pool, in order. The pool paces audio and emits chunks."""
        try:
            # The session's event stream is an async generator: closed here when listening stops (a
            # cancel included), not left half-run for the loop's shutdown to close twice.
            async with contextlib.aclosing(aiter(self._session)) as events:
                async for event in events:
                    await self._handle_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log.error(f"OpenAI realtime session error: {e}")
            if not self._closing:
                await self._callback("error", {"message": f"OpenAI realtime session error: {e}"})
            return
        if not self._closing:
            # A clean end is the session closing under us, not a turn finishing: the connection is over.
            await self._callback("error", {"message": "OpenAI realtime session ended"})

    async def _handle_event(self, event: Any) -> None:
        """Map one SDK session event onto the pool's events."""
        kind = event.type
        if kind == "audio":
            await self._callback("audio_delta", {"delta": base64.b64encode(event.audio.data).decode("utf-8"), "message_id": event.item_id})
        elif kind == "raw_model_event":
            await self._handle_model_event(event.data)
        elif kind == "handoff":
            await self._speaker_changed(event.to_agent.name, event.from_agent.name)
        elif kind == "agent_start":
            await self._speaker_changed(event.agent.name)
        elif kind == "audio_interrupted":
            await self._interrupted()
        elif kind == "guardrail_tripped":
            _log.warning(f"Realtime output guardrail tripped: {event.message[:200]}")
            await self._interrupted()
        elif kind == "tool_approval_required":
            await self._refuse_approval(event)
        elif kind == "error":
            # A server error event the session survives (a cancel racing a finished response, a tool
            # the model named that does not exist); a session that cannot continue raises instead.
            _log.warning(f"OpenAI realtime error: {event.error}")

    async def _handle_model_event(self, data: Any) -> None:
        kind = data.type
        if kind in ("transcript_delta", "output_text_delta"):
            await self._callback("transcript_delta", {"delta": data.delta, "message_id": data.item_id})
        elif kind == "turn_started":
            self._response_in_flight = True
        elif kind == "turn_ended":
            self._response_in_flight = False
            await self._callback("done", {"status": "completed"})

    async def _speaker_changed(self, agent: str, previous: str | None = None) -> None:
        """Report a change of speaker once, when the native session names an agent other than the current one.

        The SDK reports a handoff, then the new agent's turn start: the second names the agent already
        announced and is not repeated. An agent the roster did not hold is added to it, and the roster
        rides on this change.
        """
        if agent == self._speaker:
            return
        data: dict[str, Any] = {"agent": agent, "previous_agent": previous or self._speaker}
        if agent not in self._roster:
            self._roster.append(agent)
            data["agents"] = list(self._roster)
        self._speaker = agent
        await self._callback("agent_changed", data)

    async def _interrupted(self) -> None:
        """Report that unheard output must stop: a barge-in while the model responds, or the user speaking over audio the pool still holds.

        The SDK reports both as one event, and the pool tells them apart: an ``interrupt`` always
        cuts the turn, while ``speech_started`` only does while audio is still queued. Told apart here
        by whether a response is in flight, which a further interruption of the same response then is not.
        """
        if self._response_in_flight:
            self._response_in_flight = False
            await self._callback("interrupt", {})
        else:
            await self._callback("speech_started", {})

    async def _refuse_approval(self, event: Any) -> None:
        """Refuse a tool call that needs a human's decision, and fail the connection.

        There is no decision route on this edge, so the call is never approved: the SDK is told it
        was rejected (the model is not left waiting) and the connection ends with a message naming
        the tool, instead of the call silently doing nothing.
        """
        name = getattr(event.tool, "name", "?")
        try:
            await self._session.reject_tool_call(event.call_id)
        finally:
            await self._callback(
                "error", {"message": f"Tool '{name}' of agent '{event.agent.name}' needs approval, which a realtime session cannot get"}
            )

    async def append_audio(self, base64_audio: str) -> None:
        if self._session is not None:
            await self._session.send_audio(base64.b64decode(base64_audio))

    async def send_text(self, text: str) -> None:
        if self._session is not None:
            await self._session.send_message(text)

    async def disconnect(self) -> None:
        self._closing = True
        task, self._listen_task = self._listen_task, None
        await self._cancel_and_wait(task)
        session, self._session = self._session, None
        if session is not None:
            await session.close()


class OpenAIAgent(BaseAgent):
    """
    OpenAIAgent class provides an agent wrapping for OpenAI Agent SDK-based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "starting_agent": "the native agent is the one this OpenAIAgent wraps",
        "input": "built from the AgentRequest list by the runner",
        "session": "the OpenAISession stored on the Agent Kernel session",
        "context": "populated from the session's framework_context; seed it with Session.set_framework_context()",
        "conversation_id": "conversation state is the OpenAISession passed as session=; the SDK rejects combining them",
        "previous_response_id": "conversation state is the OpenAISession passed as session=; the SDK rejects combining them",
        "auto_previous_response_id": "conversation state is the OpenAISession passed as session=; the SDK rejects combining them",
    }

    def __init__(self, name: str, runner: OpenAIRunner, agent: Agent | RealtimeAgent, realtime_runner_cls: Type[BaseRealtimeRunner] = None):
        """
        Initializes an OpenAIAgent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        :param agent: The OpenAI agent instance.
        :param realtime_runner_cls: Optional realtime runner class for this agent.
        """
        super().__init__(name, runner, realtime_runner_cls)
        self._agent = agent
        if AKConfig.get().execution.mode != ExecutionMode.REALTIME:
            self._attach_system_tools()
            self._setup_system_prompt()

    @property
    def agent(self) -> Agent | RealtimeAgent:
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
        agents: list[Agent | RealtimeAgent],
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
        self.realtime_runner_cls = realtime_runner_cls or OpenAIRealtimeRunner
        if runner is not None:
            self.runner = runner
        elif AKConfig.get().trace.enabled:
            self.runner = Trace.get().openai()
        else:
            self.runner = OpenAIRunner()
        self.load(agents)

    def _wrap(self, agent: Agent | RealtimeAgent, agents: List[Agent | RealtimeAgent]) -> BaseAgent:
        """
        Wraps the provided agent in an OpenAIAgent instance.
        :param agent: Agent to wrap.
        :param agents: List of agents in the module.
        :return: OpenAIAgent instance.
        """
        # The realtime runner class is attached unconditionally: only the pipeline (in REALTIME
        # mode) ever instantiates it, so the framework need not know the execution mode.
        return OpenAIAgent(agent.name, self.runner, agent, realtime_runner_cls=self.realtime_runner_cls)

    def load(self, agents: list[Agent | RealtimeAgent]) -> OpenAIModule:
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: OpenAIModule instance.
        """
        super().load(agents)
        return self


class OpenAIToolBuilder(ToolBuilder):
    """
    Tool builder for OpenAI Agents SDK.

    Wraps generic tool functions into OpenAI-compatible tool definitions
    using the ``function_tool`` helper from the OpenAI Agents SDK.
    """

    @classmethod
    def bind(cls, funcs: list[Callable], **options: Any) -> list[Any]:
        """
        Bind generic tool functions to OpenAI Agents SDK tool definitions.

        Keyword options are forwarded to `function_tool` untouched and apply to every function in
        the call, so tools wanting different options are bound in separate calls. Without this a
        gated tool could not be declared through the builder at all: `needs_approval` is one of
        `function_tool`'s keyword-only arguments, and for this SDK that flag *is* the
        human-in-the-loop pause. A caller would have been forced back to the decorator, giving up
        the framework-free tool function the builder exists to allow.

        :param funcs: List of generic tool functions to bind.
        :param options: Keyword arguments passed to `function_tool`, e.g. `needs_approval=True`.
        :return: List of OpenAI-compatible tool definitions.
        :raises TypeError: If any item in funcs is not callable, or an option is not one the SDK takes.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(function_tool(func, **options))
        return tools
