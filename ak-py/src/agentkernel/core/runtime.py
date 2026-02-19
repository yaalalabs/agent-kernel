from __future__ import annotations

import importlib
import logging
from threading import RLock
from types import ModuleType
from typing import Optional

from deprecated import deprecated
from singleton_type import Singleton

from ..core.util.key_value_cache import KeyValueCache
from ..guardrail.guardrail import InputGuardrailFactory, OutputGuardrailFactory
from .base import Agent, Session
from .builder import SessionStoreBuilder
from .config import AKConfig
from .model import (
    AgentReply,
    AgentReplyImage,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from .multimodal import MultimodalPreHookFactory
from .session import SessionStore


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    _current: Optional[Runtime] = None
    _lock: RLock = RLock()
    _system_pre_hooks: list = [InputGuardrailFactory.get(), MultimodalPreHookFactory.get()]
    _system_post_hooks: list = [OutputGuardrailFactory.get()]

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

    async def run(self, agent: Agent, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the specified agent with the multi-modal requests.

        Note that the volatile cache is cleared after execution, including when the execution is halted by a hook.
        On successful completion, the session stored is updated.

        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The multi-modal inputs are provided to the agent.  It will be submitted to the agent as a single request
                        AgentRequestText objects will be concatenated into a single text prompt.
                        AgentRequestAny is handled only by pre-hooks, not by the agent itself
        :return: The result of the agent's execution.
        """
        async with session:
            try:
                self._log.debug(f"Executing pre hooks with agent '{agent.name}' and requests: {requests}")

                pre_hooks = agent.pre_hooks + self._system_pre_hooks  # system pre-hooks are always executed last
                for hook in pre_hooks:
                    reply = await hook.on_run(session, agent, requests)
                    if isinstance(reply, (AgentReplyText, AgentReplyImage)):
                        self._log.debug(f"PreHook halted execution for agent '{agent.name}' by hook '{hook.name()}' with reply: {reply}")
                        return reply

                    # Validation to ensure the correct type is returned from the hooks. This is important to avoid runtime errors.
                    if isinstance(reply, list):
                        for item in reply:
                            if not isinstance(item, (AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny)):
                                raise TypeError(
                                    f"PreHook '{hook.name()}' returned an invalid type in the requests list. Expected AgentRequest, got {type(item)}"
                                )
                    else:
                        raise TypeError(f"PreHook '{hook.name()}' returned an invalid type. Expected list[AgentRequest], got {type(reply)}")
                    requests = reply

                self._log.debug(f"Running agent '{agent.name}' with requests: {requests}")

                reply = await agent.runner.run(agent, session, requests)

                post_hooks = self._system_post_hooks + agent.post_hooks  # system post-hooks are always executed first
                for hook in post_hooks:
                    reply = await hook.on_run(session, requests, agent, reply)
                    if not isinstance(reply, (AgentReplyText, AgentReplyImage)):
                        raise TypeError(f"PostHook '{hook.name()}' returned an invalid type. Expected AgentReply, got {type(reply)}")
                    self._log.debug(f"PostHook executed for agent '{agent.name}' by hook '{hook.name()}' reply: {reply}")

                self.sessions().store(session)
                return reply
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


@deprecated(
    version="0.2.12",
    reason="Access to the current session is now possible with Session.current(). Access to a given session in the current runtime is possible with Runtime.current().sessions().load(session_id). Once the session is accessible, its caches can be accessed via get_volatile_cache() and get_non_volatile_cache() methods.",
)
class AuxiliaryCache:
    """
    AuxiliaryCache provides access to volatile and non-volatile key-value caches associated with
    the current or a provided session.

    .. deprecated:: 0.2.12
        Access to the current session is now possible with Session.current(). Access to a given
        session in the current runtime is possible with Runtime.current().sessions().load(session_id).
        Once the session is accessible, its caches can be accessed via get_volatile_cache() and
        get_non_volatile_cache() methods.
    """

    @staticmethod
    @deprecated(
        version="0.2.12",
        reason="Use Session.current().get_volatile_cache() or Runtime.current().sessions().load(session_id).get_volatile_cache() instead.",
    )
    def get_volatile_cache(session_id: str | None = None) -> KeyValueCache:
        """
        Retrieves the volatile key-value cache associated with the provided session.
        :param session_id: The session to retrieve the volatile cache for. If not provided, the current session is used to find the session
        :return: The volatile key-value cache.

        .. deprecated:: 0.2.12
            Use Session.current().get_volatile_cache() or Runtime.current().sessions().load(session_id).get_volatile_cache() instead.
        """
        session = Runtime.current().sessions().load(session_id) if session_id else Session.current()
        if session is None:
            raise Exception("No current or matching session available to retrieve volatile cache.")

        return session.get_volatile_cache()

    @staticmethod
    @deprecated(
        version="0.2.12",
        reason="Use Session.current().get_non_volatile_cache() or Runtime.current().sessions().load(session_id).get_non_volatile_cache() instead.",
    )
    def get_non_volatile_cache(session_id: str | None = None) -> KeyValueCache:
        """
        Retrieves the non-volatile key-value cache associated with the provided session.
        :param session_id: The session to retrieve the non-volatile cache for. If not provided, the current session is used to find the session
        :return: The non-volatile key-value cache.

        .. deprecated:: 0.2.12
            Use Session.current().get_non_volatile_cache() or Runtime.current().sessions().load(session_id).get_non_volatile_cache() instead.
        """
        session = Runtime.current().sessions().load(session_id) if session_id else Session.current()
        if session is None:
            raise Exception("No current or matching session available to retrieve non-volatile cache.")
        return session.get_non_volatile_cache()
