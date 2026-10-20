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
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, List, Literal, Mapping
from uuid import uuid4

from google.adk.agents import BaseAgent, LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.events import Event, EventActions
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.plugins import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, State
from google.adk.tools import BaseTool, FunctionTool, ToolContext
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
    """Runs a live call on ADK's own live engine (``Runner.run_live``) behind the realtime pool.

    ADK runs the conversation: its tools with their plugin and agent callbacks, its transfers (a new Live socket
    for the agent taking the call, given the conversation) and its session history. This feeds the caller's audio
    and text to ADK's ``LiveRequestQueue``, opens Agent Kernel's tool scope for each tool ADK runs, and reports
    ADK's events through the pool's callback. ADK resumes a dropped socket itself when the call's ``RunConfig``
    asks for session resumption; a live run that ends anyway, or stops answering, is started again on the same
    ADK session, so the agent that had the call carries on with the conversation so far.
    """

    input_sample_rate = 16000
    runs_tools = True
    APP_NAME = "AgentKernel"
    # Starting the live run again after it failed: attempts, and the wait before each.
    RESTART_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
    # A restarted run lost again this soon counts as a failed restart, not a fresh drop: after as many of those in a
    # row as there are delays the runner gives up. A service that accepts a connection and then closes it (out of
    # quota, failing) would otherwise be reconnected forever.
    QUICK_DROP_SECONDS: float = 20.0
    # A live run that answers nothing this long after it was given something to answer is taken for dead, checked
    # this often. Not while a tool runs: ADK reads nothing from the socket until its tools have returned. Live,
    # Gemini took 15 s or more to answer a tool's result and was restarted just before it spoke.
    STALL_SECONDS: float = 25.0
    STALL_CHECK_SECONDS: float = 1.0
    # Said into a restarted run, so the agent can tell the caller; "" says nothing. The first when the caller spoke
    # while the line was down, the second when they did not, so they are not asked to repeat what they never said.
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
    # Caller audio sent while the line is down, louder than this (the RMS of 16-bit samples, about -36 dBFS) in any
    # chunk, is taken for speech.
    SPEECH_LEVEL: int = 500

    class _ToolScope(BasePlugin):
        """Opens Agent Kernel's tool scope for each tool ADK runs, before any other plugin or the agent's callbacks."""

        def __init__(self, runner: "GoogleADKRealtimeRunner"):
            super().__init__(name="agentkernel_tool_scope")
            self._runner = runner

        async def before_tool_callback(self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext) -> None:
            await self._runner._enter_tool(tool.name, tool_context.agent_name)

        async def after_tool_callback(self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext, result: Any) -> None:
            self._runner._log.info(f"Tool {tool.name} of '{tool_context.agent_name}' returned: {str(result)[:200]}")

        async def on_tool_error_callback(self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext, error: Exception) -> None:
            self._runner._log.warning(f"Tool {tool.name} of '{tool_context.agent_name}' failed: {error!r}")

    def __init__(self):
        super().__init__(FRAMEWORK)
        self._log = logging.getLogger("ak.adk.realtime")
        self._callback: Callable | None = None
        self._runner: Runner | None = None
        self._session_id: str | None = None
        self._run_config: RunConfig | None = None
        self._queue: LiveRequestQueue | None = None
        # The task keeping a live run going (restarting it when it fails), the live run itself, and the stall watch.
        self._supervisor: asyncio.Task | None = None
        self._live: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._closing = False
        # Set when the watchdog stops a live run, naming why; any other cancellation of a run is the call closing.
        self._stalled: str | None = None
        # The agent with the call, by name.
        self._active: str | None = None
        # Per-turn state: whether the model is speaking, whether this turn was cut off, and whether the caller's
        # current turn has been reported (``speech_started`` or ``interrupt``).
        self._model_speaking = False
        self._interrupted_this_turn = False
        self._caller_turn_reported = False
        # The tools ADK is running, and since when (time.monotonic()) the run owes an answer: to the caller's turn,
        # text sent to it, or a tool's result.
        self._tools_running = 0
        self._owed_since: float | None = None
        # When the caller last finished a turn, and when the model last said anything (time.monotonic()).
        self._caller_said_at: float | None = None
        self._model_said_at: float | None = None
        # Whether the line is down (a run being restarted), whether the caller spoke meanwhile, and, for a restarted run
        # not yet heard from, when the line was lost: it is reported back only once the new run sends something.
        self._down = False
        self._heard_while_down = False
        self._lost_at: float | None = None

    @staticmethod
    def _transfer_targets(sdk_agent: Any) -> list[Any]:
        """The agents ``sdk_agent`` may transfer to by ADK's rules: sub-agents, parent and peers, minus those ADK disallows."""
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

    def team(self, agent: AKBaseAgent) -> list[str]:
        """Every agent the conversation can reach through transfers, the starting agent first."""
        root = getattr(agent, "agent", None)
        if root is None:
            return [agent.name]
        reached, seen = [root], {id(root)}
        for member in reached:
            for target in self._transfer_targets(member):
                if id(target) not in seen:
                    seen.add(id(target))
                    reached.append(target)
        return [member.name for member in reached]

    @staticmethod
    def _live_run_config(agent: AKBaseAgent) -> RunConfig:
        """The call's ``RunConfig``: the starting agent's ``run_config`` run option, with the transcriptions the pool
        reports (the caller's words, the agents' transcript) turned on unless it configures them."""
        declared = (getattr(agent, "run_options", None) or {}).get("run_config")
        run_config = declared.model_copy() if declared is not None else RunConfig()
        run_config.response_modalities = run_config.response_modalities or [types.Modality.AUDIO]
        run_config.input_audio_transcription = run_config.input_audio_transcription or types.AudioTranscriptionConfig()
        run_config.output_audio_transcription = run_config.output_audio_transcription or types.AudioTranscriptionConfig()
        return run_config

    async def connect(self, session: Session, agent: AKBaseAgent, callback: Callable) -> None:
        """Start the call's live run on ADK, in an ADK session of this connection's own, for the agent the call starts with."""
        self._callback = callback
        root = agent.agent
        self._active = root.name
        self._session_id = session.id
        session_service = InMemorySessionService()
        await session_service.create_session(app_name=self.APP_NAME, user_id=self.APP_NAME, session_id=session.id)
        # The starting agent's Runner options (its plugins, services), as GoogleADKRunner passes them; the tool scope
        # plugin runs first, so the application's plugins run inside it too.
        declared, _ = GoogleADKRunner._split_run_options(getattr(agent, "run_options", None) or {})
        plugins = [self._ToolScope(self), *(declared.pop("plugins", None) or [])]
        self._runner = Runner(app_name=self.APP_NAME, agent=root, session_service=session_service, plugins=plugins, **declared)
        self._run_config = self._live_run_config(agent)
        self._queue = LiveRequestQueue()
        self._supervisor = asyncio.create_task(self._supervise())
        self._watchdog = asyncio.create_task(self._watch_for_stalls())

    async def _supervise(self) -> None:
        """Keep the call's live run going: start it, and start it again when it fails, until the call closes."""
        restarted_at: float | None = None
        quick_drops = 0
        try:
            while not self._closing:
                self._live = asyncio.create_task(self._run_live())
                await asyncio.wait({self._live})
                if self._closing:
                    return
                failure = self._failure(self._live)
                if failure is None:
                    return
                lost_at = time.monotonic()
                quick_drops = quick_drops + 1 if restarted_at is not None and lost_at - restarted_at < self.QUICK_DROP_SECONDS else 0
                if not await self._restart(failure, quick_drops, lost_at):
                    return
                restarted_at = time.monotonic()
        finally:
            await self._cancel_and_wait(self._live)

    def _failure(self, live: asyncio.Task) -> str | None:
        """Why a live run ended, if it failed; ``None`` for a run the call's closing cancelled."""
        stalled, self._stalled = self._stalled, None
        if live.cancelled():
            return stalled
        error = live.exception()
        return f"socket error: {error!r}" if error is not None else "the live run ended"

    async def _run_live(self) -> None:
        async with contextlib.aclosing(
            self._runner.run_live(user_id=self.APP_NAME, session_id=self._session_id, live_request_queue=self._queue, run_config=self._run_config)
        ) as events:
            async for event in events:
                await self._report(event)

    async def _restart(self, reason: str, quick_drops: int, lost_at: float) -> bool:
        """Start the live run again for the agent that had the call, after the turn under way ended; whether it was started."""
        self._log.warning(f"Gemini Live run of '{self._active}' lost ({reason}); restarting it")
        # A restart that failed before its run said anything keeps what was heard since the line first went down.
        self._heard_while_down = (self._down and self._heard_while_down) or self._caller_spoke_unanswered()
        self._down = True
        self._owed_since = None
        self._end_turn()
        await self._callback("done", {"status": "reconnecting"})
        if quick_drops >= len(self.RESTART_DELAYS_SECONDS):
            self._log.error(f"Gemini Live lost again within {self.QUICK_DROP_SECONDS:.0f} s of restarting, {quick_drops} times in a row")
            await self._callback("error", {"message": f"Gemini Live keeps dropping ({reason}); not reconnecting"})
            return False
        await asyncio.sleep(self.RESTART_DELAYS_SECONDS[quick_drops])
        if self._closing:
            return False
        seconds = max(1, round(time.monotonic() - lost_at))
        note = (self.RECONNECTED_NOTE if self._heard_while_down else self.RECONNECTED_QUIET_NOTE).format(seconds=seconds)
        if note:
            # Held by ADK's queue until the new run's socket is open.
            self._queue.send_content(types.Content(role="user", parts=[types.Part(text=note)]))
            self._owed_since = time.monotonic()
        # Not reported back yet: ADK says nothing when it opens a socket, so the new run's first event is what says it is up.
        self._lost_at = self._lost_at if self._lost_at is not None else lost_at
        self._log.info(f"Restarting the Gemini Live run of '{self._active}'")
        return True

    async def _report_back(self) -> None:
        """The restarted run sent its first event: the line is back."""
        lost_at, self._lost_at = self._lost_at, None
        self._down = False
        seconds = max(1, round(time.monotonic() - lost_at))
        self._log.info(f"Restarted the Gemini Live run of '{self._active}' after {seconds} s")
        await self._callback("reconnected", {"agent": self._active, "seconds": seconds, "seeded": True})

    def _caller_spoke_unanswered(self) -> bool:
        """Whether the caller had said something the model had not answered when the line dropped."""
        said, answered = self._caller_said_at, self._model_said_at
        return said is not None and (answered is None or said > answered)

    async def _watch_for_stalls(self) -> None:
        """Stop a live run that has answered nothing for ``STALL_SECONDS`` since it was given something to answer."""
        while not self._closing:
            await asyncio.sleep(self.STALL_CHECK_SECONDS)
            owed = self._owed_since
            live = self._live
            if owed is not None and not self._tools_running and live is not None and not live.done():
                if time.monotonic() - owed > self.STALL_SECONDS:
                    self._owed_since = None
                    self._stalled = f"no answer from Gemini in {self.STALL_SECONDS:.0f} s"
                    live.cancel()

    async def _enter_tool(self, name: str = "", agent: str | None = None) -> None:
        """A tool ADK runs starts: open the pool's tool scope on the task running it, and count it until that task ends."""
        task = asyncio.current_task()
        if task is None or task is self._live:
            # The scope lasts until its task ends: on the live run's own task it would hold the session for the call.
            raise RuntimeError("ADK ran a realtime tool call on its live run's own task; this ADK version is not supported")
        self._log.info(f"Tool {name} called by '{agent or self._active}'")
        self._tools_running += 1
        self._owed_since = None
        task.add_done_callback(self._exit_tool)
        if self._open_tool_scope is not None:
            await self._open_tool_scope()

    def _exit_tool(self, task: asyncio.Task) -> None:
        self._tools_running -= 1
        if not task.cancelled():
            # The model owes an answer to the result, which ADK sends it now.
            self._owed_since = time.monotonic()

    async def _report(self, event: Event) -> None:
        """Report one of ADK's live events through the pool's callback, in the order ADK produced them."""
        if self._lost_at is not None:
            await self._report_back()
        author = event.author
        if author not in (None, "user") and author != self._active:
            # The agent answering changed without a transfer this run reported: a restarted run resumed another agent.
            await self._agent_changed(author)

        if event.input_transcription is not None and event.input_transcription.text:
            await self._caller_words(event.input_transcription.text, finished=not event.partial)

        if event.interrupted:
            self._owed_since = None
            if not self._interrupted_this_turn:
                self._interrupted_this_turn = True
                self._model_speaking = False
                self._caller_turn_reported = True
                self._log.info("Gemini barge-in (server interruption); stopping playback")
                await self._callback("interrupt", {})

        if event.output_transcription is not None and event.output_transcription.text and event.partial:
            # ADK repeats a turn's whole transcript once it is finished, unpartial: only the parts are new.
            self._caller_turn_reported = False
            self._owed_since = self._model_said_at = time.monotonic()
            await self._callback("transcript_delta", {"delta": event.output_transcription.text, "message_id": ""})

        for part in (event.content.parts or []) if event.content is not None and author != "user" else []:
            inline = part.inline_data
            if inline is not None and inline.data and (inline.mime_type or "").startswith("audio/"):
                self._model_speaking = True
                self._caller_turn_reported = False
                self._owed_since = self._model_said_at = time.monotonic()
                await self._callback("audio_delta", {"delta": base64.b64encode(inline.data).decode("utf-8"), "message_id": ""})

        if event.get_function_calls():
            # The model answered with calls, acting on the caller's words; it owes a reply again once ADK sends their
            # results. Live, a run that stalled after recording what the caller said asked them to say it again.
            self._owed_since = None
            self._model_said_at = time.monotonic()

        target = event.actions.transfer_to_agent if event.get_function_responses() else None
        if target and target != self._active:
            self._end_turn()
            await self._callback("done", {"status": "transferred"})
            await self._agent_changed(target)

        if event.turn_complete:
            self._owed_since = None
            self._end_turn()
            await self._callback("done", {"status": "completed"})

    async def _caller_words(self, text: str, finished: bool) -> None:
        """The caller's words, as Gemini transcribes them: a barge-in while the model speaks, else the start of their
        turn or more of it, and the whole turn once it is finished."""
        if self._down and text.strip():
            self._heard_while_down = True
        if self._model_speaking and not self._interrupted_this_turn:
            self._interrupted_this_turn = True
            self._model_speaking = False
            self._caller_turn_reported = True
            self._owed_since = None
            self._log.info("Gemini barge-in (user speaking); stopping playback")
            await self._callback("interrupt", {})
        elif not self._model_speaking and not self._caller_turn_reported:
            self._caller_turn_reported = True
            await self._callback("speech_started", {})
        elif not self._model_speaking:
            await self._callback("speech_heard", {})
        if finished and text.strip():
            self._log.info(f"Caller said: {text.strip()}")
            self._owed_since = self._caller_said_at = time.monotonic()
            await self._callback("caller_transcript", {"text": text.strip()})

    async def _agent_changed(self, target: str) -> None:
        previous, self._active = self._active, target
        self._log.info(f"Transferring from '{previous}' to '{target}'")
        await self._callback("agent_changed", {"agent": target, "previous_agent": previous})

    def _end_turn(self) -> None:
        self._model_speaking = False
        self._interrupted_this_turn = False
        self._caller_turn_reported = False

    async def append_audio(self, base64_audio: str) -> None:
        """Send the caller's audio to ADK's queue, which holds it while no socket is open."""
        if self._queue is None or self._closing:
            return
        pcm = base64.b64decode(base64_audio)
        if self._down and not self._heard_while_down and self._is_speech(pcm):
            self._heard_while_down = True
        self._queue.send_realtime(types.Blob(data=pcm, mime_type=f"audio/pcm;rate={self.input_sample_rate}"))

    def _is_speech(self, pcm: bytes) -> bool:
        samples = array("h", pcm[: len(pcm) - len(pcm) % 2])
        return bool(samples) and math.sqrt(sum(sample * sample for sample in samples) / len(samples)) > self.SPEECH_LEVEL

    async def send_text(self, text: str) -> None:
        """Send a user text turn through ADK's queue, which records it in the conversation and sends it as each Live model takes text."""
        if self._queue is None or self._closing:
            return
        self._queue.send_content(types.Content(role="user", parts=[types.Part(text=text)]))
        # A wait already running is kept: only the model's progress moves it, so text sent every so often to a run that
        # has stopped answering does not keep it from being taken for stalled.
        if self._owed_since is None:
            self._owed_since = time.monotonic()

    async def disconnect(self) -> None:
        self._closing = True
        watchdog, self._watchdog = self._watchdog, None
        supervisor, self._supervisor = self._supervisor, None
        await self._cancel_and_wait(watchdog)
        if self._queue is not None:
            self._queue.close()
        await self._cancel_and_wait(supervisor)
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.close()


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
