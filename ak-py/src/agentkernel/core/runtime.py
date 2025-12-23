import importlib
import logging
from threading import RLock
from types import ModuleType
from typing import Optional

from singleton_type import Singleton

from agentkernel.core.util.key_value_cache import KeyValueCache

from .base import Agent, Session
from .builder import SessionStoreBuilder
from .hooks import PostHook, PreHook
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
from .session import SessionStore


class Runtime:
    """
    Runtime class provides the environment for hosting and running agents.
    """

    def __init__(self, sessions: SessionStore):
        """
        Initialize the Runtime.

        :param sessions: The session store instance is used to manage agent sessions.
        """
        self._log = logging.getLogger("ak.runtime")
        self._agents = {}
        self._sessions = sessions
        self._pre_hooks: dict[str, list[PreHook]] = {}
        self._post_hooks: dict[str, list[PostHook]] = {}

    def __enter__(self) -> "Runtime":
        """
        Enter the Runtime context manager and attach the Runtime to the ModuleLoader.

        This method is called when entering a 'with' statement block. It attaches
        the ModuleLoader to this runtime instance, making it the active runtime
        context for module loading operations.

        :return: The runtime instance itself, allowing it to be used as a context manager in with statements.
        """
        ModuleLoader.attach(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit the Runtime context manager and detach from the ModuleLoader.

        This method is called when exiting a 'with' statement block. It detaches
        the runtime instance from the ModuleLoader, performing necessary cleanup.
        """
        ModuleLoader.detach(self)

    def load(self, module: str) -> ModuleType:
        """
        Loads an agent module dynamically.
        :param module: Name of the module to load.
        :return: The loaded module.
        """
        self._log.debug(f"Loading module '{module}'")
        return ModuleLoader.load(self, module)

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

        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The multi-modal inputs are provided to the agent.  It will be submitted to the agent as a single request
                        AgentRequestText objects will be concatenated into a single text prompt.
                        AgentRequestAny is handled only by pre-hooks, not by the agent itself
        :return: The result of the agent's execution.
        """
        self._log.debug(f"Executing pre hooks with agent '{agent.name}' and requests: {requests}")

        pre_hooks = agent.pre_hooks
        for hook in pre_hooks:
            reply = await hook.on_run(session, agent, requests)
            if isinstance(reply, (AgentReplyText, AgentReplyImage)):
                self._log.debug(
                    f"PreHook halted execution for agent '{agent.name}' by hook '{hook.name()}' with reply: {reply}"
                )
                return reply

            # Validation to ensure the correct type is returned from the hooks. This is important to avoid runtime errors.
            if isinstance(reply, list):
                for item in reply:
                    if not isinstance(item, (AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny)):
                        raise TypeError(
                            f"PreHook '{hook.name()}' returned an invalid type in the requests list. Expected AgentRequest, got {type(item)}"
                        )
            else:
                raise TypeError(
                    f"PreHook '{hook.name()}' returned an invalid type. Expected list[AgentRequest], got {type(reply)}"
                )
            requests = reply

        self._log.debug(f"Running agent '{agent.name}' with requests: {requests}")

        reply = await agent.runner.run(agent, session, requests)

        post_hooks = agent.post_hooks
        for hook in post_hooks:
            reply = await hook.on_run(session, requests, agent, reply)
            if not isinstance(reply, (AgentReplyText, AgentReplyImage)):
                raise TypeError(
                    f"PostHook '{hook.name()}' returned an invalid type. Expected AgentReply, got {type(reply)}"
                )
            self._log.debug(f"PostHook executed for agent '{agent.name}' by hook '{hook.name()}' reply: {reply}")
        return reply

    def sessions(self) -> SessionStore:
        """
        Retrieves the session storage.
        :return: The session storage.
        """
        return self._sessions

    def get_volatile_cache(self, session_id: str | None = None) -> KeyValueCache:
        """
        Retrieves the volatile key-value cache associated with the provided session.
        :param session_id: The session to retrieve the volatile cache for. If not provided, the current context is used to find the session
        :return: The volatile key-value cache.
        """
        if session_id is None:
            session_id = Session.get_current_session_id()

        if session_id is None or session_id == "":
            raise Exception("No current session context available to retrieve volatile cache.")
        return self._sessions.load(session_id).get_volatile_cache()

    def get_non_volatile_cache(self, session_id: str | None = None) -> KeyValueCache:
        """
        Retrieves the non-volatile key-value cache associated with the provided session.
        :param session_id: The session to retrieve the non-volatile cache for. If not provided, the current context is used to find the session
        :return: The non-volatile key-value cache.
        """
        if session_id is None:
            session_id = Session.get_current_session_id()

        if session_id is None or session_id == "":
            raise Exception("No current session context available to retrieve non-volatile cache.")
        return self._sessions.load(session_id).get_non_volatile_cache()


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


class ModuleLoader:
    """
    ModuleLoader is responsible for loading agent modules dynamically.
    """

    _runtime: Optional[Runtime] = None
    _lock: RLock = RLock()

    @staticmethod
    def runtime() -> Runtime:
        """
        Return the Runtime instance set to load the module. By default this is the
        global singleton Runtime instance.
        """
        return ModuleLoader._runtime or GlobalRuntime.instance()

    @staticmethod
    def attach(runtime: Runtime):
        """
        Attach a Runtime instance to the ModuleLoader.

        This method sets the Runtime instance that will be used by the ModuleLoader for
        loading and managing modules. It ensures thread-safety using a lock and validates
        that only one Runtime can be attached at a time.

        :param runtime: The Runtime instance to attach to the ModuleLoader.
        :raises Exception: If a different runtime instance is already attached to the ModuleLoader.
        """
        with ModuleLoader._lock:
            if ModuleLoader._runtime is not None and ModuleLoader._runtime != runtime:
                raise Exception("A different runtime is already attached")
            ModuleLoader._runtime = runtime

    @staticmethod
    def detach(runtime: Runtime):
        """
        Detach a Runtime instance from the ModuleLoader.

        This method removes the Runtime association from the ModuleLoader in a thread-safe manner.
        It validates that the runtime being detached matches the currently attached runtime before
        proceeding with the detachment.

        :param runtime: The runtime instance to detach from the ModuleLoader.
        :raises Exception: If a different runtime is currently attached than the one being detached.
        """
        with ModuleLoader._lock:
            if ModuleLoader._runtime is not None and ModuleLoader._runtime != runtime:
                raise Exception("A different runtime is already attached")
            ModuleLoader._runtime = None

    @staticmethod
    def load(runtime: Runtime, module: str) -> ModuleType:
        """
        Load a module within the context of a given runtime.
        :param runtime: The runtime environment to be associated with the module loading process.
        :param module: The name of the module to import (e.g., 'os.path' or 'mypackage.mymodule').
        :return: The imported module object.

        :raises ModuleNotFoundError: If the specified module cannot be found.
        :raises ImportError: If there's an error during the module import process.
        """
        with ModuleLoader._lock, runtime:
            return importlib.import_module(module)
