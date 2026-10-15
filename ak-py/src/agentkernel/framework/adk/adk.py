from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import inspect
import json
import logging
import math
import time
from array import array
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, List, Literal, Mapping
from uuid import uuid4

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.events import Event, EventActions
from google.adk.flows.llm_flows.agent_transfer import _build_transfer_instructions
from google.adk.flows.llm_flows.contents import _present_other_agent_message
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, State
from google.adk.tools import BaseTool, FunctionTool, ToolContext, TransferToAgentTool
from google.genai import types
from pydantic import ValidationError

from agentkernel.core.model import (
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
    ResumeDecision,
)

from ...core import Agent as AKBaseAgent
from ...core import Module
from ...core import RealtimeRunner as BaseRealtimeRunner
from ...core import Runner as BaseRunner
from ...core import Runtime, Session, ToolBuilder
from ...core import ToolContext as AKToolContext
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
from ...core.paused_run import PausedRun, PausedRunState
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


PauseKind = Literal["tool_call", "confirmation"]
"""
The interruption kinds this adapter produces, narrower than `PausedInterruption.kind`.

ADK never asks for a value on its own: a `LongRunningFunctionTool` is answered with the tool's
result and `adk_request_confirmation` with a verdict, so `input_required` has no producer here.
"""


class _AdkStreamMapper:
    """
    Maps one drained ADK turn's events onto Agent Kernel stream events.

    A class rather than a function because the mapping is stateful: whether text is a delta of an open
    message or a whole one, and whether reasoning has been streamed, is only knowable from the events
    before it. The three values it carries were locals in `stream()`, which is why `resume_stream()`
    could not reuse that logic and grew a second copy — one that silently dropped reasoning. Both
    paths now hold one of these instead, so the envelope a client sees cannot differ by whether a
    human was involved.

    One instance per run: it is per-turn state, never shared across sessions.
    """

    def __init__(self, runner: "GoogleADKRunner") -> None:
        """
        :param runner: The runner whose `_event_text` and `_tool_events` helpers do the extraction.
        """
        self._runner = runner
        self._message_id: str | None = None
        self._reasoning_id: str | None = None
        self._reasoning_streamed = False

    def events(self, event: Event) -> list[StreamEvent]:
        """
        The Agent Kernel events one ADK event produces.

        :param event: One event from the ADK runner.
        :return: The mapped events, in order; empty when the event carries nothing a client sees.
        """
        out: list[StreamEvent] = []
        chunk, thinking = self._runner._event_text(event)
        partial = getattr(event, "partial", False)

        if partial and thinking:
            self._reasoning_streamed = True
            if self._reasoning_id is None:
                self._reasoning_id = uuid4().hex
                out.append(ReasoningStart(message_id=self._reasoning_id))
            out.append(ReasoningDelta(message_id=self._reasoning_id, content=thinking))
        elif thinking and not self._reasoning_streamed:
            whole_reasoning = uuid4().hex
            out.append(ReasoningStart(message_id=whole_reasoning))
            out.append(ReasoningDelta(message_id=whole_reasoning, content=thinking))
            out.append(ReasoningEnd(message_id=whole_reasoning))

        if chunk and self._reasoning_id is not None:
            out.append(ReasoningEnd(message_id=self._reasoning_id))
            self._reasoning_id = None

        if partial:
            if chunk:
                if self._message_id is None:
                    self._message_id = uuid4().hex
                    out.append(MessageStart(message_id=self._message_id))
                out.append(TextDelta(message_id=self._message_id, content=chunk))
        elif self._message_id is not None:
            out.append(MessageEnd(message_id=self._message_id))
            self._message_id = None
        elif chunk:
            whole = uuid4().hex
            out.append(MessageStart(message_id=whole))
            out.append(TextDelta(message_id=whole, content=chunk))
            out.append(MessageEnd(message_id=whole))

        tool_events = self._runner._tool_events(event)
        if tool_events and self._reasoning_id is not None:
            out.append(ReasoningEnd(message_id=self._reasoning_id))
            self._reasoning_id = None
        out.extend(tool_events)
        return out

    def close(self) -> list[StreamEvent]:
        """
        Closes whatever the drained turn left open.

        :return: The trailing boundary events, empty when nothing is open.
        """
        out: list[StreamEvent] = []
        # Reasoning first: a thought arriving after prose leaves both open, and the inner boundary
        # closes before the outer one. This is the order `stream()` has always emitted.
        if self._reasoning_id is not None:
            out.append(ReasoningEnd(message_id=self._reasoning_id))
            self._reasoning_id = None
        if self._message_id is not None:
            out.append(MessageEnd(message_id=self._message_id))
            self._message_id = None
        return out


@dataclass(frozen=True)
class _AdkTurn:
    """
    What one drained ADK turn produced.

    `pending` being non-empty is the pause: ADK signals it by ending the turn with the call still
    outstanding rather than by raising, so the absence of text is not enough to tell a pause from a
    tool-only turn.
    """

    text: str
    pending: list[tuple[Any, PauseKind]]
    invocation_id: str | None


class GoogleADKRunner(BaseRunner):
    RUNNER_CONSTRUCTOR_OPTIONS: ClassVar[frozenset[str]] = frozenset(
        {"plugins", "memory_service", "artifact_service", "credential_service", "plugin_close_timeout"}
    )
    """Run options routed to the per-run google.adk Runner(...) constructor; everything else goes to run_async."""

    def __init__(self):
        """
        Initializes a GoogleADKRunner instance.
        """
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.runner")
        self._streaming_mode_warned = False
        """Whether the stream-mode streaming_mode override was already logged for this runner."""

    @classmethod
    def _split_run_options(cls, options: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Splits the run options resolved for one run by destination.
        :param options: The run options resolved for this run.
        :return: (options for the per-run Runner constructor, options for run_async).
        """
        ctor = {k: v for k, v in options.items() if k in cls.RUNNER_CONSTRUCTOR_OPTIONS}
        run = {k: v for k, v in options.items() if k not in cls.RUNNER_CONSTRUCTOR_OPTIONS}
        return ctor, run

    def _stream_run_config(self, caller: RunConfig | None) -> RunConfig:
        """
        The RunConfig for a streamed run: the caller's, copied with streaming_mode forced to SSE, because the
        stream mapping depends on partial events. Logged once per runner when the caller explicitly set a different mode;
        a RunConfig that never set streaming_mode is not a choice being overridden.
        :param caller: The declared `run_config` run option, or None.
        :return: A RunConfig with streaming_mode=SSE; the caller's object is never mutated.
        """
        if caller is None:
            return RunConfig(streaming_mode=StreamingMode.SSE)
        explicitly_set = "streaming_mode" in caller.model_fields_set
        if explicitly_set and caller.streaming_mode is not StreamingMode.SSE and not self._streaming_mode_warned:
            self._log.warning(
                f"ADK RunConfig streaming_mode {caller.streaming_mode} overridden to SSE for Agent Kernel stream mode; "
                "the stream mapping depends on partial events"
            )
            self._streaming_mode_warned = True
        return caller.model_copy(update={"streaming_mode": StreamingMode.SSE})

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
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        injected: dict | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[str, Runner, AKToolContext, GoogleADKSession]:
        """
        Setup ADK session and tool context.
        :param agent: The ADK agent.
        :param session: The AgentKernel session.
        :param requests: The requests.
        :param injected: The per-run framework context to seed into the ADK session state, or None.
        :param options: The run options resolved for this run; its constructor keys reach the per-run Runner.
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

        # Resolved constructor options (plugins, services) first; the keys AK owns are written last.
        ctor_options, _ = self._split_run_options(options or {})
        # `plugins` belongs to the App, not the Runner: ADK refuses both at once ("When app is provided,
        # plugins should not be provided and should be provided in the app instead"), and this adapter
        # always provides an App because resumability lives there.
        plugins = ctor_options.pop("plugins", None)
        app = App(
            name=app_name,
            root_agent=agent.agent,
            resumability_config=ResumabilityConfig(is_resumable=True),
            **({"plugins": plugins} if plugins is not None else {}),
        )
        runner = Runner(**self._native_kwargs(ctor_options, app=app, app_name=app_name, session_service=adk_session.session_service))
        return user_id, runner, ctx, adk_session

    def _text_reply(self, agent: Any, text: str, prompt: str = "") -> AgentReply:
        """
        Maps a finished turn's text onto a reply, honouring the agent's declared `output_schema`.

        Shared by `run` and `resume` so a structured-output agent answers the same way either side of
        a pause. Returning text from one and parsed content from the other would make the reply type
        depend on whether a human was involved, which no client should have to branch on.

        :param agent: The agent that produced the text, read for its `output_schema`.
        :param text: The turn's text.
        :param prompt: The prompt this answers, carried on the reply; empty on a resume, which has none.
        :return: `AgentReplyAny` when the text parses against the schema, `AgentReplyText` otherwise.
        """
        output_schema = getattr(agent.agent, "output_schema", None)
        if output_schema is not None:
            try:
                parsed = output_schema.model_validate_json(text)
                return AgentReplyAny(content=parsed.model_dump(mode="json"), prompt=prompt)
            except ValidationError:
                self._log.warning(f"Agent '{agent.name}' has output_schema set but reply is not valid JSON for it; returning text")
        return AgentReplyText(response=text, prompt=prompt)

    @staticmethod
    def _pending_calls(event: Event) -> list[tuple[Any, PauseKind]]:
        """
        The calls on one event that are waiting for a human, with the kind each one is.

        Two shapes mean "waiting": a `function_call` whose id ADK listed in `long_running_tool_ids`,
        and a call to `adk_request_confirmation`, which ADK synthesises for a tool declared with
        `require_confirmation`. The second is a confirmation rather than a tool call because the
        human is being asked to bless a call, not to supply one.

        :param event: One event from the runner.
        :return: (FunctionCall, kind) for every call on the event that needs a human.
        """
        long_running = getattr(event, "long_running_tool_ids", None) or set()
        found: list[tuple[Any, PauseKind]] = []
        for part in (event.content.parts if event.content else None) or []:
            call = getattr(part, "function_call", None)
            if call is None:
                continue
            if call.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
                found.append((call, "confirmation"))
            elif call.id in long_running:
                found.append((call, "tool_call"))
        return found

    @staticmethod
    async def get_response(
        runner: Runner, user_id: str, session_id: str, parts: list[types.Part], run_options: Mapping[str, Any] | None = None
    ) -> "_AdkTurn":
        """
        Send a message to the agent and drain its events into one turn.

        Returns the whole turn rather than only its text because a run that stops for a human
        produces no final response — the pending calls are the outcome, and reading the text alone
        is what made a pause look like an empty answer.

        :param runner: The Google ADK Runner to use for the agent.
        :param user_id: The user ID to use for the agent.
        :param session_id: The session ID to use for the agent.
        :param parts: The message parts to send to the agent.
        :param run_options: Declared run options for run_async (e.g. `run_config`); the keys AK owns are written last.
        :return: The turn's final text, anything awaiting a human, and the invocation to resume.
        """
        new_message = types.Content(role="user", parts=parts)
        response_text = ""
        pending: list[tuple[Any, PauseKind]] = []
        invocation_id: str | None = None
        kwargs = BaseRunner._native_kwargs(run_options or {}, user_id=user_id, session_id=session_id, new_message=new_message)

        if hasattr(runner, "run_async"):
            # Drain the stream instead of breaking early: stopping early cancels ADK's still-running root agent
            # task, and with sub-agents the last final response is the one to return.
            async for event in runner.run_async(**kwargs):
                invocation_id = getattr(event, "invocation_id", None) or invocation_id
                pending.extend(GoogleADKRunner._pending_calls(event))
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
        else:
            for event in runner.run(**kwargs):
                invocation_id = getattr(event, "invocation_id", None) or invocation_id
                pending.extend(GoogleADKRunner._pending_calls(event))
                if event.is_final_response() and event.content and event.content.parts:
                    text_parts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(text_parts) if text_parts else ""
                    break
        return _AdkTurn(text=response_text, pending=pending, invocation_id=invocation_id)

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

            # Resolved once per run: the static options with a declared factory's result merged over them.
            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming, options)
            _, run_options = self._split_run_options(options)
            with ctx:
                turn = await self.get_response(runner=runner, session_id=session.id, parts=parts, user_id=user_id, run_options=run_options)

            # Write back the full ADK state, so keys a tool added during the run also round-trip. Done after
            # the run, so a framework error leaves the stored context intact.
            if incoming is not None:
                produced = await adk_session.get_state()
                self._store_framework_context(session, incoming, produced)

            if turn.pending:
                return self._paused_reply(agent, session, turn)

            return self._text_reply(agent, turn.text, prompt)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e), prompt=prompt)

    @property
    def supports_pause(self) -> bool:
        """
        :return: True — verified at google-adk 2.8.0, on both the streamed and non-streamed paths.
        """
        return True

    def _paused_reply(self, agent: Any, session: Session, turn: "_AdkTurn") -> AgentPausedReplyAny:
        """
        Records a paused run and returns the reply that carries it back to the caller.

        Replaces rather than appends: ADK keeps one conversation per session in its session service,
        and resuming addresses one `invocation_id`, so an earlier ADK record could never be
        answered. Scoped to this runner — a pause another framework holds on the same session is
        independent and stays.

        The `invocation_id` is the whole payload — the conversation itself already lives in the ADK
        session inside `GoogleADKSession`, which the AK session persists.

        One call can reach a turn more than once. A drained turn is many events, and an outstanding
        long-running call is re-surfaced on each round the model takes while it waits, so collecting
        them produces repeats rather than distinct questions. Carried through, the repeat fails
        `PausedRunState.add`'s uniqueness check and the pause is lost to an error reply, which is a
        confusing way to say "the model asked twice". Deduplicated here because this is the one place
        pending calls become interruptions, so every path — run, stream and both resumes — is covered.

        :param agent: The agent that paused.
        :param session: The session the record is written to.
        :param turn: The drained turn carrying the pending calls and the invocation to resume.
        :return: The paused reply, carrying the assigned run id.
        """
        PausedRunState.clear_for_runner(session, self.name)

        interruptions = []
        seen: set[str] = set()
        for call, kind in turn.pending:
            if call.id in seen:
                continue
            seen.add(call.id)
            try:
                arguments = json.dumps(dict(call.args or {}), default=str)
            except Exception:
                arguments = None
            interruptions.append(PausedInterruption(id=call.id, kind=kind, tool_name=call.name, arguments=arguments))

        record = PausedRunState.add(
            session,
            agent=agent.name,
            runner=self.name,
            interruptions=interruptions,
            payload={"invocation_id": turn.invocation_id},
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    @staticmethod
    def _reject_prompt_alongside(requests: list[AgentRequest]) -> None:
        """
        Refuses a prompt riding along with a decision, before the adapter's `try` opens.

        Established by test at google-adk 2.8.0, not assumed: a `Content` carrying both a
        `function_response` and a text part is rejected by ADK itself with *"Message cannot contain
        both function responses and text. Function responses resume an existing invocation while
        text starts a new one."* Agent Kernel pre-empts it so the reason reaches the caller rather
        than being flattened by the `except Exception` below.

        :param requests: The hook-processed request list.
        :raises ValueError: If any text request carries a prompt.
        """
        if any(isinstance(req, AgentRequestText) and req.prompt for req in requests):
            raise ValueError(
                "The Google ADK adapter cannot carry a prompt alongside a decision: ADK rejects a message holding both "
                "a function response and text, because a function response resumes an invocation while text starts a new one. "
                "Send the prompt as a separate turn once the run has resumed."
            )

    @staticmethod
    def _reject_payload_on_a_confirmation(decisions: list[ResumeDecision], record: PausedRun) -> None:
        """
        Refuses a structured answer on a confirmation, before the adapter's `try` opens.

        ADK's `ToolConfirmation` carries a boolean and a hint, and nothing else: it consumes the
        response and reissues the original call unchanged, so a payload never reaches the tool.
        Verified by running it — an approval carrying different arguments ran the tool with its
        original ones. Refused rather than dropped, so the human is told instead of being shown a
        confident answer computed from arguments they thought they had replaced.

        A long-running tool is unaffected: there the payload *is* the tool's return value.

        :param decisions: The human's decisions.
        :param record: The record naming which interruption is which kind.
        :raises ValueError: If a decision answering a confirmation carries a payload.
        """
        kinds = {i.id: i.kind for i in record.interruptions}
        offenders = sorted(d.id for d in decisions if kinds.get(d.id) == "confirmation" and d.payload is not None)
        if offenders:
            raise ValueError(
                f"The Google ADK adapter cannot deliver a structured answer to a confirmation: decision(s) {offenders} carry a payload, "
                f"and ADK's ToolConfirmation holds only a verdict. Model the question as a LongRunningFunctionTool, whose result is the "
                f"human's answer, or have the model propose the value in the tool arguments for the human to approve."
            )

    def _decision_parts(self, decisions: list[ResumeDecision], record: PausedRun) -> list[types.Part]:
        """
        Renders the decisions as the function responses ADK resumes on.

        The two kinds answer differently. A long-running tool is waiting for a **result**, so the
        human's payload or message is handed back as the tool's return. A confirmation is waiting
        for a verdict, so it takes ADK's own `{"confirmed": ...}` shape.

        The `hint` on a confirmation is best-effort. ADK consumes the confirmation response and
        writes its own function response for the original call, so the wording does not reach the
        model: **on this adapter `cancelled` is indistinguishable from `denied`**, unlike every
        other pausing adapter. Measured, not assumed. It is still sent, because ADK owns that
        response shape and may start surfacing it.

        :param decisions: The human's decisions.
        :param record: The record naming which interruption is which kind.
        :return: One function-response part per decision.
        """
        pending = {i.id: i for i in record.interruptions}
        parts: list[types.Part] = []
        for decision in decisions:
            interruption = pending.get(decision.id)
            name = interruption.tool_name if interruption else ""
            if interruption is not None and interruption.kind == "confirmation":
                response: Any = {"confirmed": decision.status == "approved"}
                if decision.status == "cancelled":
                    response["hint"] = self.CANCELLED_DECISION_MESSAGE
                elif decision.message:
                    response["hint"] = decision.message
            else:
                answer = decision.payload if decision.payload is not None else decision.message
                response = {"result": answer if answer is not None else decision.status}
            parts.append(types.Part(function_response=types.FunctionResponse(id=decision.id, name=name, response=response)))
        return parts

    async def resume(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AgentReply:
        """
        Continues a paused ADK invocation from the human's decisions.

        ADK re-runs the tools of the resumed invocation, so a tool may execute more than once — its
        own documented behaviour, which the adapter docs pass through verbatim rather than hiding.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The continued run's reply, which may itself be paused again.
        """
        self._reject_prompt_alongside(requests)
        self._reject_payload_on_a_confirmation(decisions, record)

        try:
            options = await agent.resolve_run_options(session, requests)
            incoming = self._load_framework_context(session)
            user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming, options)
            _, run_options = self._split_run_options(options)
            invocation_id = record.payload.get("invocation_id") if isinstance(record.payload, dict) else None

            with ctx:
                turn = await self.get_response(
                    runner=runner,
                    session_id=session.id,
                    parts=self._decision_parts(decisions, record),
                    user_id=user_id,
                    run_options=self._native_kwargs(run_options, invocation_id=invocation_id) if invocation_id else run_options,
                )

            if incoming is not None:
                produced = await adk_session.get_state()
                self._store_framework_context(session, incoming, produced)

            PausedRunState.clear(session, record.id)

            if turn.pending:
                return self._paused_reply(agent, session, turn)
            return self._text_reply(agent, turn.text)
        except Exception as e:
            return AgentReplyText(response=user_facing_error_message(e))

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

        # Resolved once per run: the static options with a declared factory's result merged over them.
        options = await agent.resolve_run_options(session, requests)
        incoming = self._load_framework_context(session)
        user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming, options)
        new_message = types.Content(role="user", parts=parts)
        _, run_options = self._split_run_options(options)
        kwargs = self._native_kwargs(
            run_options,
            user_id=user_id,
            session_id=session.id,
            new_message=new_message,
            run_config=self._stream_run_config(run_options.get("run_config")),
        )

        if hasattr(runner, "run_async"):
            with ctx:
                mapper = _AdkStreamMapper(self)  # per-run state; the runner is shared across sessions
                pending: list[tuple[Any, PauseKind]] = []
                invocation_id: str | None = None
                async for event in runner.run_async(**kwargs):
                    invocation_id = getattr(event, "invocation_id", None) or invocation_id
                    pending.extend(self._pending_calls(event))
                    for mapped in mapper.events(event):
                        yield mapped

                for closing in mapper.close():
                    yield closing

                # After a normal drain only — disconnect/error leaves stored context intact.
                if incoming is not None:
                    try:
                        produced = await adk_session.get_state()
                        self._store_framework_context(session, incoming, produced)
                    except Exception as e:
                        self._log_framework_context_stream_failure(session, e)

                if pending:
                    paused = self._paused_reply(agent, session, _AdkTurn(text="", pending=pending, invocation_id=invocation_id))
                    yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)

    async def resume_stream(
        self,
        agent: Any,
        session: Session,
        requests: list[AgentRequest],
        decisions: list[ResumeDecision],
        record: PausedRun,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Streaming counterpart of `resume()`.

        Verified against google-adk 2.8.0 rather than assumed: a streamed run does pause on a
        long-running tool and does resume from its `invocation_id`, and the event carrying the
        pending call is non-partial — so the id a client reads off the stream is one ADK persisted.

        :param agent: The agent that paused.
        :param session: The session holding the record.
        :param requests: The hook-processed request list, carrying the resume request.
        :param decisions: One per interruption being answered.
        :param record: The record Runtime validated.
        :return: The events the continued run produces, ending in RunPaused if it pauses again.
        """
        self._reject_prompt_alongside(requests)
        self._reject_payload_on_a_confirmation(decisions, record)

        options = await agent.resolve_run_options(session, requests)
        incoming = self._load_framework_context(session)
        user_id, runner, ctx, adk_session = await self._setup_session_context(agent, session, requests, incoming, options)
        _, run_options = self._split_run_options(options)
        invocation_id = record.payload.get("invocation_id") if isinstance(record.payload, dict) else None
        if invocation_id:
            run_options = self._native_kwargs(run_options, invocation_id=invocation_id)

        kwargs = self._native_kwargs(
            run_options,
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=self._decision_parts(decisions, record)),
            run_config=self._stream_run_config(run_options.get("run_config")),
        )

        with ctx:
            mapper = _AdkStreamMapper(self)  # the same envelope an ordinary stream produces, reasoning included
            pending: list[tuple[Any, PauseKind]] = []
            resumed_invocation: str | None = None
            async for event in runner.run_async(**kwargs):
                resumed_invocation = getattr(event, "invocation_id", None) or resumed_invocation
                pending.extend(self._pending_calls(event))
                for mapped in mapper.events(event):
                    yield mapped

            for closing in mapper.close():
                yield closing

            if incoming is not None:
                try:
                    produced = await adk_session.get_state()
                    self._store_framework_context(session, incoming, produced)
                except Exception as e:
                    self._log_framework_context_stream_failure(session, e)

            PausedRunState.clear(session, record.id)

            if pending:
                paused = self._paused_reply(agent, session, _AdkTurn(text="", pending=pending, invocation_id=resumed_invocation))
                yield RunPaused(run_id=paused.run_id, agent=agent.name, interruptions=paused.interruptions)

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


class GoogleADKRealtimeRunner(BaseRealtimeRunner):
    """Drives a persistent Gemini Live (BidiGenerateContent) socket behind the realtime pool.

    Mirrors ``OpenAIRealtimeRunner``: the pool calls :meth:`connect` once per session and then
    pushes audio/text through :meth:`append_audio` / :meth:`send_text`. Model events are reported
    back through the callback the pool supplied, so the pool keeps owning queue emission and this
    class never imports pipeline types.

    Gemini Live's realtime input is 16 kHz PCM16 mono (the edge carries 24 kHz), so
    ``input_sample_rate`` is set to 16 kHz and the pool resamples before :meth:`append_audio`.

    The agent's native transfers work as on an ADK live run. An agent with transfer targets (its
    sub-agents, its parent and its peers, as ADK allows them) is offered ADK's own
    ``transfer_to_agent`` tool and ADK's transfer instructions. The tool runs like any other; a tool
    call that leaves ``tool_context.actions.transfer_to_agent`` set moves the conversation to that
    agent. A Live session's instructions and tools are fixed when it opens, so, as ADK does, the
    runner then closes the socket and opens one configured for the new agent, seeded with the
    conversation so far: what was said, as text, and every tool call with its result. Each agent's
    turns are presented as ADK presents them (``[billing] said: ...``, on the user's side), so the
    new agent can tell what a teammate said, or asked it, from what it said itself. The caller hears
    a short gap while it connects; each agent speaks with its own model and, when its
    ``generate_content_config`` sets one, its own voice.

    The call's own Live settings come from the ADK ``RunConfig`` its starting agent declares as a run option
    (``Module.run_options(agent, run_config=RunConfig(...))``), the same option a non-live run reads: its
    ``realtime_input_config`` (how the caller's turns are detected) and ``input_audio_transcription`` /
    ``output_audio_transcription`` (such as the languages to expect), for every socket of the call.

    A tool call runs between the calling agent's ``before_tool_callback``, ``on_tool_error_callback``
    and ``after_tool_callback``, as on an ADK run, ``transfer_to_agent`` included: a before-callback
    that answers in the tool's place stops a transfer. ADK plugins do not run, since a Live socket
    has no ADK ``Runner`` to hold them.

    A socket that drops, or stalls, is replaced without leaving the agent that had the call: the runner reconnects
    that agent, seeded with the conversation and told the line dropped (``RECONNECTED_NOTE``, in that seed only),
    up to ``RECONNECT_ATTEMPTS`` times, waiting ``RECONNECT_DELAYS_SECONDS`` between attempts, and reports
    ``reconnected``; only when every attempt fails, or reconnected sockets keep being lost again within
    ``QUICK_DROP_SECONDS``, is it reported as an ``error``. The server closing a connection at its time limit is
    recovered the same way. A stall is no progress from the model for ``STALL_SECONDS`` after it was given something
    to answer (a tool result, text, a seeded turn) or in the middle of a response (a dead socket can take the
    websocket keepalive about 40 seconds to notice). A turn the caller speaks and the model never answers is not
    detected: Gemini Live does not signal the end of the caller's speech. While no socket is open (a reconnect, a
    transfer), what the caller says is held, its latest ``HOLD_AUDIO_SECONDS``, and sent to the next socket, as is
    any text sent meanwhile; a tool result that arrives for a lost socket is kept in the history.

    The caller starting a turn is reported as ``speech_started``, on the first transcription of
    their speech while the model is silent, and each later transcription as ``speech_heard``, so
    the pool can tell a quiet call from a busy one, and a long answer from silence. Gemini Live
    does not signal the end of the caller's speech, so ``speech_stopped`` is not reported. The
    caller's words in a turn are reported as ``caller_transcript`` when the turn ends (the model
    finishes, calls a tool, or text is sent in), for the agent's realtime hooks.
    """

    input_sample_rate = 16000
    # How long a transfer may take to open the new agent's Live socket before the connection is failed.
    TRANSFER_CONNECT_TIMEOUT_SECONDS: float = 15.0
    # Recovering a socket that dropped or stalled: attempts, the wait before each, and how long each may take.
    RECONNECT_ATTEMPTS: int = 3
    RECONNECT_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
    RECONNECT_TIMEOUT_SECONDS: float = 10.0
    # A reconnected socket lost again this soon counts as a failed reconnect, not a fresh drop: after
    # RECONNECT_ATTEMPTS of those in a row the runner gives up. A service that accepts a connection and then closes it
    # (out of quota, failing) would otherwise be reconnected forever, the conversation resent each time.
    QUICK_DROP_SECONDS: float = 20.0
    # A socket that answers nothing this long after it was given something to answer is taken for dead,
    # checked this often.
    STALL_SECONDS: float = 15.0
    STALL_CHECK_SECONDS: float = 1.0
    # While no socket is open, the latest this many seconds of the caller's audio are held for the next one.
    HOLD_AUDIO_SECONDS: float = 5.0
    # A tool still running when its socket is lost is waited for this long before the new socket is seeded, so the
    # seed has its call and result and the model does not make the call again.
    LOST_TOOL_WAIT_SECONDS: float = 2.0
    # Added to the conversation a reconnected socket is seeded with, so the agent can tell the caller; "" adds nothing.
    # The first when the caller was speaking as the line dropped, or said something while it was down; the second
    # when they were silent throughout, so they are not asked to repeat what they never said.
    RECONNECTED_NOTE: str = (
        "[The call's connection dropped for about {seconds} seconds and is back. What the caller said meanwhile may "
        "not have been heard: tell them in one short sentence that you lost them for a moment, and ask them to "
        "repeat what they last said.]"
    )
    RECONNECTED_QUIET_NOTE: str = (
        "[The call's connection dropped for about {seconds} seconds and is back; the caller did not speak meanwhile. "
        "Carry on where you were without asking them to repeat anything; if you were cut off mid-sentence, finish "
        "your point in one sentence.]"
    )
    # Held audio louder than this (the RMS of 16-bit samples, about -36 dBFS) in any chunk is taken for speech.
    SPEECH_LEVEL: int = 500

    @dataclass
    class _ToolBatch:
        """The function calls of one Gemini Live ``tool_call`` message and their results so far.

        Answered together, as ADK answers a model's parallel calls: the responses go back as one, or,
        when one of the calls asks for a transfer, into the history the new agent's socket is seeded
        with.
        """

        calls: list[Any]
        results: dict[str, str] = field(default_factory=dict)

    @dataclass
    class _Said:
        """One entry of the conversation history, and who it came from: ``"user"`` for the caller, else an agent's name."""

        author: str
        content: types.Content

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.realtime")
        self._callback: Callable | None = None
        self._agent = None
        # The ADK RunConfig the call's starting agent declares (its ``run_config`` run option), or None.
        self._run_config: RunConfig | None = None
        # The ADK session tools run in, owned by this connection like the socket: ADK builds a
        # tool's ToolContext from a session and its service, and neither outlives the connection.
        self._tool_session_service: InMemorySessionService | None = None
        self._tool_session = None
        self._connection = None
        # Set only once the socket is open, so a socket that never opened is never closed.
        self._cm = None
        self._client = None
        self._listen_task: asyncio.Task | None = None
        # Per-turn barge-in state; reset at each turn_complete.
        self._interrupted_this_turn = False
        self._model_speaking = False
        # Whether the caller's current turn has been reported (``speech_started`` or ``interrupt``);
        # reset when the model answers, so the caller's next turn is reported once.
        self._caller_turn_reported = False
        # Each dispatched call's batch, the calls of its tool_call message. Holds only the open
        # socket's calls: a result for a call a transfer has closed the socket of is dropped.
        self._batches: dict[str, GoogleADKRealtimeRunner._ToolBatch] = {}
        # The batches a lost socket was still owed results for, by call id, with the agent that made them: their
        # results are kept in the history when they arrive, though the socket that asked is gone.
        self._lost_batches: dict[str, tuple[GoogleADKRealtimeRunner._ToolBatch, str]] = {}
        # True once disconnect() runs; the listen loop suppresses its error callback then so a
        # normal shutdown does not surface as a model-socket failure.
        self._closing = False
        # The ADK agent answering: the connected agent, then whichever agent a transfer moved to.
        self._active: Any = None
        # The agent that made each dispatched tool call: the tool runs as that agent.
        self._callers: dict[str, Any] = {}
        # The agent each tool call asked to transfer to, by call id; performed once every call of its
        # tool_call message has a result.
        self._transfers: dict[str, Any] = {}
        # The conversation so far, to seed the socket a transfer opens: what was said, as text, and
        # every tool call with its result, each with who said or made it, as ADK's session records
        # them as events (audio aside). And the current turn's transcribed words, not yet added to it.
        self._history: list[GoogleADKRealtimeRunner._Said] = []
        self._user_words: list[str] = []
        self._model_words: list[str] = []
        # Recovery: what the caller said and what was sent while no socket was open, the task replacing a
        # lost socket, the task watching for a stalled one, when the server last sent anything, and since
        # when it owes an answer (to a tool result or text), all in time.monotonic().
        self._held_audio: list[bytes] = []
        self._held_text: list[str] = []
        self._recovery: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._last_message_at: float | None = None
        self._owed_since: float | None = None
        # When the socket was last reconnected, and how many reconnected sockets in a row were lost again soon after.
        self._reconnected_at: float | None = None
        self._quick_drops = 0
        # For the first-audio log: when the caller's words were last transcribed, and when the model was last
        # given something to answer (a tool result, text), until its next turn starts speaking.
        self._caller_words_at: float | None = None
        self._given_at: float | None = None

    @staticmethod
    def _live_model(sdk_agent: Any) -> str:
        """The Gemini Live model an ADK agent runs on: its own, or its nearest ancestor's, as ADK resolves it.

        Deliberately no adapter-level default: the model is the agent's choice, and a silent
        fallback would run a different model than the one the caller declared.
        """
        node = sdk_agent
        while node is not None:
            model = getattr(node, "model", None)
            name = model if isinstance(model, str) else getattr(model, "model", None)
            if isinstance(name, str) and name:
                return name
            node = getattr(node, "parent_agent", None)
        raise ValueError(f"Agent '{getattr(sdk_agent, 'name', '?')}' must define a Gemini Live model to run in REALTIME mode")

    @staticmethod
    def _instruction(sdk_agent: Any) -> str | None:
        instruction = getattr(sdk_agent, "instruction", None)
        if callable(instruction):
            # An InstructionProvider is resolved by ADK's own Runner from a ReadonlyContext; this
            # runner talks to Gemini Live directly, so it cannot resolve one faithfully.
            raise ValueError(f"Agent '{getattr(sdk_agent, 'name', '?')}' must define its instruction as a string to run in REALTIME mode")
        return instruction

    @staticmethod
    def _transfer_targets(sdk_agent: Any) -> list[Any]:
        """The agents ``sdk_agent`` may transfer to, by ADK's rules.

        Its sub-agents, its parent unless ``disallow_transfer_to_parent``, and its peers unless
        ``disallow_transfer_to_peers``; only LLM agents transfer, and a sub-agent in ``single_turn``
        or ``task`` mode is called rather than transferred to.
        """
        if not hasattr(sdk_agent, "disallow_transfer_to_parent"):
            return []

        def transferable(agent: Any) -> bool:
            return getattr(agent, "mode", None) not in ("single_turn", "task")

        targets = [agent for agent in getattr(sdk_agent, "sub_agents", None) or [] if transferable(agent)]
        parent = getattr(sdk_agent, "parent_agent", None)
        if parent is None or not hasattr(parent, "disallow_transfer_to_parent"):
            return targets
        if not sdk_agent.disallow_transfer_to_parent:
            targets.append(parent)
        if not sdk_agent.disallow_transfer_to_peers:
            targets.extend(peer for peer in parent.sub_agents if peer is not sdk_agent and transferable(peer))
        return targets

    @staticmethod
    def _transfer_instruction(sdk_agent: Any, targets: list[Any]) -> str:
        """The transfer instructions ADK adds to ``sdk_agent``'s system instruction, from ADK's own builder.

        So the wording, and which agents get none (one in ``task`` or ``single_turn`` mode), follow ADK.
        """
        return _build_transfer_instructions("transfer_to_agent", sdk_agent, targets)

    @staticmethod
    def _is_gemini_3_live(model: str) -> bool:
        """Whether ``model`` is a Gemini 3.x Live model, by ADK's test."""
        name = model.rsplit("/", 1)[-1]
        return name.startswith("gemini-3.") and "-live" in name and "translate" not in name

    def _connect_config(self, sdk_agent: Any, seeded: bool = False) -> types.LiveConnectConfig:
        """Build the Live session config from the ADK agent's instruction, tools and voice, and the call's ``RunConfig``.

        Only what is declared is sent; everything else (turn detection, thinking) is left to the Live
        API's own defaults. The call's ``RunConfig`` sets turn detection (``realtime_input_config``) and
        the transcription of both sides; transcription is always on, since the runner depends on it. An
        agent with transfer targets also gets ADK's transfer instructions and ``transfer_to_agent`` tool.

        :param sdk_agent: The ADK agent the session is for.
        :param seeded: The socket is seeded with prior conversation (after a transfer); the server
            is told so, as ADK tells it, so it does not answer the replayed turns again.
        """
        instruction = self._instruction(sdk_agent)
        targets = self._transfer_targets(sdk_agent)
        if targets:
            instruction = f"{instruction or ''}\n{self._transfer_instruction(sdk_agent, targets)}".strip()

        declarations = []
        for tool in self._live_tools(sdk_agent, warn=True).values():
            try:
                # ADK exposes a tool's FunctionDeclaration only through this protected method; it is
                # what ADK's own flows send to the model, so the Live session sees the same schema.
                declaration = tool._get_declaration()
            except Exception as e:
                self._log.warning(f"Could not build a Live declaration for tool {getattr(tool, 'name', '?')}: {e!r}")
                declaration = None
            if declaration is not None:
                declarations.append(declaration)

        run_config = self._run_config
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=instruction)]) if instruction else None,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            speech_config=getattr(getattr(sdk_agent, "generate_content_config", None), "speech_config", None),
            # Input transcription drives early barge-in (``interim_input_transcription``) and the
            # history a transfer replays; output transcription is the transcript the edge publishes.
            input_audio_transcription=(run_config and run_config.input_audio_transcription) or types.AudioTranscriptionConfig(),
            output_audio_transcription=(run_config and run_config.output_audio_transcription) or types.AudioTranscriptionConfig(),
            realtime_input_config=run_config.realtime_input_config if run_config else None,
        )
        # Older google-genai releases predate HistoryConfig.
        if seeded and hasattr(types, "HistoryConfig"):
            config.history_config = types.HistoryConfig(initial_history_in_client_content=True)
        return config

    def _live_tools(self, sdk_agent: Any, warn: bool = False) -> dict[str, BaseTool]:
        """The ADK agent's tools the Live session can call, by name.

        ADK accepts a plain function in ``tools`` and wraps it in a ``FunctionTool`` itself when it
        runs the agent; this runner does the same, so a plain function works in REALTIME mode too.
        A toolset (e.g. MCP) is resolved by ADK's own Runner from a run context, which a Live
        socket does not have, so it is skipped. An agent with transfer targets gets ADK's own
        ``transfer_to_agent``, so a transfer runs exactly as it does on an ADK run.
        :param sdk_agent: The ADK agent.
        :param warn: Log the skipped toolsets (when a socket opens).
        """
        tools: dict[str, BaseTool] = {}
        for tool in getattr(sdk_agent, "tools", None) or []:
            if isinstance(tool, BaseTool):
                tools[tool.name] = tool
            elif callable(tool):
                wrapped = FunctionTool(tool)
                tools[wrapped.name] = wrapped
            elif warn:
                self._log.warning(f"Tool {type(tool).__name__} is a toolset, which REALTIME mode does not resolve; it is not offered")
        targets = self._transfer_targets(sdk_agent)
        if targets:
            # As ADK builds it: the declaration limits ``agent_name`` to the target names.
            tools["transfer_to_agent"] = TransferToAgentTool(agent_names=[target.name for target in targets])
        return tools

    def _validate_transfers(self, root: Any) -> None:
        """Check, before connecting, that every agent the conversation can transfer to can run over a Live socket.

        A transfer opens a socket configured for its target, so a target that cannot be configured
        would otherwise fail mid-call. Raises for an agent that is not an LLM agent (a workflow
        agent runs its sub-agents in turn, which one Live socket cannot), names no Live model, or
        has an instruction provider.
        """
        for agent in self._reachable(root):
            if not isinstance(agent, LlmAgent):
                raise ValueError(
                    f"Agent '{getattr(agent, 'name', '?')}' is a {type(agent).__name__}; REALTIME mode runs and transfers between LLM agents only"
                )
            self._live_model(agent)
            self._instruction(agent)

    def team(self, agent: AKBaseAgent) -> list[str]:
        """Every agent the conversation can reach through transfers, the starting agent first."""
        root = getattr(agent, "agent", None)
        if root is None:
            return [agent.name]
        return [member.name for member in self._reachable(root)]

    @classmethod
    def _reachable(cls, root: Any) -> list[Any]:
        """Every agent reachable from ``root`` through transfers, by ADK's rules, ``root`` first, nearest first."""
        reached = [root]
        seen = {id(root)}
        for agent in reached:
            for target in cls._transfer_targets(agent):
                if id(target) not in seen:
                    seen.add(id(target))
                    reached.append(target)
        return reached

    async def connect(self, session: Session, agent: AKBaseAgent, callback: Callable) -> None:
        from google import genai

        self._callback = callback
        self._agent = agent
        self._run_config = (getattr(agent, "run_options", None) or {}).get("run_config")
        root = getattr(agent, "agent", None)
        self._validate_transfers(root)
        # Opened before the socket, so a failure here leaves no live connection to clean up.
        await self._open_tool_session(session.id)
        self._client = genai.Client()
        try:
            await self._open_socket(root)
        except Exception:
            # The pool drops a connection that failed to connect without disconnecting it.
            await self.disconnect()
            raise

        self._listen_task = asyncio.create_task(self._listen())
        self._watchdog = asyncio.create_task(self._watch_for_stalls())
        await self._release_held()

    async def _open_socket(self, sdk_agent: Any, extra: list[types.Content] | None = None) -> bool:
        """Open a Live socket configured for ``sdk_agent`` and make it the agent answering.

        After a transfer the socket is seeded with the conversation so far, presented as ADK presents
        it to a Live socket (:meth:`_presented_history`), as ADK's ``send_history`` seeds it:
        completed when it ends with the user's side (it always does, as every agent turn is presented
        on that side), so the new agent answers; on Gemini 3.x, which waits for fresh input after
        replayed history, followed by the placeholder input ADK sends.

        :param sdk_agent: The ADK agent the socket is for.
        :param extra: Turns added to this seed only, after the conversation, such as the note a reconnect
            sends; they are not kept in the history a later socket is seeded with.
        :return: Whether the socket was seeded.
        """
        model = self._live_model(sdk_agent)
        turns = self._presented_history() + list(extra or [])
        seeded = bool(turns)
        self._log.info(f"Connecting to Gemini Live (agent={sdk_agent.name}, model={model})")
        cm = self._client.aio.live.connect(model=model, config=self._connect_config(sdk_agent, seeded=seeded))
        connection = await cm.__aenter__()
        self._cm = cm
        self._active = sdk_agent
        if seeded:
            turn_complete = turns[-1].role == "user"
            await connection.send_client_content(turns=turns, turn_complete=turn_complete)
            if turn_complete and self._is_gemini_3_live(model):
                await connection.send_realtime_input(text=".")
            if turn_complete:
                self._owed_since = self._given_at = time.monotonic()
        self._connection = connection
        return seeded

    async def _close_socket(self) -> None:
        cm, self._cm, self._connection = self._cm, None, None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _stop_listening(self) -> None:
        task, self._listen_task = self._listen_task, None
        await self._cancel_and_wait(task)

    async def _open_tool_session(self, session_id: str) -> None:
        """Create this connection's ADK session, the one every tool call's ToolContext is built from.

        In-memory and connection-scoped: ``tool_context.state`` is shared by the tool calls of one
        connection, across transfers, and starts empty on the next, as the model's conversation does.
        :param session_id: The Agent Kernel session id, reused as the ADK session id.
        """
        self._tool_session_service = InMemorySessionService()
        self._tool_session = await self._tool_session_service.create_session(app_name="AgentKernel", user_id="AgentKernel", session_id=session_id)

    async def _listen(self) -> None:
        try:
            # receive() ends each turn at turn_complete, so the persistent socket is drained one
            # turn at a time; the outer loop re-enters it for the next turn.
            while True:
                # receive() is an async generator: closed here when listening stops (a cancel
                # included), not left half-run for the loop's shutdown to close twice.
                async with contextlib.aclosing(self._connection.receive()) as messages:
                    async for message in messages:
                        await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log.error(f"Gemini Live socket error: {e}")
            if not self._closing:
                self._recover_soon(f"socket error: {e}")

    def _recover_soon(self, reason: str) -> None:
        """Start replacing the socket, unless that is already under way or the connection is closing."""
        if self._closing or (self._recovery is not None and not self._recovery.done()):
            return
        self._recovery = asyncio.create_task(self._recover(reason))

    async def _recover(self, reason: str) -> None:
        """Reconnect the agent that had the call, seeded with the conversation and told the line dropped.

        What was outstanding on the lost socket is dropped (a tool result it was owed, a transfer it asked
        for), and the turn under way is ended, so what was said in it is kept and the edge's turn closes.
        """
        started = time.monotonic()
        last = self._last_message_at
        heard = f"{started - last:.0f} s ago" if last is not None else "never"
        self._log.warning(f"Gemini Live socket lost ({reason}); last message from Gemini {heard}. Reconnecting '{self._speaker()}'")
        self._connection = None
        # Before anything is awaited: a tool that finishes while the old socket closes then finds its call lost,
        # and a handoff it asked for is not performed while this replaces the socket.
        self._set_aside_outstanding_calls()
        await self._stop_listening()
        try:
            await self._close_socket()
        except Exception as e:
            self._log.debug(f"Closing the lost socket failed: {e!r}")
        # Any call the listener took in while it was being stopped.
        self._set_aside_outstanding_calls()
        self._owed_since = None
        caller_was_speaking = bool("".join(self._user_words).strip())
        await self._end_turn_and_report()
        self._interrupted_this_turn = False
        self._model_speaking = False
        self._caller_turn_reported = False
        await self._callback("done", {"status": "reconnecting"})

        if self._reconnected_at is not None and started - self._reconnected_at < self.QUICK_DROP_SECONDS:
            self._quick_drops += 1
        else:
            self._quick_drops = 0
        if self._quick_drops >= self.RECONNECT_ATTEMPTS:
            self._log.error(
                f"Gemini Live socket lost again within {self.QUICK_DROP_SECONDS:.0f} s of reconnecting, "
                f"{self._quick_drops} times in a row: not reconnecting ({reason})"
            )
            await self._callback("error", {"message": f"Gemini Live socket keeps dropping ({reason}); not reconnecting"})
            return

        await self._wait_for_lost_calls()
        for attempt, delay in enumerate(self.RECONNECT_DELAYS_SECONDS[: self.RECONNECT_ATTEMPTS], start=1):
            await asyncio.sleep(delay)
            if self._closing:
                return
            heard = caller_was_speaking or self._held_speech()
            note = self._reconnected_note(time.monotonic() - (last if last is not None else started), heard)
            try:
                seeded = await asyncio.wait_for(self._open_socket(self._active, extra=note), timeout=self.RECONNECT_TIMEOUT_SECONDS)
            except Exception as e:
                self._log.warning(f"Reconnect attempt {attempt} of {self.RECONNECT_ATTEMPTS} failed: {e!r}")
                try:
                    await self._close_socket()
                except Exception as close_error:
                    self._log.debug(f"Closing the failed reconnect socket failed: {close_error!r}")
                continue
            if self._closing:
                await self._close_socket()
                return
            self._listen_task = asyncio.create_task(self._listen())
            self._reconnected_at = time.monotonic()
            seconds = round(time.monotonic() - started)
            self._log.info(f"Reconnected '{self._speaker()}' to Gemini Live after {seconds} s")
            await self._callback("reconnected", {"agent": self._speaker(), "seconds": seconds, "seeded": seeded})
            await self._release_held()
            return
        self._log.error(f"Gemini Live could not reconnect after {self.RECONNECT_ATTEMPTS} attempts")
        await self._callback("error", {"message": f"Gemini Live socket lost ({reason}) and could not reconnect"})

    def _set_aside_outstanding_calls(self) -> None:
        """A tool still running for the lost socket reports to no socket; its result is kept for the history."""
        for call_id, batch in self._batches.items():
            self._lost_batches[call_id] = (batch, getattr(self._callers.get(call_id), "name", None) or self._speaker())
        self._batches.clear()
        self._callers.clear()
        self._transfers.clear()

    async def _wait_for_lost_calls(self) -> None:
        """Wait, up to ``LOST_TOOL_WAIT_SECONDS``, for the tools still running for the lost socket to finish.

        Their calls and results then go into the history the new socket is seeded with: without them the model does
        not know the call was made, and may make it again (a record written twice). A tool that takes longer is not
        waited for; its result is still kept in the history when it comes.
        """
        deadline = time.monotonic() + self.LOST_TOOL_WAIT_SECONDS
        while self._lost_batches and time.monotonic() < deadline and not self._closing:
            await asyncio.sleep(self.STALL_CHECK_SECONDS / 20)
        if self._lost_batches:
            names = sorted({call.name for batch, _ in self._lost_batches.values() for call in batch.calls if call.id not in batch.results})
            self._log.warning(f"Reconnecting while {names} still run for the lost socket; the new agent does not know of them")

    def _log_first_audio(self) -> None:
        """Log how long the caller waited for the agent to start speaking: after their last transcribed words, and
        after the model was last given something to answer (a tool result or text). Measured, not guessed from
        when a turn's words end."""
        now = time.monotonic()
        waits = []
        if self._caller_words_at is not None:
            waits.append(f"{now - self._caller_words_at:.1f} s after the caller's last words")
        if self._given_at is not None:
            waits.append(f"{now - self._given_at:.1f} s after its last tool result or text")
        if waits:
            self._log.info(f"'{self._speaker()}' started speaking {', '.join(waits)}")
        self._caller_words_at = self._given_at = None

    def _reconnected_note(self, seconds: float, caller_spoke: bool) -> list[types.Content]:
        """The note a reconnected socket's seed ends with, telling the agent the line dropped; none for an empty note.

        For that seed only: kept in the history, it would be replayed as the caller's words to every later socket.
        """
        note = self.RECONNECTED_NOTE if caller_spoke else self.RECONNECTED_QUIET_NOTE
        if not note:
            return []
        text = note.format(seconds=max(1, round(seconds)))
        return [types.Content(role="user", parts=[types.Part(text=text)])]

    def _held_speech(self) -> bool:
        """Whether the audio held while no socket was open has speech in it, not only the silence an edge sends."""
        for chunk in self._held_audio:
            samples = array("h", chunk[: len(chunk) - len(chunk) % 2])
            if samples and math.sqrt(sum(sample * sample for sample in samples) / len(samples)) > self.SPEECH_LEVEL:
                return True
        return False

    async def _watch_for_stalls(self) -> None:
        """Replace a socket that has answered nothing for ``STALL_SECONDS`` since it was given something to answer."""
        while not self._closing:
            await asyncio.sleep(self.STALL_CHECK_SECONDS)
            owed = self._owed_since
            if owed is not None and self._connection is not None and time.monotonic() - owed > self.STALL_SECONDS:
                self._recover_soon(f"no answer from Gemini in {self.STALL_SECONDS:.0f} s")

    def _hold_audio(self, pcm: bytes) -> None:
        """Keep what the caller says while no socket is open: its latest ``HOLD_AUDIO_SECONDS``."""
        self._held_audio.append(pcm)
        limit = int(self.HOLD_AUDIO_SECONDS * self.input_sample_rate * 2)
        while sum(len(chunk) for chunk in self._held_audio) > limit and len(self._held_audio) > 1:
            self._held_audio.pop(0)

    async def _release_held(self) -> None:
        """Send the new socket what the caller said, and any text sent, while there was none.

        The audio goes out oldest first, one chunk at a time: what the caller says meanwhile joins the end of what
        is held (``append_audio``), so the socket hears it all in order. What a socket lost again meanwhile has not
        sent stays held for the next one.
        """
        texts, self._held_text = self._held_text, []
        mime = f"audio/pcm;rate={self.input_sample_rate}"
        while self._held_audio and self._connection is not None:
            chunk = self._held_audio.pop(0)
            await self._connection.send_realtime_input(audio=types.Blob(data=chunk, mime_type=mime))
        for text in texts:
            await self.send_text(text)

    async def _handle_message(self, message: types.LiveServerMessage) -> None:
        """Handle one server message.

        The stall wait (``_owed_since``) moves only on the model's progress: each audio or output
        transcription restarts it, as a response under way must keep producing, and ``turn_complete``, an
        ``interrupted`` (or the barge-in this runner detects) and a tool call end it. Any other message, the
        caller's own transcription included, leaves it as it is.
        """
        self._last_message_at = time.monotonic()
        server_content = getattr(message, "server_content", None)
        if server_content is not None:
            # Barge-in. The server signals it on ``interrupted``; its low-latency
            # ``interim_input_transcription`` (updated while the user speaks) gives the same
            # signal a beat earlier, so the edge can stop playback as soon as the user starts
            # talking over the model. Only fires while the model is actually speaking, and only
            # once per turn.
            interim = getattr(server_content, "interim_input_transcription", None)
            if getattr(server_content, "interrupted", False):
                # The response stopped: the model owes the caller an answer only once they finish speaking.
                self._owed_since = None
            if getattr(server_content, "interrupted", False) and not self._interrupted_this_turn:
                self._interrupted_this_turn = True
                self._model_speaking = False
                self._caller_turn_reported = True
                self._log.info("Gemini barge-in (server interruption); stopping playback")
                await self._callback("interrupt", {})
            elif self._model_speaking and not self._interrupted_this_turn:
                if interim is not None and interim.text:
                    self._interrupted_this_turn = True
                    self._model_speaking = False
                    self._caller_turn_reported = True
                    self._owed_since = None
                    self._log.info("Gemini barge-in (user speaking); stopping playback")
                    await self._callback("interrupt", {})
            elif not self._model_speaking and not self._caller_turn_reported and self._transcribed(interim, server_content):
                # The caller starting a turn while the model is silent; the pool decides whether
                # audio it is still pacing makes it a barge-in.
                self._caller_turn_reported = True
                await self._callback("speech_started", {})
            elif not self._model_speaking and self._transcribed(interim, server_content):
                # More of the caller's words: they are still speaking, so a long answer is not
                # taken for silence.
                await self._callback("speech_heard", {})

            input_transcription = getattr(server_content, "input_transcription", None)
            if input_transcription is not None and input_transcription.text:
                self._user_words.append(input_transcription.text)
                self._caller_words_at = time.monotonic()

            output_transcription = getattr(server_content, "output_transcription", None)
            if output_transcription is not None and output_transcription.text:
                self._caller_turn_reported = False
                self._owed_since = time.monotonic()
                self._model_words.append(output_transcription.text)
                await self._callback("transcript_delta", {"delta": output_transcription.text, "message_id": ""})

            model_turn = getattr(server_content, "model_turn", None)
            if model_turn and model_turn.parts:
                for part in model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and inline.data:
                        if not self._model_speaking:
                            self._log_first_audio()
                        self._model_speaking = True
                        self._caller_turn_reported = False
                        self._owed_since = time.monotonic()
                        audio_b64 = base64.b64encode(inline.data).decode("utf-8")
                        await self._callback("audio_delta", {"delta": audio_b64, "message_id": ""})

            if getattr(server_content, "turn_complete", False):
                self._interrupted_this_turn = False
                self._model_speaking = False
                self._caller_turn_reported = False
                self._owed_since = None
                await self._end_turn_and_report()
                await self._callback("done", {"status": "completed"})

        tool_call = getattr(message, "tool_call", None)
        if tool_call and tool_call.function_calls:
            # The model answered with calls; it owes a reply again once their results are sent.
            self._owed_since = None
            batch = self._ToolBatch(calls=list(tool_call.function_calls))
            for call in batch.calls:
                self._batches[call.id] = batch
                self._callers[call.id] = self._active
            for call in batch.calls:
                await self._callback("tool_call", {"call_id": call.id, "name": call.name, "arguments": json.dumps(call.args or {})})

    @staticmethod
    def _transcribed(interim: Any, server_content: Any) -> bool:
        """Whether a server message carries the caller's words, interim or final."""
        final = getattr(server_content, "input_transcription", None)
        return any(transcription is not None and transcription.text for transcription in (interim, final))

    def _end_turn(self) -> str:
        """Add the turn's transcribed words to the history a transfer replays: the user's, then the agent's.

        The caller's words are also logged, as Gemini transcribed them, so a log shows both sides of
        the call (the edge logs the agent's).

        :return: The caller's words in the turn, or "" when they said nothing.
        """
        said = ""
        for author, role, words in (("user", "user", self._user_words), (self._speaker(), "model", self._model_words)):
            text = "".join(words).strip()
            if text:
                if author == "user":
                    said = text
                    self._log.info(f"Caller said: {text}")
                self._history.append(self._Said(author, types.Content(role=role, parts=[types.Part(text=text)])))
            words.clear()
        return said

    async def _end_turn_and_report(self) -> None:
        """End the turn (``_end_turn``) and report the caller's words in it as ``caller_transcript``, for realtime hooks."""
        await self._report_caller(self._end_turn())

    async def _report_caller(self, said: str) -> None:
        if said:
            await self._callback("caller_transcript", {"text": said})

    def _speaker(self) -> str:
        """The name of the agent answering, which the turn being recorded is the work of."""
        return getattr(self._active, "name", None) or "agent"

    def _presented_history(self) -> list[types.Content]:
        """The conversation as ADK sends it to a Live socket after a transfer.

        The caller's words go as they are. Every agent's turn, the new agent's own included, goes as
        user-side context naming who said it or called what (``[architect] said: ...``), fenced as
        data, through ADK's own presenter: so an agent can tell a teammate's words, and a question
        put to it, from its own, and the Live API does not take replayed turns for the model's
        current answer.
        """
        turns = []
        for said in self._history:
            if said.author == "user":
                turns.append(said.content)
                continue
            presented = _present_other_agent_message(Event(author=said.author, content=said.content))
            if presented is not None and presented.content is not None:
                turns.append(presented.content)
        return turns

    async def append_audio(self, base64_audio: str) -> None:
        # Audio still held for a new socket goes first (``_release_held``): this joins the end of it.
        if self._connection and not self._held_audio:
            await self._connection.send_realtime_input(
                audio=types.Blob(data=base64.b64decode(base64_audio), mime_type=f"audio/pcm;rate={self.input_sample_rate}")
            )
        elif not self._closing:
            self._hold_audio(base64.b64decode(base64_audio))

    async def send_text(self, text: str) -> None:
        if self._connection:
            await self._end_turn_and_report()
            self._history.append(self._Said("user", types.Content(role="user", parts=[types.Part(text=text)])))
            await self._connection.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)
            # A wait already running is kept: only the model's progress moves it. Otherwise text sent every so often
            # to a socket that has stopped answering (an application's nudges) keeps it from being taken for stalled.
            if self._owed_since is None:
                self._owed_since = time.monotonic()
            self._given_at = time.monotonic()
        elif not self._closing:
            self._held_text.append(text)

    async def send_tool_result(self, call_id: str, result: str) -> None:
        """Record one function call's result; answer its tool_call message once every call in it has one.

        As ADK answers a model's parallel calls, the responses go back together, in call order, and
        the turn's calls and responses are kept in the history a later transfer replays. When one of
        the calls asked for a transfer the responses go only into that history, which seeds the new
        agent's socket; the first transfer in call order is performed, and any other is answered as
        not performed. A result for a call made on a socket a transfer has since closed is dropped:
        the call is not the open socket's. A result for a call made on a socket that was lost is kept in
        the history, once every call of its batch has one, so a later socket is seeded with it; it is
        sent to no socket, and a transfer it asked for is not performed.
        """
        lost = self._lost_batches.pop(call_id, None)
        if lost is not None:
            batch, author = lost
            batch.results[call_id] = result
            self._transfers.pop(call_id, None)
            if len(batch.results) == len(batch.calls):
                self._append_tool_turn(author, batch, self._responses(batch))
                self._log.info(f"Kept the results of {[call.name for call in batch.calls]}, called on a lost socket, in the history")
            return
        batch = self._batches.pop(call_id, None)
        if batch is None:
            self._log.debug(f"Dropping the result of call {call_id}: it was made on a socket a transfer has closed")
            return
        batch.results[call_id] = result
        if len(batch.results) < len(batch.calls):
            return

        transfers = [call for call in batch.calls if call.id in self._transfers]
        if transfers:
            chosen, *extra = transfers
            for call in extra:
                batch.results[call.id] = f"Error: only one handoff is performed per turn; this one, to {self._transfers[call.id].name}, was not"
            await self._transfer(batch, self._transfers[chosen.id])
            return
        responses = self._responses(batch)
        await self._report_caller(self._record_tool_turn(batch, responses))
        if self._connection:
            await self._connection.send_tool_response(function_responses=responses)
            self._owed_since = self._given_at = time.monotonic()

    def _record_tool_turn(self, batch: GoogleADKRealtimeRunner._ToolBatch, responses: list[types.FunctionResponse]) -> str:
        """Add a tool-call turn to the history, as ADK's session records it.

        The words said before the calls first, then the calls, then their responses; the words said
        after them follow when the turn ends.

        :return: The caller's words before the calls, as ``_end_turn`` returns them.
        """
        said = self._end_turn()
        self._append_tool_turn(self._speaker(), batch, responses)
        return said

    def _append_tool_turn(self, author: str, batch: GoogleADKRealtimeRunner._ToolBatch, responses: list[types.FunctionResponse]) -> None:
        """Add a batch's calls, then their responses, to the history, as made by ``author``."""
        calls = [types.Part(function_call=types.FunctionCall(id=call.id, name=call.name, args=call.args or {})) for call in batch.calls]
        self._history.append(self._Said(author, types.Content(role="model", parts=calls)))
        self._history.append(self._Said(author, types.Content(role="user", parts=[types.Part(function_response=response) for response in responses])))

    @staticmethod
    def _responses(batch: GoogleADKRealtimeRunner._ToolBatch) -> list[types.FunctionResponse]:
        # Wrapped as ADK wraps a plain tool result, so the model sees the same shape as on a normal run.
        return [types.FunctionResponse(id=call.id, name=call.name, response={"result": batch.results[call.id]}) for call in batch.calls]

    async def _transfer(self, batch: GoogleADKRealtimeRunner._ToolBatch, target: Any) -> None:
        """Move the conversation to ``target`` on a socket configured for it.

        The old socket's listener is stopped first, so nothing it still says is credited to the new
        agent and its close is not reported as a failure; what the caller says during the switch is
        held and sent to the new agent. The turn is ended (``done``) and the change reported before the new socket opens,
        which is seeded with the conversation, the turn's calls and their results included, as ADK
        replays them. A socket that fails to open within the timeout is reported as an ``error``, so
        the pool replaces the connection.
        """
        previous = self._active
        # What is still outstanding belongs to the socket being closed.
        self._transfers.clear()
        self._batches.clear()
        self._callers.clear()
        self._connection = None
        await self._stop_listening()

        await self._report_caller(self._record_tool_turn(batch, self._responses(batch)))
        self._interrupted_this_turn = False
        self._model_speaking = False
        self._caller_turn_reported = False
        self._log.info(f"Transferring from '{previous.name}' to '{target.name}'")
        await self._callback("done", {"status": "transferred"})
        await self._callback("agent_changed", {"agent": target.name, "previous_agent": previous.name})

        try:
            await self._close_socket()
            await asyncio.wait_for(self._open_socket(target), timeout=self.TRANSFER_CONNECT_TIMEOUT_SECONDS)
        except Exception as e:
            self._log.exception(f"Transfer to '{target.name}' failed")
            await self._close_socket()
            if not self._closing:
                await self._callback("error", {"message": f"Gemini Live transfer to '{target.name}' failed: {e!r}"})
            return
        if self._closing:
            # Disconnected while the new socket was opening.
            await self._close_socket()
            return
        self._listen_task = asyncio.create_task(self._listen())
        await self._release_held()

    async def execute_tool(self, name: str, arguments: str, context: AKToolContext, call_id: str) -> str:
        """Invoke an ADK tool through ADK's own ``run_async`` with a real ToolContext.

        ADK *injects* a ``ToolContext`` (session state, actions, artifacts) into any tool that
        declares one, so calling the wrapped function directly would hand those tools ``None``
        and any ``tool_context.state`` access would fail. A fresh ``InvocationContext`` /
        ``ToolContext`` is built here instead, from this connection's own ADK session, carrying
        the active Agent Kernel context id in its state the same way a normal ADK run does.

        The tool runs as the agent that made the call, between that agent's tool callbacks
        (:meth:`_run_tool`). A call that leaves ``tool_context.actions.transfer_to_agent`` set (ADK's
        ``transfer_to_agent``, any tool that sets the action, or a callback that does, as ADK
        allows) asks for a transfer, performed once every call of its tool_call message has a
        result; the target is looked up across the agent tree, as ADK looks it up.
        """
        from google.adk.agents.invocation_context import InvocationContext
        from google.adk.tools import ToolContext as ADKToolContext

        if self._tool_session is None:
            raise RuntimeError("Gemini Live connection is not open: call connect() before executing tools")

        caller = self._callers.pop(call_id, None) or self._active
        tool = self._live_tools(caller).get(name)
        if tool is None:
            return f"Error: Tool {name} not found"

        invocation_context = InvocationContext(
            session_service=self._tool_session_service,
            invocation_id=str(uuid4()),
            session=self._tool_session,
            agent=caller,
        )
        tool_context = ADKToolContext(invocation_context=invocation_context, function_call_id=call_id)

        # Entering the context populates the cache the ADK tool wrapper fetches the Agent
        # Kernel context from; the wrapper then sets/resets the contextvar itself.
        args = json.loads(arguments) if arguments else {}
        with context:
            tool_context.state["ak_tool_context"] = context.id
            result = await self._run_tool(caller, tool, args, tool_context)

        target_name = tool_context.actions.transfer_to_agent
        if target_name:
            target = caller.root_agent.find_agent(target_name)
            if target is None:
                return f"Error: there is no agent named {target_name} to transfer to"
            self._transfers[call_id] = target
        return str(result) if result is not None else ""

    @classmethod
    async def _run_tool(cls, caller: Any, tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Any:
        """Run ``tool`` between ``caller``'s tool callbacks, in the order and with the short-circuits of ADK's own flow.

        The before-callbacks run in turn until one returns a truthy result; a result other than
        ``None`` answers in the tool's place and the tool does not run. A tool that raises is offered
        to the error callbacks, the first result other than ``None`` replacing the error, which
        otherwise propagates. The after-callbacks then run in turn until one returns a truthy result;
        a result other than ``None`` replaces the tool's. Each callback may be sync or async.
        """
        response = None
        for callback in getattr(caller, "canonical_before_tool_callbacks", None) or []:
            response = await cls._call(callback, tool=tool, args=args, tool_context=tool_context)
            if response:
                break

        if response is None:
            try:
                response = await tool.run_async(args=args, tool_context=tool_context)
            except Exception as error:
                for callback in getattr(caller, "canonical_on_tool_error_callbacks", None) or []:
                    response = await cls._call(callback, tool=tool, args=args, tool_context=tool_context, error=error)
                    if response is not None:
                        break
                if response is None:
                    raise

        altered = None
        for callback in getattr(caller, "canonical_after_tool_callbacks", None) or []:
            altered = await cls._call(callback, tool=tool, args=args, tool_context=tool_context, tool_response=response)
            if altered:
                break
        return altered if altered is not None else response

    @staticmethod
    async def _call(callback: Callable, **kwargs: Any) -> Any:
        """Call an ADK callback, awaiting it when it is async."""
        result = callback(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def disconnect(self) -> None:
        self._closing = True
        watchdog, self._watchdog = self._watchdog, None
        recovery, self._recovery = self._recovery, None
        await self._cancel_and_wait(watchdog)
        await self._cancel_and_wait(recovery)
        await self._stop_listening()
        await self._close_socket()
        if self._client is not None:
            await self._client.aio.aclose()
            self._client = None
        self._tool_session = None
        self._tool_session_service = None


class GoogleADKAgent(AKBaseAgent):
    """
    GoogleADKAgent class provides an agent wrapping for Google ADK Agent SDK based agents.
    """

    RESERVED_RUN_OPTIONS: ClassVar[Mapping[str, str]] = {
        "agent": "the native agent is the one this GoogleADKAgent wraps",
        "app": "the runner builds the App itself, carrying the ResumabilityConfig a pause depends on; declare plugins instead",
        "app_name": "fixed to 'AgentKernel' by the runner",
        "node": "the runner constructs the ADK Runner from the agent",
        "session_service": "the GoogleADKSession stored on the Agent Kernel session",
        "auto_create_session": "the runner creates the ADK session itself",
        "user_id": "fixed to 'AgentKernel' by the runner",
        "session_id": "the Agent Kernel session id",
        "new_message": "built from the AgentRequest list by the runner",
        "state_delta": "state is seeded from the session's framework_context; seed it with Session.set_framework_context()",
        "invocation_id": "assigned by ADK per run, and set by the runner from the paused record when a run is resumed",
        "yield_user_message": "the stream mapping expects model events only",
    }

    def __init__(self, name: str, runner: GoogleADKRunner, agent: BaseAgent, realtime_runner_cls: type[BaseRealtimeRunner] | None = None):
        """
        Initializes a GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The Google ADK agent instance.
        :param realtime_runner_cls: Optional realtime runner class for this agent.
        """
        super().__init__(name, runner, realtime_runner_cls)
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
        :param realtime_runner_cls: Realtime adapter class enabling ``execution.mode: realtime``
            for this module's agents. Defaults to :class:`GoogleADKRealtimeRunner`; pass a custom
            class to override. Only the pipeline (in REALTIME mode) ever instantiates it.
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
        # The realtime runner class is attached unconditionally; only the pipeline (in REALTIME
        # mode) ever instantiates it, so the framework need not know the execution mode.
        return GoogleADKAgent(agent.name, self.runner, agent, realtime_runner_cls=self.realtime_runner_cls)

    def load(self, agents: list[BaseAgent]) -> "GoogleADKModule":
        """
        Loads the specified agents into the module. By replacing the current agents.
        :param agents: List of agents to load.
        :return: GoogleADKModule instance.
        """
        super().load(agents)
        return self


class GoogleADKToolBuilder(ToolBuilder):
    """
    Tool builder for Google ADK.

    Wraps generic tool functions into ADK-compatible FunctionTool instances.
    """

    @classmethod
    def bind(cls, funcs: list[Callable], **options: Any) -> list[Any]:
        """
        Bind generic tool functions to ADK FunctionTool instances.

        Keyword options are forwarded to `FunctionTool` untouched and apply to every function in the
        call, so tools wanting different options are bound in separate calls. `require_confirmation`
        is the one that matters: it is this framework's human-in-the-loop gate, so without
        forwarding, a gated tool could only be built by constructing `FunctionTool` directly, giving
        up the framework-free tool function the builder exists to allow.

        :param funcs: List of generic tool functions to bind.
        :param options: Keyword arguments passed to `FunctionTool`, e.g. `require_confirmation=True`.
        :return: List of ADK-compatible FunctionTool instances.
        :raises TypeError: If any item in funcs is not callable, or an option ADK does not take.
        """
        tools = []
        for func in funcs:
            tools.append(FunctionTool(cls._wrap(func), **options))
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
