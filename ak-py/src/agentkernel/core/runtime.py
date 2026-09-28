from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncGenerator
from threading import RLock
from types import ModuleType
from typing import Optional

from singleton_type import Singleton

from ..guardrail.guardrail import InputGuardrailFactory, OutputGuardrailFactory
from ..sandbox.hooks import SandboxPreHookFactory
from .base import Agent, Session
from .builder import SessionStoreBuilder
from .event import MessageEnd, ReasoningEnd, RunPaused, StepEnd, StreamEvent, TextDelta, ToolCallEnd
from .hooks import StreamHalt
from .model import (
    AgentPausedReplyAny,
    AgentReply,
    AgentReplyAny,
    AgentReplyImage,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestAttachmentRef,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    StreamChunk,
)
from .multimodal import MultimodalPreHookFactory
from .paused_run import PausedRun, PausedRunState
from .session import SessionStore

# Volatile-cache key under which the run's acting user is published, so hooks and tools can read
# who the request was made on behalf of without threading user_id through every call.
ACTING_USER_CACHE_KEY = "ak.acting_user_id"


class StreamBoundaryTracker:
    """
    Remembers which paired events a streamed run has left open, and how to close them.

    Several of the events in `event.py` come in pairs: a `MessageStart` is closed by a `MessageEnd`, a
    `ToolCallStart` by a `ToolCallEnd`. A post-hook can end a run part-way through such a pair by
    raising `StreamHalt`, which would otherwise leave the client holding something that never closes —
    an AG-UI frontend renders an unclosed tool call as work still in progress. `Runtime.stream` tracks
    what it has emitted so its halt path can emit the closes the stream still owes.

    Only events that were actually emitted are observed, never what the runner yielded, so a hook that
    holds, drops or injects a boundary cannot desynchronise the tracker from the client's view.

    Malformed sequences are tolerated rather than rejected: closing an id that was never opened is a
    no-op, and opening one twice keeps the later close. Validating a runner's event sequence is a wider
    contract question than this class, and raising mid-stream would turn a third-party adapter's bug
    into a failed run.

    Internal to `Runtime.stream`, and deliberately not exported from the package.
    """

    def __init__(self) -> None:
        self._open: dict[tuple[str, str], StreamEvent] = {}

    def observe(self, event: StreamEvent) -> None:
        """
        Records an emitted event, opening or closing the boundary it represents.

        The closing event is built when the boundary opens and stored against it, so `drain` needs no
        mapping from a boundary back to its event type. Events that open nothing are ignored.

        :param event: An event that has just been emitted to the client.
        """
        match event.type:
            case "message_start":
                self._open[("message", event.message_id)] = MessageEnd(message_id=event.message_id)
            case "message_end":
                self._open.pop(("message", event.message_id), None)
            case "reasoning_start":
                self._open[("reasoning", event.message_id)] = ReasoningEnd(message_id=event.message_id)
            case "reasoning_end":
                self._open.pop(("reasoning", event.message_id), None)
            case "tool_call_start":
                self._open[("tool", event.tool_call_id)] = ToolCallEnd(tool_call_id=event.tool_call_id)
            case "tool_call_end":
                self._open.pop(("tool", event.tool_call_id), None)
            case "step_start":
                self._open[("step", event.name)] = StepEnd(name=event.name)
            case "step_end":
                self._open.pop(("step", event.name), None)

    def drain(self) -> list[StreamEvent]:
        """
        Returns the closing events for everything still open, innermost first, and forgets them.

        Insertion order is the order the boundaries opened, so reversing it closes the innermost
        boundary first — a tool call opened inside a message is closed before the message. The tracker
        is emptied, since a halted run emits these once and then ends.

        :return: The closing events the run still owes its client, innermost first.
        """
        closes = list(reversed(self._open.values()))
        self._open.clear()
        return closes


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _current: Optional[Runtime] = None
    _lock: RLock = RLock()
    # System hooks are built on first use, not at import time, because the
    # factories read AKConfig and importing agentkernel must not load it.
    _system_pre_hooks: Optional[list] = None
    _system_post_hooks: Optional[list] = None

    @classmethod
    def _get_system_pre_hooks(cls) -> list:
        if Runtime._system_pre_hooks is None:
            with Runtime._lock:
                if Runtime._system_pre_hooks is None:
                    Runtime._system_pre_hooks = [InputGuardrailFactory.get(), MultimodalPreHookFactory.get(), SandboxPreHookFactory.get()]
        return Runtime._system_pre_hooks

    @classmethod
    def _get_system_post_hooks(cls) -> list:
        if Runtime._system_post_hooks is None:
            with Runtime._lock:
                if Runtime._system_post_hooks is None:
                    Runtime._system_post_hooks = [OutputGuardrailFactory.get()]
        return Runtime._system_post_hooks

    def __init__(self, sessions: SessionStore):
        """
        Initialize the Runtime.

        :param sessions: The session store instance is used to manage agent sessions.
        """
        self._log = logging.getLogger("ak.runtime")
        self._agents = {}
        self._sessions = sessions

    @staticmethod
    def current() -> Runtime:
        """
        Return the currently active Runtime instance. By default this is the
        global singleton Runtime instance.

        :return: The currently active runtime instance.
        """
        return Runtime._current or GlobalRuntime.instance()

    def __enter__(self) -> "Runtime":
        """
        Enter the Runtime context manager and set as the current Runtime.

        This method is called when entering a 'with' statement block. It sets
        this runtime instance as the active runtime context.

        :return: The runtime instance itself, allowing it to be used as a context manager in with statements.
        """
        with Runtime._lock:
            if Runtime._current is not None and Runtime._current != self:
                raise Exception("A different runtime is already active")
            Runtime._current = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit the Runtime context manager and clear the current Runtime.

        This method is called when exiting a 'with' statement block. It clears
        the runtime instance from being the active runtime, performing necessary cleanup.
        """
        with Runtime._lock:
            if Runtime._current is not None and Runtime._current != self:
                raise Exception("A different runtime is currently active")
            Runtime._current = None

    def load(self, module: str) -> ModuleType:
        """
        Loads an agent module dynamically.
        :param module: Name of the module to load.
        :return: The loaded module.

        :raises ModuleNotFoundError: If the specified module cannot be found.
        :raises ImportError: If there's an error during the module import process.
        """
        self._log.debug(f"Loading module '{module}'")
        with self:
            return importlib.import_module(module)

    def agents(self) -> dict[str, Agent]:
        """
        Returns the list of registered agents.
        :return: List of agents.
        """
        return self._agents

    def register(self, agent: Agent) -> None:
        """
        Registers an agent in the runtime.
        :param agent: The agent to register.
        """
        if not self._agents.get(agent.name):
            self._log.debug(f"Registering agent '{agent.name}'")
            self._agents[agent.name] = agent
        else:
            raise Exception(f"Agent with name '{agent.name}' is already registered.")

    def deregister(self, agent: Agent) -> None:
        """
        Deregisters an agent from the runtime.
        :param agent: The agent to deregister.
        """
        if self._agents.get(agent.name):
            self._log.debug(f"Deregistering agent '{agent.name}'")
            del self._agents[agent.name]
        else:
            self._log.warning(f"Agent with name '{agent.name}' is not registered.")

    async def _prepare_requests(
        self,
        agent: Agent,
        session: Session,
        requests: list[AgentRequest],
    ) -> list[AgentRequest] | AgentReply:
        """
        Runs the shared pre-hook pipeline and validates hook responses.

        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The requests to pass through the pre-hook chain.
        :return: A potentially modified request list, or a reply that halts execution.
        """
        self._log.debug(f"Executing pre hooks with agent '{agent.name}' and requests: {requests}")

        pre_hooks = agent.pre_hooks + self._get_system_pre_hooks()  # system pre-hooks are always executed last
        for hook in pre_hooks:
            reply = await hook.on_run(session, agent, requests)
            if isinstance(reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                return reply

            # Validation to ensure the correct type is returned from the hooks. This is important to avoid runtime errors.
            if isinstance(reply, list):
                for item in reply:
                    if not isinstance(
                        item,
                        (AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny, AgentRequestAttachmentRef, AgentResumeRequestAny),
                    ):
                        raise TypeError(
                            f"PreHook '{hook.name()}' returned an invalid type in the requests list. Expected AgentRequest, got {type(item)}"
                        )
            else:
                raise TypeError(f"PreHook '{hook.name()}' returned an invalid type. Expected list[AgentRequest], got {type(reply)}")
            requests = reply

        return requests

    @staticmethod
    def _extract_resume(requests: list[AgentRequest]) -> Optional[AgentResumeRequestAny]:
        """
        Returns the resume request in a request list, or None when it carries no decisions.
        :param requests: The request list to inspect.
        :return: The first AgentResumeRequestAny in the list, or None.
        """
        return next((req for req in requests if isinstance(req, AgentResumeRequestAny)), None)

    def _validate_resume(self, agent: Agent, session: Session, resume: AgentResumeRequestAny) -> tuple[Agent, PausedRun]:
        """
        Resolves and validates the paused run a resume request answers, before anything acts on it.

        Runs here rather than in the adapter because every adapter wraps its body in one `except
        Exception` that returns a text reply, so a failure raised inside would surface as a generic
        error instead of naming what went wrong. These four checks also need no framework knowledge,
        so an adapter-side implementation would be written four times.

        :param agent: The agent named on the request, used only to reject a conflicting one.
        :param session: The session holding the paused-run records.
        :param resume: The decisions to validate.
        :return: The agent resolved from the record, and the record itself.
        :raises ValueError: If no run matches, a decision names an unknown interruption, the named
            agent disagrees with the record, or the record's agent is no longer registered.
        """
        decision_ids = [decision.id for decision in resume.decisions]
        record = PausedRunState.get(session, resume.run_id) if resume.run_id else PausedRunState.find_by_interruption(session, decision_ids)
        if record is None:
            held = len(PausedRunState.list(session))
            raise ValueError(
                f"No paused run in session '{session.id}' matches this resume "
                f"(run_id={resume.run_id!r}, decisions={decision_ids}); the session holds {held}. "
                f"A run_id that disagrees with its decisions, and decisions spanning two runs, fail the same way."
            )
        known = {interruption.id for interruption in record.interruptions}
        unknown = sorted(set(decision_ids) - known)
        if unknown:
            raise ValueError(f"Resume for run '{record.id}' names unknown interruption(s): {unknown}. The run is waiting on: {sorted(known)}")

        if agent.name != record.agent:
            raise ValueError(
                f"Resume names agent '{agent.name}' but paused run '{record.id}' belongs to '{record.agent}'. "
                f"The agent is resolved from the record; an explicit one that disagrees is an error, not an override."
            )

        resolved = self.agents().get(record.agent)
        if resolved is None:
            raise ValueError(f"Paused run '{record.id}' belongs to agent '{record.agent}', which is no longer registered.")
        if not resolved.runner.supports_pause:
            raise ValueError(f"Runner '{resolved.runner.name}' for agent '{resolved.name}' does not support resuming a paused run.")
        return resolved, record

    def _clear_leftover_record(self, session: Session, record: PausedRun, paused_again: bool) -> None:
        """
        Removes a record a resumed run left behind, rather than warning that the adapter forgot it.

        Clearing is otherwise the adapter's, because a resume can pause again and the adapter writes
        the new record. Narrowed to a run that did *not* pause again, no new record is in play, so
        one still present can only be the resumed one — and removing it means the next turn cannot
        inherit a phantom pause.

        :param session: The session holding the record.
        :param record: The record that was resumed.
        :param paused_again: Whether the resumed run produced another pause.
        """
        if paused_again:
            return
        if PausedRunState.get(session, record.id) is None:
            return
        self._log.debug(f"Session '{session.id}': clearing paused run '{record.id}' left behind by a resumed run.")
        PausedRunState.clear(session, record.id)

    def _warn_resume_dropped(self, agent: Agent, session: Session) -> None:
        """
        Warns that a pre-hook removed the decisions, so this run proceeds as an ordinary turn.
        :param agent: The agent the run was for.
        :param session: The session whose pause is still open.
        """
        self._log.warning(
            f"Session '{session.id}', agent '{agent.name}': a resume decision was dropped by the pre-hook chain; "
            f"this run is proceeding as a new turn and the pause is still open."
        )

    def _warn_pause_dropped(self, agent: Agent, session: Session, hook_name: str) -> None:
        """
        Warns that a post-hook filtered a pause out of a stream, so the client was never told.

        The hook wins, as it does for any other event: Agent Kernel does not decide which event
        types a hook may filter. The paused run itself is untouched, so the decision is still
        answerable — the caller simply does not know it is owed.

        :param agent: The agent the run was for.
        :param session: The session whose pause is still open.
        :param hook_name: The post-hook that dropped the event.
        """
        self._log.warning(
            f"Session '{session.id}', agent '{agent.name}': a pause was dropped by post-hook '{hook_name}', "
            f"so the client will not learn a decision is owed. The paused run itself is untouched."
        )

    def _warn_resume_halted(self, agent: Agent, session: Session) -> None:
        """
        Warns that a pre-hook ended a resume before the decision reached the runner.

        The only halt with a durable consequence: every other costs a turn and leaves nothing
        behind, whereas this leaves a record in the store while the client receives a reply that
        reads like completion.

        :param agent: The agent the run was for.
        :param session: The session whose pause is still open.
        """
        self._log.warning(
            f"Session '{session.id}', agent '{agent.name}': a pre-hook halted a resume, so the decision was accepted "
            f"but never delivered. The paused run is untouched and can be answered again."
        )

    async def run(self, agent: Agent, session: Session, requests: list[AgentRequest], acting_user_id: Optional[str] = None) -> AgentReply:
        """
        Runs the specified agent with the multi-modal requests.

        Note that the volatile cache is cleared after execution, including when the execution is halted by a hook.
        On successful completion, the session stored is updated.

        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The multi-modal inputs are provided to the agent.  It will be submitted to the agent as a single request
                        AgentRequestText objects will be concatenated into a single text prompt.
                        AgentRequestAny is handled only by pre-hooks, not by the agent itself
        :param acting_user_id: When given, published under ACTING_USER_CACHE_KEY in the session's volatile
                        cache for the duration of this run, so hooks and tools can attribute work to the caller.
        :return: The result of the agent's execution.
        """
        async with session:
            try:
                if acting_user_id:
                    session.get_volatile_cache().set(ACTING_USER_CACHE_KEY, acting_user_id)
                with agent._activate():
                    arrived_with_resume = self._extract_resume(requests) is not None
                    requests_or_reply = await self._prepare_requests(agent, session, requests)
                    if isinstance(requests_or_reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                        self._log.debug(f"PreHook halted execution for agent '{agent.name}' by hook chain with reply: {requests_or_reply}")
                        if arrived_with_resume:
                            self._warn_resume_halted(agent, session)
                        return requests_or_reply
                    requests = requests_or_reply

                    resume = self._extract_resume(requests)
                    if arrived_with_resume and resume is None:
                        self._warn_resume_dropped(agent, session)

                    self._log.debug(f"Running agent '{agent.name}' with requests: {requests}")

                    if resume is not None:
                        agent, record = self._validate_resume(agent, session, resume)
                        reply = await agent.runner.resume(agent, session, requests, resume.decisions, record)
                        self._clear_leftover_record(session, record, isinstance(reply, AgentPausedReplyAny))
                    else:
                        reply = await agent.runner.run(agent, session, requests)

                    post_hooks = self._get_system_post_hooks() + agent.post_hooks  # system post-hooks are always executed first
                    for hook in post_hooks:
                        reply = await hook.on_run(session, requests, agent, reply)
                        if not isinstance(reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                            raise TypeError(f"PostHook '{hook.name()}' returned an invalid type. Expected AgentReply, got {type(reply)}")
                        self._log.debug(f"PostHook executed for agent '{agent.name}' by hook '{hook.name()}' reply: {reply}")

                    self.sessions().store(session)
                    return reply
            finally:
                session.get_volatile_cache().clear()

    async def stream(
        self, agent: Agent, session: Session, requests: list[AgentRequest], acting_user_id: Optional[str] = None
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Streams the specified agent response as StreamChunks carrying typed stream events.

        Pre-hooks run first; if halted, yields a StreamChunk with error and done=True.
        Every event the runner yields passes through the post-hook chain via on_stream_event(), which
        may pass it, rewrite it in place, drop it by returning None, or return a list to emit several
        events in its place; a returned list ends the chain for that event. Only TextDelta content is
        projected into `delta`, keeping reasoning out of consumers that concatenate it as the answer,
        and `delta` is taken from the event finally emitted so the two can never disagree. A hook
        raising StreamHalt ends the run: the closing event for any boundary the stream left open is
        emitted, then a single error chunk, and the session is not stored. Any other exception
        propagates unchanged. The volatile cache is cleared on exit.

        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The multi-modal inputs provided to the agent.
        :param acting_user_id: When given, published under ACTING_USER_CACHE_KEY in the session's volatile
                        cache for the duration of this run, so hooks and tools can attribute work to the caller.
        :return: An async generator of StreamChunk objects.
        """
        async with session:
            try:
                if acting_user_id:
                    session.get_volatile_cache().set(ACTING_USER_CACHE_KEY, acting_user_id)
                with agent._activate():
                    arrived_with_resume = self._extract_resume(requests) is not None
                    requests_or_reply = await self._prepare_requests(agent, session, requests)
                    if isinstance(requests_or_reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                        self._log.debug(f"PreHook halted streaming for agent '{agent.name}' by hook chain with reply: {requests_or_reply}")
                        if arrived_with_resume:
                            self._warn_resume_halted(agent, session)
                        yield StreamChunk(error=str(requests_or_reply), done=True)
                        return
                    requests = requests_or_reply

                    resume = self._extract_resume(requests)
                    if arrived_with_resume and resume is None:
                        self._warn_resume_dropped(agent, session)

                    self._log.debug(f"Streaming agent '{agent.name}' with requests: {requests}")

                    record = None
                    if resume is not None:
                        agent, record = self._validate_resume(agent, session, resume)
                        events = agent.runner.resume_stream(agent, session, requests, resume.decisions, record)
                    else:
                        events = agent.runner.stream(agent, session, requests)

                    post_hooks = self._get_system_post_hooks() + agent.post_hooks
                    boundaries = StreamBoundaryTracker()
                    paused = False

                    try:
                        async for ev in events:
                            for hook in post_hooks:
                                result = await hook.on_stream_event(session, requests, agent, ev)
                                if result is None:
                                    emitted: list[StreamEvent] = []
                                    break
                                if isinstance(result, list):
                                    emitted = result
                                    break
                                if result.type != ev.type:
                                    raise TypeError(
                                        f"PostHook '{hook.name()}' returned event type '{result.type}' for a '{ev.type}'. "
                                        "Return a list to emit a different type"
                                    )
                                ev = result
                            else:
                                emitted = [ev]

                            if isinstance(ev, RunPaused) and not emitted:
                                self._warn_pause_dropped(agent, session, hook.name())

                            for event in emitted:
                                if isinstance(event, RunPaused):
                                    paused = True
                                chunk = StreamChunk(delta=event.content if isinstance(event, TextDelta) else None, event=event)
                                boundaries.observe(event)
                                yield chunk

                            if paused:
                                # A pause is a valid outcome, not an invalidated partial, so the
                                # boundaries the stream left open are closed and the session is
                                # stored — unlike the StreamHalt path below.
                                for closing in boundaries.drain():
                                    yield StreamChunk(event=closing)
                                break

                        if record is not None:
                            self._clear_leftover_record(session, record, paused)

                        self.sessions().store(session)
                        yield StreamChunk(done=True)
                    except StreamHalt as halt:
                        self._log.warning(f"Stream halted for agent '{agent.name}': {halt.reason}")
                        for closing in boundaries.drain():
                            yield StreamChunk(event=closing)
                        yield StreamChunk(error=halt.reason, done=True)
            finally:
                session.get_volatile_cache().clear()

    def sessions(self) -> SessionStore:
        """
        Retrieves the session storage.
        :return: The session storage.
        """
        return self._sessions


class GlobalRuntime(Runtime, metaclass=Singleton):
    """
    GlobalRuntime is a singleton instance of Runtime that can be accessed globally.

    This is the default runtime instance used by all operations unless otherwise specified.
    """

    def __init__(self):
        """
        Initialize the global singleton Runtime instance based on the configuration.
        """
        sessions = SessionStoreBuilder.build()
        super().__init__(sessions)

    @staticmethod
    def instance() -> Runtime:
        """
        Get the global singleton instance of the Runtime.
        :return: The global singleton runtime instance.
        """
        return GlobalRuntime()
