from __future__ import annotations

import base64
import copy
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, ClassVar, List, Literal, Mapping
from uuid import uuid4

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import BinaryContent, DeferredToolRequests, DeferredToolResults, DocumentUrl, FunctionToolset, ImageUrl, Tool
from pydantic_ai.messages import ModelMessagesTypeAdapter, UserContent
from pydantic_ai.tools import ToolApproved, ToolDenied
from pydantic_core import to_jsonable_python

from ...core import Agent as BaseAgent
from ...core import Module
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
    ResumeDecision,
)
from ...core.paused_run import PausedRun, PausedRunState
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
        self._event_stream_handler_warned = False
        """Whether the stream-mode event_stream_handler drop was already logged for this runner."""

    def _stream_run_options(self, options: Mapping[str, Any]) -> dict[str, Any]:
        """
        The run options resolved for one run without `event_stream_handler`, which `run_stream_events` does not
        accept (it is itself the event stream, and the runner's own StreamEvents carry the same information). Logged
        once per runner when a handler was present.
        :param options: The run options resolved for this run.
        :return: A filtered copy of the options for the stream call; the input mapping is untouched.
        """
        filtered = dict(options)
        if filtered.pop("event_stream_handler", None) is not None and not self._event_stream_handler_warned:
            _log.warning(
                "Pydantic AI event_stream_handler is ignored in Agent Kernel stream mode; the runner's own stream events "
                "carry the same information"
            )
            self._event_stream_handler_warned = True
        return filtered

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
        self._reject_while_a_decision_is_outstanding(session)

        context: ToolContext | None = None
        prompt = ""
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)

            if not content:
                return AgentReplyText(response="Sorry. No valid content found in the requests")

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

            # Deep copy so in-place tool mutations do not alter `incoming`.
            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            # Resolved run options (usage_limits, model_settings, ...) first; the keys AK owns are written last.
            kwargs = self._native_kwargs(options, message_history=history, deps=produced)
            result = await agent.agent.run(content, **kwargs)

            if fw_session is not None:
                fw_session.messages = to_jsonable_python(result.all_messages())

            self._store_framework_context(session, incoming, produced)

            if isinstance(result.output, DeferredToolRequests):
                return self._paused_reply(agent, session, result)

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

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — deferred requests come back as typed output and resume through the same run call.
        """
        return True

    def _paused_reply(self, agent: Any, session: Session, result: Any) -> AgentPausedReplyAny:
        """
        Records a paused run and returns the reply that carries it back to the caller.

        Two axes arrive together and mean different things. `approvals` is a gated tool waiting for a
        yes or no, so it maps to `tool_call`; `calls` is a tool that raised `CallDeferred` and is
        waiting for somebody to supply its **return value**, so it maps to `input_required`. Mapping
        both to one kind would lose the difference between "may I?" and "what is it?".

        Replaces rather than appends: the framework keeps one message history per session and refuses
        a new question while a decision is outstanding, so an earlier record could never be resumed.
        Scoped to this runner, since a pause another framework holds on the same session is a
        separate conversation and still answerable.

        The record carries the message history rather than leaning on the session's copy, so the
        pause stays resumable no matter what the session does next.

        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param result: The run result whose `output` is a `DeferredToolRequests`.
        :return: The paused reply, carrying the assigned run id.
        """
        PausedRunState.clear_for_runner(session, self.name)

        requested = result.output
        interruptions = [self._interruption(part, "tool_call") for part in requested.approvals]
        interruptions += [self._interruption(part, "input_required") for part in requested.calls]

        record = PausedRunState.add(
            session,
            agent=agent.name,
            runner=self.name,
            interruptions=interruptions,
            payload={"messages": to_jsonable_python(result.all_messages())},
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    @staticmethod
    def _interruption(part: Any, kind: Literal["tool_call", "input_required"]) -> PausedInterruption:
        """
        Maps one pending `ToolCallPart` onto an interruption.

        :param part: The tool call awaiting a human.
        :param kind: `tool_call` for an approval, `input_required` for a deferred call.
        :return: The interruption to carry back to the caller.
        """
        try:
            arguments = part.args if isinstance(part.args, str) else json.dumps(part.args, default=str)
        except Exception:
            arguments = None
        return PausedInterruption(id=part.tool_call_id, kind=kind, tool_name=part.tool_name, arguments=arguments)

    def _reject_while_a_decision_is_outstanding(self, session: Session) -> None:
        """
        Refuses an ordinary turn while this framework's pause is still unanswered.

        Pydantic AI's `Agent.run` will not take a new prompt while the message history holds
        unprocessed tool calls — it raises `UserError`, which the `except` below would flatten into
        "Sorry, something went wrong". The run is going to fail either way; this makes it fail saying
        *why*, and names the run to resume. Only this runner's records are consulted: a pause another
        framework holds on the same session has no bearing on this agent's history.

        :param session: The session whose paused runs to inspect.
        :raises ValueError: If this runner holds an unanswered paused run in this session.
        """
        outstanding = next((record for record in PausedRunState.list(session) if record.runner == self.name), None)
        if outstanding is not None:
            raise ValueError(
                f"Pydantic AI cannot take a new prompt while run '{outstanding.id}' is waiting on a decision: "
                f"the message history still holds unprocessed tool calls. Answer it with a 'resume' block first, "
                f"or start a new session."
            )

    @staticmethod
    def _reject_partial(decisions: list[ResumeDecision], record: PausedRun) -> None:
        """
        Refuses a resume that leaves any deferred call unanswered, before the adapter's `try` opens.

        The framework's own error here is unusually good — it names the expected and received ids —
        and the `except Exception` below would replace it with "Sorry, something went wrong". Agent
        Kernel pre-empts it to keep a message of the same quality, and to stop a partial answer
        reaching a framework that cannot use one.

        :param decisions: The human's decisions.
        :param record: The record Runtime validated.
        :raises ValueError: If any interruption in the record has no decision.
        """
        answered = {decision.id for decision in decisions}
        missing = sorted(i.id for i in record.interruptions if i.id not in answered)
        if missing:
            raise ValueError(
                f"Pydantic AI needs every deferred tool call resolved in one resume; {missing} were not answered. "
                f"Answer all of {sorted(i.id for i in record.interruptions)} together."
            )

    @staticmethod
    def _reject_unusable_override(decisions: list[ResumeDecision], record: PausedRun) -> None:
        """
        Refuses a payload an approval cannot carry, before the adapter's `try` opens.

        On an approval the payload becomes `ToolApproved(override_args=...)`, which replaces the
        tool call's arguments and so must be an object. Anything else has nowhere to go, and
        dropping it silently would run the tool with its original arguments while the human believes
        their answer was used. A deferred call is unaffected — there the payload is the tool's return
        value and any JSON shape is passed through.

        :param decisions: The human's decisions.
        :param record: The record naming which interruption is which kind.
        :raises ValueError: If an approved gated call carries a payload that is not an object.
        """
        kinds = {i.id: i.kind for i in record.interruptions}
        offenders = sorted(
            decision.id
            for decision in decisions
            if kinds.get(decision.id) == "tool_call"
            and decision.status == "approved"
            and decision.payload is not None
            and not isinstance(decision.payload, dict)
        )
        if offenders:
            raise ValueError(
                f"A Pydantic AI approval can only carry a JSON object as its payload; decision(s) {offenders} carry another shape. "
                f"The payload becomes the tool call's override_args, so send an object of argument names, or answer the question "
                f"as a deferred tool call instead, where any value is passed through."
            )

    def _deferred_results(self, decisions: list[ResumeDecision], record: PausedRun) -> DeferredToolResults:
        """
        Renders the decisions onto the two channels the framework takes.

        An approval becomes a verb: `cancelled` is a denial carrying Agent Kernel's own wording,
        because the framework has only approve and deny and "nobody decided" must not read as a
        refusal. A deferred call becomes a **value** — whatever the human supplied is what the tool
        appears to have returned, so a list arrives as a list and a string as a string.

        :param decisions: The human's decisions.
        :param record: The record naming which interruption is which kind.
        :return: The results to hand the framework.
        """
        kinds = {i.id: i.kind for i in record.interruptions}
        results = DeferredToolResults()
        for decision in decisions:
            if kinds.get(decision.id) == "tool_call":
                results.approvals[decision.id] = self._approval(decision)
            else:
                results.calls[decision.id] = decision.payload if decision.payload is not None else decision.message
        return results

    def _approval(self, decision: ResumeDecision) -> Any:
        """
        The approval verb for one gated tool call.

        A payload here is the tool call's replacement arguments. `_reject_unusable_override` has
        already refused any shape but an object, so this reads it straight.

        :param decision: The human's decision.
        :return: A `ToolApproved` or `ToolDenied` for the framework.
        """
        if decision.status == "approved":
            return ToolApproved(override_args=decision.payload) if decision.payload is not None else ToolApproved()
        if decision.status == "denied":
            return ToolDenied(message=decision.message) if decision.message else ToolDenied()
        return ToolDenied(message=self.CANCELLED_DECISION_MESSAGE)

    async def resume(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AgentReply:
        """
        Continues a paused run from the human's decisions.

        A prompt riding along is native here rather than encoded: supplying the deferred results is
        exactly what lifts the framework's own guard against a new prompt while tool calls are
        outstanding, so the prompt is passed as the run content unchanged.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        """
        self._reject_partial(decisions, record)
        self._reject_unusable_override(decisions, record)

        prompt = ""
        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(record.payload["messages"])

            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)
            kwargs = self._native_kwargs(
                options,
                message_history=history,
                deps=produced,
                deferred_tool_results=self._deferred_results(decisions, record),
            )
            result = await agent.agent.run(content or "", **kwargs)

            if fw_session is not None:
                fw_session.messages = to_jsonable_python(result.all_messages())

            self._store_framework_context(session, incoming, produced)
            PausedRunState.clear(session, record.id)

            if isinstance(result.output, DeferredToolRequests):
                return self._paused_reply(agent, session, result)

            structured = AgentReplyAny.from_output(result.output, prompt)
            if structured is not None:
                return structured
            return AgentReplyText(response="" if result.output is None else str(result.output), prompt=prompt)
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
        self._reject_while_a_decision_is_outstanding(session)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            prompt, content = self._process_requests(requests)

            if not content:
                return

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(fw_session.messages) if fw_session and fw_session.messages else None

            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)

            open_parts: dict[int, tuple[str, str]] = {}  # live index -> (kind, id); local, never on self
            carried: dict[str, str] = {}  # kind -> id when a stream continues across a part boundary
            run_result: Any = None

            kwargs = self._native_kwargs(self._stream_run_options(options), message_history=history, deps=produced)
            async with agent.agent.run_stream_events(content, **kwargs) as events:
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

            if run_result is not None and isinstance(run_result.output, DeferredToolRequests):
                paused = self._paused_reply(agent, session, run_result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
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

        The pause is read off the final `agent_run_result` rather than from a deferred event, so the
        streamed and non-streamed paths decide it the same way and cannot drift apart.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued run produces, ending in RunPaused if it pauses again.
        """
        self._reject_partial(decisions, record)
        self._reject_unusable_override(decisions, record)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            _, content = self._process_requests(requests)

            options = await agent.resolve_run_options(session, requests)
            fw_session = self._session(session)
            history = ModelMessagesTypeAdapter.validate_python(record.payload["messages"])

            incoming = self._load_framework_context(session)
            produced = copy.deepcopy(incoming)

            open_parts: dict[int, tuple[str, str]] = {}
            carried: dict[str, str] = {}
            run_result: Any = None

            kwargs = self._native_kwargs(
                self._stream_run_options(options),
                message_history=history,
                deps=produced,
                deferred_tool_results=self._deferred_results(decisions, record),
            )
            async with agent.agent.run_stream_events(content or "", **kwargs) as events:
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

            try:
                self._store_framework_context(session, incoming, produced)
            except Exception as e:
                self._log_framework_context_stream_failure(session, e)

            PausedRunState.clear(session, record.id)

            if run_result is not None and isinstance(run_result.output, DeferredToolRequests):
                paused = self._paused_reply(agent, session, run_result)
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)
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

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "user_prompt": "built from the AgentRequest list by the runner",
        "message_history": "the PydanticAISession stored on the Agent Kernel session",
        "deps": "populated from the session's framework_context; seed it with Session.set_framework_context()",
        "deferred_tool_results": "built from the human's decisions by the runner when a paused run is resumed",
    }

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
