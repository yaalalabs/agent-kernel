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
from .event import ReasoningDelta, TextDelta
from .model import (
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
    StreamChunk,
)
from .multimodal import MultimodalPreHookFactory
from .session import SessionStore

# Volatile-cache key under which the run's acting user is published, so hooks and tools can read
# who the request was made on behalf of without threading user_id through every call.
ACTING_USER_CACHE_KEY = "ak.acting_user_id"


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

    @staticmethod
    def ensure_agent_available(name: Optional[str]) -> None:
        """Check that a request naming ``name`` could be served, without selecting anything.

        The rule ``AgentHandler.initialize`` applies when it selects: a named agent must be
        registered, and an unnamed one needs at least one agent to default to. Surfaces that
        commit state before the agent ever runs — a thread write, a scheduled task — call this
        first, so a request that could never be answered fails while the caller is still
        listening instead of at run time.

        :param name: The requested agent name, or None for the default agent.
        :raises ValueError: If no matching agent is available.
        """
        agents = Runtime.current().agents()
        if (name and name not in agents) or (not name and not agents):
            raise ValueError("No agent available")

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
                    if not isinstance(item, (AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny, AgentRequestAttachmentRef)):
                        raise TypeError(
                            f"PreHook '{hook.name()}' returned an invalid type in the requests list. Expected AgentRequest, got {type(item)}"
                        )
            else:
                raise TypeError(f"PreHook '{hook.name()}' returned an invalid type. Expected list[AgentRequest], got {type(reply)}")
            requests = reply

        return requests

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
                    requests_or_reply = await self._prepare_requests(agent, session, requests)
                    if isinstance(requests_or_reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                        self._log.debug(f"PreHook halted execution for agent '{agent.name}' by hook chain with reply: {requests_or_reply}")
                        return requests_or_reply
                    requests = requests_or_reply

                    self._log.debug(f"Running agent '{agent.name}' with requests: {requests}")

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
        The runner's events pass through the post-hook chain via on_stream_chunk(), which sees
        text only: TextDelta and ReasoningDelta content reaches the hooks, and a hook's edit is
        written back into the event so `delta` and `event` never disagree. Returning None drops
        the chunk entirely, event included. Only TextDelta content is projected into `delta`,
        keeping reasoning out of consumers that concatenate it as the answer; every event still
        reaches `event`. The volatile cache is cleared on exit.

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
                    requests_or_reply = await self._prepare_requests(agent, session, requests)
                    if isinstance(requests_or_reply, (AgentReplyText, AgentReplyImage, AgentReplyAny)):
                        self._log.debug(f"PreHook halted streaming for agent '{agent.name}' by hook chain with reply: {requests_or_reply}")
                        yield StreamChunk(error=str(requests_or_reply), done=True)
                        return
                    requests = requests_or_reply

                    self._log.debug(f"Streaming agent '{agent.name}' with requests: {requests}")

                    post_hooks = self._get_system_post_hooks() + agent.post_hooks

                    async for ev in agent.runner.stream(agent, session, requests):
                        text = ev.content if isinstance(ev, (TextDelta, ReasoningDelta)) else None

                        if text is not None:
                            for hook in post_hooks:
                                text = await hook.on_stream_chunk(session, requests, agent, text)
                                if text is None:
                                    break
                            if text is None:
                                continue  # hook dropped the whole chunk, event included
                            if text != ev.content:
                                ev = ev.model_copy(update={"content": text})

                        yield StreamChunk(delta=text if isinstance(ev, TextDelta) else None, event=ev)

                    self.sessions().store(session)
                    yield StreamChunk(done=True)
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
