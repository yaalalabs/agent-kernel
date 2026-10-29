from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import inspect
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, List, Literal, Mapping
from uuid import uuid4

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.events import Event, EventActions
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, State
from google.adk.tools import FunctionTool, ToolContext
from google.adk.workflow import Workflow
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
    ExecutionMode,
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

APP_NAME = "AgentKernel"
USER_ID = "AgentKernel"
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
        app_name = APP_NAME
        user_id = USER_ID
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
    """ADK live runner: sends input, maps events, and restarts a dead run on the same session."""

    input_sample_rate = 16000
    output_sample_rate = 24000

    LIVE_OPTIONS: ClassVar[frozenset[str]] = frozenset({"run_config"})
    APP_OPTIONS: ClassVar[frozenset[str]] = frozenset({"plugins", "context_cache_config"})
    RESTART_DELAYS_SECONDS: ClassVar[tuple[float, ...]] = (0.5, 1.0, 2.0)
    RESTART_HEALTH_SECONDS: ClassVar[float] = 30.0
    MAX_TOTAL_RESTARTS: ClassVar[int] = 20
    STALL_TIMEOUT_SECONDS: ClassVar[float] = 5.0
    HANDOVER_STALL_TIMEOUT_SECONDS: ClassVar[float] = 10.0
    NO_SPEECH_TIMEOUT_SECONDS: ClassVar[float] = 15.0
    MAX_STALL_RESTARTS: ClassVar[int] = 2
    FILLER_BARGE_INS: ClassVar[frozenset[str]] = frozenset({"and", "uh", "um", "mhm", "hmm", "mm", "er", "ah", "oh", "hm"})

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.realtime")
        self._callback: Callable | None = None
        self._runner: Runner | None = None
        self._queue: LiveRequestQueue | None = None
        self._listen_task: asyncio.Task | None = None
        self._session_id: str | None = None
        self._live_options: dict[str, Any] = {}
        self._restart_attempt = 0
        self._total_restarts = 0
        self._run_started_at = 0.0
        self._awaiting_model_since: float | None = None
        self._awaiting_speech_since: float | None = None
        self._stall_restarts = 0
        self._speech_restarts = 0
        self._handover_pending = False
        self._handover_to: str | None = None
        self._tools_running = 0
        self._last_client_words = ""
        self._last_client_at = 0.0
        self._watch_task: asyncio.Task | None = None
        self._closing = False
        self._speaker: str | None = None
        self._roster: list[str] = []
        self._tool_context: AKToolContext | None = None

    # -- the agent graph ----------------------------------------------------------------------

    def team(self, agent: AKBaseAgent) -> list[str]:
        """Every speaking agent the root's public graph names, the root first when it speaks."""
        root = getattr(agent, "agent", None)
        if root is None:
            return [agent.name]
        return [member.name for member in self._speaking(root)]

    def initial_speaker(self, agent: AKBaseAgent) -> str | None:
        """The root's own name when it is an agent; ``None`` for a workflow, which only contains the speakers."""
        return agent.name if isinstance(getattr(agent, "agent", None), LlmAgent) else None

    @classmethod
    def _speaking(cls, root: Any) -> list[LlmAgent]:
        """Speaking LlmAgents under root, nearest first."""
        found: list[LlmAgent] = []
        seen: set[int] = set()
        pending = [root] if isinstance(root, LlmAgent) else cls._workflow_nodes(root)
        while pending:
            node = pending.pop(0)
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, LlmAgent) and node.mode != "single_turn":
                found.append(node)
            pending.extend(getattr(node, "sub_agents", None) or [])
        return found

    @staticmethod
    def _workflow_nodes(root: Any) -> list[Any]:
        """The nodes of a workflow root, from its public graph; none for any other root."""
        graph = getattr(root, "graph", None)
        return list(getattr(graph, "nodes", None) or [])

    def _check_graph(self, agent: AKBaseAgent, root: Any) -> None:
        """Reject graphs ADK cannot run live."""
        if not isinstance(root, (BaseAgent, Workflow)):
            raise TypeError(f"Agent '{agent.name}' wraps {type(root).__name__}; realtime mode runs an ADK LlmAgent or Workflow")
        pending = [root]
        seen: set[int] = set()
        while pending:
            node = pending.pop(0)
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, (ParallelAgent, LoopAgent)):
                raise ValueError(
                    f"'{node.name}' is a {type(node).__name__}, which ADK does not run live; keep it off the realtime path (agent '{agent.name}')"
                )
            if isinstance(node, Workflow):
                for member in self._workflow_nodes(node):
                    if isinstance(member, LlmAgent) and member.mode in (None, "single_turn"):
                        raise ValueError(
                            f"Node '{member.name}' of workflow '{node.name}' has mode {member.mode!r}, which runs outside the live connection "
                            "so the caller would hear nothing from it; set mode='chat' or mode='task' (agent '" + agent.name + "')"
                        )
                    pending.append(member)
            pending.extend(getattr(node, "sub_agents", None) or [])

    # -- lifecycle ----------------------------------------------------------------------------

    async def connect(self, session: Session, agent: AKBaseAgent, callback: Callable) -> None:
        root = getattr(agent, "agent", None)
        self._check_graph(agent, root)
        self._callback = callback
        self._speaker = self.initial_speaker(agent)
        self._roster = self.team(agent)
        options = await agent.resolve_run_options(session, [])
        constructor_options, live_options, app_options = self._split_options(agent, options)

        try:
            adk_session = GoogleADKRunner._session(session)
            await adk_session.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)
            # The wrapper finds this context by id from the ADK session state.
            self._tool_context = AKToolContext(Runtime.current(), agent, session, [])
            self._tool_context.__enter__()
            await adk_session.update_session_state(self._tool_context.id, agent.name, {"ak_tool_context": self._tool_context.id})
            plugins = app_options.pop("plugins", None)
            app = App(name=APP_NAME, root_agent=root, **app_options, **({"plugins": plugins} if plugins is not None else {}))
            self._runner = Runner(
                **GoogleADKRunner._native_kwargs(constructor_options, app=app, app_name=APP_NAME, session_service=adk_session.session_service)
            )
            self._session_id = session.id
            self._live_options = dict(live_options)
            self._restart_attempt = 0
            self._total_restarts = 0
            self._start_live()
            self._watch_task = asyncio.create_task(self._watch_stalls())
        except (Exception, asyncio.CancelledError):
            await self.disconnect()
            raise

    def _split_options(self, agent: AKBaseAgent, options: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Split options between App, Runner and run_live."""
        remaining = dict(options)
        app_options = {key: remaining.pop(key) for key in self.APP_OPTIONS if key in remaining}
        constructor_options, other = GoogleADKRunner._split_run_options(remaining)
        rejected = sorted(key for key in other if key not in self.LIVE_OPTIONS)
        if rejected:
            reasons = {**GoogleADKAgent.RESERVED_RUN_OPTIONS}
            details = "; ".join(f"'{key}'" + (f": {reasons[key]}" if key in reasons else ": not a setting of ADK's run_live()") for key in rejected)
            accepted = ", ".join(sorted(GoogleADKRunner.RUNNER_CONSTRUCTOR_OPTIONS | self.APP_OPTIONS | self.LIVE_OPTIONS))
            raise ValueError(
                f"Run option(s) cannot apply to a realtime session of agent '{agent.name}': {details}. A realtime session takes: {accepted}"
            )
        return dict(constructor_options), dict(other), app_options

    def _start_live(self) -> None:
        """Start a fresh run_live stream."""
        assert self._runner is not None and self._session_id is not None
        self._run_started_at = time.monotonic()
        self._tools_running = 0
        queue, self._queue = self._queue, LiveRequestQueue()
        if queue is not None:
            queue.close()
        events = self._runner.run_live(
            user_id=USER_ID,
            session_id=self._session_id,
            live_request_queue=self._queue,
            **self._live_options,
        )
        self._listen_task = asyncio.create_task(self._listen(events))

    @staticmethod
    def _restartable(error: Exception) -> bool:
        """Whether this is a transport drop a new live run can recover from, not a terminal failure."""
        if isinstance(error, (ConnectionError, ConnectionAbortedError, ConnectionResetError, TimeoutError)):
            return True
        name = type(error).__name__.lower()
        if "connectionclosed" in name or "connectionreset" in name:
            return True
        text = str(error).lower()
        return any(marker in text for marker in ("abnormal closure", "connection lost", "connection closed", "1006"))

    async def _restart(self, error: Exception) -> bool:
        """Start a dropped live run again, with the configured delays. ``False`` when it should surface."""
        if self._closing or self._runner is None or self._session_id is None or not self.RESTART_DELAYS_SECONDS:
            return False
        if not self._restartable(error):
            return False
        while self._restart_attempt < len(self.RESTART_DELAYS_SECONDS):
            if self._total_restarts >= self.MAX_TOTAL_RESTARTS:
                self._log.error("Giving up on the ADK live run: restart limit reached")
                return False
            self._total_restarts += 1
            delay = self.RESTART_DELAYS_SECONDS[self._restart_attempt]
            self._restart_attempt += 1
            self._log.warning(
                f"ADK live run failed: {error}; restarting in {delay}s " f"(attempt {self._restart_attempt}/{len(self.RESTART_DELAYS_SECONDS)})"
            )
            await asyncio.sleep(delay)
            if self._closing:
                return False
            try:
                self._start_live()
                if self._awaiting_model_since is not None:
                    self._awaiting_model_since = time.monotonic()
                return True
            except Exception as next_error:  # noqa: BLE001 - each failed start is the next attempt's reason
                error = next_error
                self._log.error(f"Could not restart the ADK live run: {next_error}")
                if not self._restartable(next_error):
                    return False
        return False

    async def _watch_stalls(self) -> None:
        """Restart after no event or no spoken output; keep the same ADK session."""
        while not self._closing:
            await asyncio.sleep(0.25)
            if self._closing or self._tools_running:
                continue
            now = time.monotonic()
            event_timeout = self.HANDOVER_STALL_TIMEOUT_SECONDS if self._handover_pending else self.STALL_TIMEOUT_SECONDS
            speech_timeout = (
                max(self.NO_SPEECH_TIMEOUT_SECONDS, self.HANDOVER_STALL_TIMEOUT_SECONDS) if self._handover_pending else self.NO_SPEECH_TIMEOUT_SECONDS
            )
            no_event = self._awaiting_model_since is not None and now - self._awaiting_model_since >= event_timeout
            no_speech = self._awaiting_speech_since is not None and now - self._awaiting_speech_since >= speech_timeout
            if not (no_event or no_speech):
                continue
            reason = "no model event" if no_event else "no spoken output"
            timeout = event_timeout if no_event else speech_timeout
            attempts = self._stall_restarts if no_event else self._speech_restarts
            if self._total_restarts >= self.MAX_TOTAL_RESTARTS:
                await self._callback("error", {"message": "ADK live run stalled: restart limit reached"})
                return
            self._total_restarts += 1
            self._awaiting_model_since = None
            self._awaiting_speech_since = None
            if attempts >= self.MAX_STALL_RESTARTS:
                what = "the handover" if self._handover_pending else "the client turn"
                await self._callback("error", {"message": f"ADK live run stalled ({reason}) during {what}"})
                return
            if no_event:
                self._stall_restarts += 1
            else:
                self._speech_restarts += 1
            self._log.warning(
                "ADK live run stalled (%s) for %.1fs (%s); restarting (attempt %s/%s)",
                reason,
                timeout,
                "handover" if self._handover_pending else "client turn",
                attempts + 1,
                self.MAX_STALL_RESTARTS,
            )
            task, self._listen_task = self._listen_task, None
            await self._cancel_and_wait(task)
            try:
                self._start_live()
                self._awaiting_model_since = time.monotonic()
                self._awaiting_speech_since = time.monotonic()
            except Exception as e:  # noqa: BLE001 - a failed restart is surfaced as a terminal error
                self._log.error(f"Could not restart the stalled ADK live run: {e}")
                await self._callback("error", {"message": f"ADK live run failed: {e}"})
                return

    async def _listen(self, events: AsyncGenerator[Event, None]) -> None:
        """Report ADK events to the pool in order."""
        try:
            async with contextlib.aclosing(events) as stream:
                async for event in stream:
                    # Only a long-lived run earns a fresh restart budget.
                    if time.monotonic() - self._run_started_at >= self.RESTART_HEALTH_SECONDS:
                        self._restart_attempt = 0
                    if await self._handle_event(event):
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log.error(f"ADK live run failed: {e}")
            if await self._restart(e):
                return
            if not self._closing:
                await self._callback("error", {"message": f"ADK live run failed: {e}"})
            return
        if not self._closing:
            await self._callback("error", {"message": "ADK live run ended"})

    async def _handle_event(self, event: Event) -> bool:
        """Map one ADK event to pool events; True ends the listener."""
        if event.error_code or event.error_message:
            detail = ": ".join(value for value in (event.error_code, event.error_message) if value)
            await self._callback("error", {"message": f"ADK live run failed: {detail}"})
            return True
        if event.actions and event.actions.requested_tool_confirmations:
            await self._refuse_confirmation(event)
            return True
        # Tool wall time is not model silence.
        calls = [call for call in event.get_function_calls() if getattr(call, "name", None) != "transfer_to_agent"]
        responses = event.get_function_responses()
        self._tools_running = max(0, self._tools_running + len(calls) - len(responses))
        if event.author == "user":
            transcription = event.input_transcription
            if transcription is not None and transcription.finished and (transcription.text or "").strip():
                self._awaiting_model_since = time.monotonic()
                self._awaiting_speech_since = time.monotonic()
                self._stall_restarts = 0
                self._speech_restarts = 0
                self._handover_pending = False
                self._handover_to = None
                self._last_client_words = transcription.text.strip()
                self._last_client_at = time.monotonic()
                await self._callback("input_transcript", {"text": transcription.text.strip(), "message_id": event.id})
            if responses and not self._tools_running:
                self._awaiting_model_since = time.monotonic()
                self._awaiting_speech_since = time.monotonic()
            return False
        if self._handover_pending and self._handover_to and event.author != self._handover_to:
            # The old agent may still be finishing its tail; keep the handover grace.
            self._awaiting_model_since = time.monotonic()
            self._awaiting_speech_since = time.monotonic()
            self._stall_restarts = 0
        else:
            # A model event is progress.
            self._awaiting_model_since = None
            self._stall_restarts = 0
            self._handover_pending = False
            self._handover_to = None
        if event.interrupted:
            if self._is_filler_barge_in():
                self._log.info("Ignoring barge-in for microphone filler %r", self._last_client_words)
            else:
                await self._callback("interrupt", {})

        audio_heard = False
        output = event.output_transcription
        if output is not None and output.text and not output.finished and event.partial:
            await self._speaker_changed(event.author)
            await self._callback("transcript_delta", {"delta": output.text, "message_id": event.id})

        for part in (event.content.parts if event.content and event.content.parts else []):
            blob = part.inline_data
            if blob is not None and blob.data and (blob.mime_type or "").startswith("audio/"):
                audio_heard = True
                await self._speaker_changed(event.author)
                self._check_output_rate(blob.mime_type)
                await self._callback("audio_delta", {"delta": base64.b64encode(blob.data).decode("utf-8"), "message_id": event.id})
            elif part.text and not part.thought and output is None:
                await self._speaker_changed(event.author)
                await self._callback("transcript_delta", {"delta": part.text, "message_id": event.id})

        if event.actions and event.actions.transfer_to_agent:
            # The next agent follows on its own connection.
            self._awaiting_model_since = time.monotonic()
            self._awaiting_speech_since = time.monotonic()
            self._stall_restarts = 0
            self._speech_restarts = 0
            self._handover_pending = True
            self._handover_to = event.actions.transfer_to_agent
            await self._callback("done", {"status": "transferred"})
        elif event.turn_complete:
            self._awaiting_speech_since = None
            self._speech_restarts = 0
            self._restart_attempt = 0  # a completed turn is proof the restarted run is healthy
            await self._callback("done", {"status": "completed"})
        if responses and not self._tools_running:
            self._awaiting_model_since = time.monotonic()
            self._awaiting_speech_since = time.monotonic()
            self._handover_pending = False
            self._handover_to = None
        if audio_heard:
            # Audio keeps the no-speech clock alive until turn_complete.
            self._awaiting_speech_since = time.monotonic()
            self._stall_restarts = 0
        return False

    def _is_filler_barge_in(self) -> bool:
        """Whether the interrupt came right after a one-word microphone noise such as "and" or "mhm"."""
        word = self._last_client_words.strip().lower().strip(".,!?;:")
        return bool(word) and time.monotonic() - self._last_client_at <= 1.5 and word in self.FILLER_BARGE_INS

    def _check_output_rate(self, mime_type: str) -> None:
        """Fail on audio that is not at the rate the pool resamples from, instead of playing it at the wrong speed."""
        rate = next((p.split("=", 1)[1] for p in mime_type.split(";")[1:] if p.strip().startswith("rate=")), None)
        if rate is not None and int(rate) != self.output_sample_rate:
            raise RuntimeError(f"ADK produced audio at {rate} Hz; the realtime adapter expects {self.output_sample_rate} Hz ({mime_type})")

    async def _speaker_changed(self, agent: str) -> None:
        """Report a speaker change and the roster when it grows."""
        if agent == self._speaker:
            return
        data: dict[str, Any] = {"agent": agent, "previous_agent": self._speaker}
        if self._speaker is None or agent not in self._roster:
            if agent not in self._roster:
                self._roster.append(agent)
            data["agents"] = list(self._roster)
        self._speaker = agent
        await self._callback("agent_changed", data)

    async def _refuse_confirmation(self, event: Event) -> None:
        """Fail the connection when a tool needs human confirmation."""
        names = sorted({response.name for response in event.get_function_responses() if response.name}) or ["a tool"]
        await self._callback(
            "error", {"message": f"Tool(s) {', '.join(names)} of agent '{event.author}' require confirmation, which a realtime session cannot get"}
        )

    async def append_audio(self, base64_audio: str) -> None:
        if self._queue is not None:
            self._queue.send_realtime(types.Blob(data=base64.b64decode(base64_audio), mime_type=f"audio/pcm;rate={self.input_sample_rate}"))

    async def send_text(self, text: str) -> None:
        if self._queue is not None:
            self._queue.send_content(types.Content(role="user", parts=[types.Part(text=text)]))
            self._awaiting_model_since = time.monotonic()
            self._awaiting_speech_since = time.monotonic()
            self._stall_restarts = 0
            self._speech_restarts = 0
            self._handover_pending = False
            self._handover_to = None

    async def disconnect(self) -> None:
        self._closing = True
        queue, self._queue = self._queue, None
        if queue is not None:
            queue.close()
        watch, self._watch_task = self._watch_task, None
        await self._cancel_and_wait(watch)
        task, self._listen_task = self._listen_task, None
        await self._cancel_and_wait(task)
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.close()
        ctx, self._tool_context = self._tool_context, None
        if ctx is not None:
            ctx.__exit__(None, None, None)


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
        "live_request_queue": "the realtime runner owns the one queue of the conversation",
        "session": "the GoogleADKSession stored on the Agent Kernel session",
    }

    def __init__(self, name: str, runner: GoogleADKRunner, agent: BaseAgent | Workflow, realtime_runner_cls: type[BaseRealtimeRunner] | None = None):
        """
        Initializes a GoogleADKAgent instance.
        :param name: Name of the agent.
        :param runner: BaseRunner associated with the agent.
        :param agent: The Google ADK agent instance.
        :param realtime_runner_cls: Optional realtime runner class for this agent.
        """
        super().__init__(name, runner, realtime_runner_cls)
        self._agent = agent
        if AKConfig.get().execution.mode != ExecutionMode.REALTIME:
            self._attach_system_tools()
            self._setup_system_prompt()

    @property
    def agent(self) -> BaseAgent | Workflow:
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

    def __init__(
        self, agents: list[BaseAgent | Workflow], runner: GoogleADKRunner = None, realtime_runner_cls: type[BaseRealtimeRunner] | None = None
    ):
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

    def _wrap(self, agent: BaseAgent | Workflow, agents: List[BaseAgent | Workflow]) -> AKBaseAgent:
        """
        Wraps the provided agent in a GoogleADKAgent instance.
        :param agent: The agent to wrap.
        :param agents: List of agents in the module.
        :return: GoogleADKAgent instance.
        """
        # The realtime runner class is attached unconditionally; only the pipeline (in REALTIME
        # mode) ever instantiates it, so the framework need not know the execution mode.
        return GoogleADKAgent(agent.name, self.runner, agent, realtime_runner_cls=self.realtime_runner_cls)

    def load(self, agents: list[BaseAgent | Workflow]) -> "GoogleADKModule":
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
