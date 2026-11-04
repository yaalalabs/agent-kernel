from __future__ import annotations

import base64
import contextlib
import copy
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Callable, ClassVar, List, Mapping
from uuid import uuid4

from agent_framework import Agent, AgentResponse, AgentResponseUpdate, AgentSession, Content, Message
from agent_framework import tool as maf_tool

from ...core import Agent as BaseAgent
from ...core import Module, Runner, Runtime, Session, ToolBuilder, ToolContext
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

FRAMEWORK = "maf"

_log = logging.getLogger("ak.maf.runner")


class MAFSession:
    """
    Stores the MAF-specific session data: the serialized native `AgentSession` (`AgentSession.to_dict()`),
    kept as a plain dict so the AK session store can persist it.
    """

    def __init__(self) -> None:
        """Initialize session data with no stored native state."""
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
        """Initialize the runner under the MAF session key."""
        # Must match the session key: Session.get_framework_session() resolves it via the runner name.
        super().__init__(FRAMEWORK)

    @staticmethod
    def _session(session: Session) -> MAFSession:
        """
        Retrieves the MAFSession from the AgentKernel session, initializing it if not present.
        Callers handle a stateless run (no session) before reaching here.
        :param session: The AK session.
        :return: The MAF session data stored under the framework key.
        """
        stored: MAFSession | None = session.get(FRAMEWORK)
        if stored is None:
            stored = MAFSession()
            session.set(FRAMEWORK, stored)
        return stored

    @staticmethod
    def _attachment_content(data: str, mime_type: str | None, kind: str) -> Content:
        """
        Converts one image or file attachment into a MAF Content item.
        :param data: An HTTP, HTTPS, or S3 URL, a data URI, or raw base64 data.
        :param mime_type: The MIME type for URLs or raw base64 data; data URIs supply their own MIME type.
        :param kind: "image" or "file", used in error messages.
        :return: A URI Content item for URLs, otherwise a data Content item.
        :raises ValueError: If raw base64 data has no MIME type or the encoded data contains non-ASCII characters.
        :raises binascii.Error: If base64 decoding fails, for example because of incorrect padding.
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
        Unsupported request types, including AgentRequestAny, are ignored. The prompt joins text and attachment
        labels with newlines; the contents retain request order and carry the actual attachments.
        :param requests: The requests to process.
        :return: Tuple of (prompt, contents of the single user message sent to MAF).
        :raises ValueError: If an attachment has no data, raw base64 data has no MIME type, or encoded data is not ASCII.
        :raises binascii.Error: If an attachment cannot be base64-decoded.
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

    def _prepare_session(
        self, session: Session | None, options: Mapping[str, Any], state: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], AgentSession | None, dict | None]:
        """
        Restores the native MAF session and injects the framework context for one run.
        :param session: The AK session, or None for a stateless run.
        :param options: The run options resolved for this run.
        :param state: A serialized native session to restore instead of the stored one: a paused run's snapshot.
            An empty state starts a new native session.
        :return: Tuple of (native run kwargs, native session or None, framework context loaded this turn).
        :raises TypeError: If the stored framework context is not a dict.
        """
        if session is None:
            return self._native_kwargs(options), None, None

        if state is None:
            state = self._session(session).get_state()
        # Deep copy so restoring never mutates the stored snapshot: a failed resume must be retryable from it.
        native_session = AgentSession.from_dict(copy.deepcopy(state)) if state else AgentSession(session_id=session.id)

        # Tools reach the framework context as `FunctionInvocationContext.session.state["ak_context"]`.
        incoming = self._load_framework_context(session)
        native_session.state.pop("ak_context", None)
        if incoming is not None:
            # Deep copy so in-place tool mutations do not alter `incoming`.
            native_session.state["ak_context"] = copy.deepcopy(incoming)

        return self._native_kwargs(options, session=native_session), native_session, incoming

    def _finalize_session(
        self, session: Session | None, native_session: AgentSession | None, incoming: dict | None, record: PausedRun | None = None
    ) -> None:
        """
        Writes the native MAF session, then the framework context, back to the AK session after a successful run.

        The context is popped from the native state first: AK persists it as the framework context, so keeping it in
        the MAF snapshot would store it twice. The conversation is persisted first, as Pydantic AI persists its history
        first: the context write-back can fail (an unpicklable value a tool stored), and that failure must not also
        lose a turn the model already completed. A resumed run's record is cleared right after the conversation is
        stored and before the context: once the conversation holds the tool results, a retry from the record's
        pre-resume snapshot would run the approved tools a second time.
        :param session: The AK session, or None for a stateless run.
        :param native_session: The native session used for the run, or None.
        :param incoming: The framework context loaded this turn, or None.
        :param record: The paused run being resumed, or None for an ordinary turn.
        :raises TypeError: If the framework context cannot be pickled; the conversation is already stored.
        """
        if session is None or native_session is None:
            return
        produced = native_session.state.pop("ak_context", None)
        self._session(session).set_state(native_session.to_dict())
        if record is not None:
            PausedRunState.clear(session, record.id)
        self._store_framework_context(session, incoming, produced)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the MAF agent with the provided multi modal inputs.
        No supported input returns a text reply explaining that no valid content was found. Errors during request
        preparation, option resolution, native execution, or session finalization are converted to text error replies.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: The result of the agent's execution, or a paused reply when a tool needs approval.
        :raises ValueError: If this runner has an unanswered paused run in the session.
        """
        self._reject_while_a_decision_is_outstanding(session)

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
            return self._reply(agent, session, native_session, result, prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)
        finally:
            if context is not None:
                context.reset()

    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """
        Streams the MAF agent response as Agent Kernel stream events, ending in `RunPaused` when a tool needs approval.
        No supported input yields no events. Request preparation, option resolution, and native execution errors
        propagate during iteration; session finalization errors are suppressed after the native stream completes.
        :param agent: The MAF agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to the agent.
        :return: An async generator yielding StreamEvent objects.
        :raises ValueError: If this runner has an unanswered pause, attachment validation fails, or a new pause has no session.
        :raises TypeError: If the stored framework context is not a dict.
        :raises binascii.Error: If an attachment cannot be base64-decoded.
        """
        self._reject_while_a_decision_is_outstanding(session)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            _, inputs = self._process_requests(requests)

            if not inputs:
                return

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options)

            # aclosing: a client disconnect closes this generator, and the turn (with the provider stream) must close with it.
            async with contextlib.aclosing(
                self._stream_turn(agent, session, Message("user", inputs), kwargs, native_session, incoming, None)
            ) as turn:
                async for event in turn:
                    yield event
        finally:
            if context is not None:
                context.reset()

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — a tool declared with `approval_mode="always_require"` pauses the run, and the native session
            that holds the pending call serializes, so the decision can arrive later on any replica.
        """
        return True

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

        The native session is restored from the record's snapshot, not the stored one, so the pause stays
        resumable whatever the session does next; the decisions travel as one user message of approval responses.
        Preparation, native execution, and finalization errors become text error replies. A native execution failure
        leaves the paused record available for retry; once the conversation holding the outcome is stored, the record is
        cleared before the framework context is written, so a context write-back failure cannot make an approved tool run twice.
        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        :raises ValueError: If any pending approval is unanswered, a decision has a payload, or requests include a nonempty text prompt.
        """
        self._reject_unresumable(decisions, record, requests)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options, state=record.payload["session"])

            result = await agent.agent.run(self._approval_message(decisions, record), **kwargs)

            # Clears the record once the conversation holds the outcome; a failed native call above leaves it for a retry.
            self._finalize_session(session, native_session, incoming, record)
            return self._reply(agent, session, native_session, result, "")
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
        Restores the paused snapshot. Preparation and native execution errors propagate during iteration and leave the
        record for a retry; after the stream drains, the record is cleared once the conversation is stored, before the
        framework context, whose write-back errors are logged rather than raised.
        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued run produces, ending in RunPaused if it pauses again.
        :raises ValueError: If any pending approval is unanswered, a decision has a payload, or requests include a nonempty text prompt.
        :raises TypeError: If the stored framework context is not a dict.
        """
        self._reject_unresumable(decisions, record, requests)

        context: ToolContext | None = None
        try:
            context = ToolContext(Runtime.current(), agent, session, requests).set()
            options = await agent.resolve_run_options(session, requests)
            kwargs, native_session, incoming = self._prepare_session(session, options, state=record.payload["session"])

            turn = self._stream_turn(agent, session, self._approval_message(decisions, record), kwargs, native_session, incoming, record)
            async with contextlib.aclosing(turn) as events:
                async for event in events:
                    yield event
        finally:
            if context is not None:
                context.reset()

    async def _stream_turn(
        self,
        agent: Any,
        session: Session,
        message: Message,
        kwargs: dict[str, Any],
        native_session: AgentSession | None,
        incoming: dict | None,
        record: PausedRun | None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Runs one streamed native turn and maps it, shared by `stream()` and `resume_stream()` so both emit the same events.

        Text and reasoning streams are keyed by the update's native `message_id` (or a generated id when MAF supplies
        none); tool events are correlated by MAF's own `call_id`. `streams` / `open_calls` / `call_ids` are locals —
        the runner is shared across sessions. The pause is read off the final response, as `run()` reads it, so the
        streamed and non-streamed paths cannot drift apart.
        Native execution and event mapping errors propagate. Session finalization errors are logged rather than raised;
        after a normal drain a resumed record is cleared once the conversation is stored, and kept if storing it fails.
        :param agent: The agent being run.
        :param session: The AK session.
        :param message: The user message to send: the prompt, or the approval responses on a resume.
        :param kwargs: The native run kwargs built by `_prepare_session`.
        :param native_session: The native session used for the run, or None.
        :param incoming: The framework context loaded this turn, or None.
        :param record: The paused run being resumed, cleared after a normal drain; None for an ordinary turn.
        :return: An async generator yielding StreamEvent objects.
        """
        stream_result = await agent.agent.run(message, stream=True, **kwargs)

        fallback_id = uuid4().hex
        streams: dict[str, str] = {}  # native content type -> id of the open text/reasoning stream
        open_calls: dict[str, None] = {}  # insertion-ordered set of call ids awaiting a result
        call_ids: dict[Any, str] = {}  # tool_call_index -> call id; the None key holds the latest call

        try:
            async for update in stream_result:
                for event in self._map_update(update, fallback_id, streams, open_calls, call_ids):
                    yield event
            for event in self._close_streams(streams, open_calls):
                yield event
            final = await stream_result.get_final_response()
        finally:
            # Releases the provider stream when the turn is interrupted (an error, a disconnect, a StreamHalt);
            # MAF's close() is idempotent, so a normally drained stream is unaffected.
            await stream_result.close()

        # After a normal drain only — disconnect/error leaves the stored session, context and record intact.
        try:
            self._finalize_session(session, native_session, incoming, record)
        except Exception as e:
            self._log_framework_context_stream_failure(session, e)

        approvals = self._approval_requests(final)
        if approvals:
            paused = self._paused_reply(agent, session, native_session, approvals)
            yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)

    def _reply(self, agent: Any, session: Session | None, native_session: AgentSession | None, result: AgentResponse, prompt: str) -> AgentReply:
        """
        Maps a finished native run onto an AgentReply, shared by `run()` and `resume()` so a resumed turn answers in
        the same shapes. A pause is checked first: a run waiting on approval may still carry text produced on the way.
        :param agent: The agent that ran.
        :param session: The AK session, or None for a stateless run.
        :param native_session: The native session used for the run, or None.
        :param result: The native `AgentResponse`.
        :param prompt: The text prompt sent to the agent.
        :return: A paused reply, a structured reply, or a text reply.
        :raises ValueError: If the result requires approval but an AK or native session is missing.
        """
        approvals = self._approval_requests(result)
        if approvals:
            return self._paused_reply(agent, session, native_session, approvals)

        structured = AgentReplyAny.from_output(result.value, prompt)
        if structured is not None:
            return structured

        return AgentReplyText(response=result.text, prompt=prompt)

    @staticmethod
    def _approval_requests(result: AgentResponse) -> list[Content]:
        """
        :param result: The native `AgentResponse`.
        :return: The tool approvals the run is waiting on; empty when no function approvals are requested.
        """
        return [request for request in result.user_input_requests if request.type == "function_approval_request"]

    def _paused_reply(
        self, agent: Any, session: Session | None, native_session: AgentSession | None, approvals: list[Content]
    ) -> AgentPausedReplyAny:
        """
        Records a paused run and returns the reply that carries it back to the caller.

        Replaces rather than appends: MAF keeps one conversation per session, so an earlier pause of this runner
        could never be resumed. Scoped to this runner, since a pause another framework holds on the same session
        is a separate conversation and still answerable. The record carries the native session snapshot and the
        pending requests, so the native conversation can be restored on another replica.
        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param native_session: The native session holding the pending tool calls.
        :param approvals: The `function_approval_request` items MAF returned.
        :return: The paused reply, carrying the assigned run id.
        :raises ValueError: If the run has no session to record the pause in.
        """
        if session is None or native_session is None:
            raise ValueError("A Microsoft Agent Framework run paused for tool approval, but a pause needs a session to be recorded in.")

        interruptions = [self._interruption(request) for request in approvals]
        PausedRunState.clear_for_runner(session, self.name)
        record = PausedRunState.add(
            session,
            agent=agent.name,
            runner=self.name,
            interruptions=interruptions,
            payload={"session": native_session.to_dict(), "requests": {i.id: request.to_dict() for i, request in zip(interruptions, approvals)}},
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    @classmethod
    def _interruption(cls, request: Content) -> PausedInterruption:
        """
        Maps one `function_approval_request` onto an interruption, keyed by MAF's own request id.
        :param request: The pending approval request.
        :return: The interruption to carry back to the caller.
        :raises ValueError: If the request carries no id or function call.
        """
        call, request_id = request.function_call, request.id
        if call is None or request_id is None:
            # MAF builds every approval request with both, and skips one without them when resuming.
            raise ValueError(f"Microsoft Agent Framework returned an approval request without an id or function call: {request!r}")
        return PausedInterruption(
            id=request_id,
            kind="tool_call",
            tool_name=call.name,
            arguments=None if call.arguments is None else cls._as_text(call.arguments),
        )

    def _reject_while_a_decision_is_outstanding(self, session: Session | None) -> None:
        """
        Refuses an ordinary turn while this framework's pause is still unanswered.

        MAF does not refuse one: it drops the pending tool calls from the conversation and answers the new prompt,
        so the pause would be lost without anyone being told. This makes the turn fail saying why, and names the run
        to resume. Only this runner's records are consulted: another framework's pause on the same session is a
        separate conversation.
        :param session: The session whose paused runs to inspect, or None.
        :raises ValueError: If this runner holds an unanswered paused run in this session.
        """
        if session is None:
            return
        outstanding = next((record for record in PausedRunState.list(session) if record.runner == self.name), None)
        if outstanding is not None:
            raise ValueError(
                f"Microsoft Agent Framework cannot take a new prompt while run '{outstanding.id}' is waiting on a decision: "
                f"MAF would drop the pending tool calls. Answer it with a 'resume' block first, or start a new session."
            )

    @staticmethod
    def _reject_unresumable(decisions: list[ResumeDecision], record: PausedRun, requests: list[AgentRequest]) -> None:
        """
        Refuses what a MAF resume cannot carry, before the adapter's `try` opens, so the caller gets the reason rather
        than a generic reply.

        - A partial answer: MAF holds the approved calls back until every pending one is answered and re-asks for
          the rest, so a partial resume would run nothing while appearing to succeed.
        - A payload: a MAF approval is only approved or rejected, with no channel for replacement arguments.
        - A prompt beside the decisions: MAF places it between the tool calls and their results, an order model
          APIs reject.
        :param decisions: The human's decisions.
        :param record: The record Runtime validated.
        :param requests: The hook-processed request list.
        :raises ValueError: If the resume is partial, carries a payload, or carries a prompt.
        """
        answered = {decision.id for decision in decisions}
        missing = sorted(i.id for i in record.interruptions if i.id not in answered)
        if missing:
            raise ValueError(
                f"Microsoft Agent Framework needs every pending approval answered in one resume; {missing} were not answered. "
                f"Answer all of {sorted(i.id for i in record.interruptions)} together."
            )

        with_payload = sorted(decision.id for decision in decisions if decision.payload is not None)
        if with_payload:
            raise ValueError(
                f"The Microsoft Agent Framework adapter cannot deliver a structured answer: decision(s) {with_payload} carry a payload, "
                f"and a MAF approval is only approved or rejected. Model the question as a gated tool's arguments instead."
            )

        if any(isinstance(req, AgentRequestText) and req.prompt for req in requests):
            raise ValueError(
                "The Microsoft Agent Framework adapter cannot carry a prompt alongside a decision: MAF would place it between the "
                "tool calls and their results, which model APIs reject. Send the prompt as a separate turn once the run has resumed."
            )

    @staticmethod
    def _approval_message(decisions: list[ResumeDecision], record: PausedRun) -> Message:
        """
        Renders the decisions as the one user message MAF resumes from.

        `approved` approves; `denied` and `cancelled` both reject, since MAF has only those two verbs. MAF tells the
        model the call was rejected by the user; a decision's `message` has no channel and is not forwarded.
        :param decisions: The human's decisions, one per pending request (`_reject_unresumable` has checked).
        :param record: The record holding the pending requests, keyed by interruption id.
        :return: The message of approval responses.
        """
        pending = {interruption_id: Content.from_dict(request) for interruption_id, request in record.payload["requests"].items()}
        return Message("user", [pending[decision.id].to_function_approval_response(decision.status == "approved") for decision in decisions])

    def _map_update(
        self, update: AgentResponseUpdate, fallback_id: str, streams: dict[str, str], open_calls: dict[str, None], call_ids: dict[Any, str]
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
        native_id = update.message_id
        events: list[StreamEvent] = []
        for item in update.contents:
            item_type = item.type
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
        text = item.text
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
            events.append(ToolCallStart(tool_call_id=call_id, name=item.name or ""))
            open_calls[call_id] = None
        args = item.arguments
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
        call_id = item.call_id
        if not call_id:
            return []
        events: list[StreamEvent] = []
        if call_id in open_calls:
            del open_calls[call_id]
            events.append(ToolCallEnd(tool_call_id=call_id))
        events.append(ToolCallResult(tool_call_id=call_id, content=self._as_text(item.result)))
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
        index = (item.additional_properties or {}).get("tool_call_index")
        call_id = item.call_id
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

    def __init__(self, name: str, runner: Runner, agent: Agent):
        """
        Initializes a MAFAgent instance.
        Attaches configured system tools and appends system instructions to the supplied native agent.
        :param name: The name the agent is registered under.
        :param runner: The runner that executes the agent.
        :param agent: The native MAF agent.
        """
        super().__init__(name, runner)
        self._agent = agent
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
        return self.agent.description or self.agent.default_options.get("instructions") or ""

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
        :raises TypeError: If tool is not callable.
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
        Initializes a MAFModule instance and registers its agents in the current runtime.
        :param agents: List of MAF agents in the module.
        :param runner: Custom runner; when omitted, uses the configured tracer's MAF runner or an untraced MAFRunner.
        :raises ValueError: If a native agent's name is None.
        :raises Exception: If an agent name is already registered in the current runtime.
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
        :raises ValueError: If the native agent's name is None.
        """
        if agent.name is None:
            raise ValueError("MAF agents passed to MAFModule must have an explicit name= — AK registers agents by name immediately.")
        return MAFAgent(agent.name, self.runner, agent)

    def load(self, agents: list[Agent]) -> MAFModule:
        """
        Loads and registers the native MAF agents, replacing the current ones.
        Existing agents are unloaded first. If wrapping or registration fails, newly registered agents are unloaded
        and the error propagates.
        :param agents: List of native MAF agents.
        :return: This module.
        :raises ValueError: If a native agent's name is None.
        :raises Exception: If an agent name is already registered in the current runtime.
        """
        super().load(agents)
        return self


class MAFToolBuilder(ToolBuilder):
    """
    Tool builder for Microsoft Agent Framework.
    """

    @classmethod
    def bind(cls, funcs: list[Callable], **options: Any) -> list[Any]:
        """
        Bind generic tool functions to MAF ``@tool`` definitions.

        Keyword options are forwarded to MAF's ``tool()`` untouched and apply to every function in the call, so tools
        wanting different options are bound in separate calls. ``approval_mode="always_require"`` is the one that
        matters: it is this framework's gate for a tool needing a human verdict, which pauses the run.
        :param funcs: List of generic tool functions to bind.
        :param options: Keyword arguments passed to ``tool()``, e.g. ``approval_mode="always_require"``.
        :return: List of MAF tool definitions.
        :raises TypeError: If any item in funcs is not callable, or an option ``tool()`` does not take.
        """
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected a callable, got {type(func).__name__}")
            tools.append(maf_tool(func, **options))
        return tools
