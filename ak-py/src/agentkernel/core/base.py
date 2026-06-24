import asyncio
import contextvars
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Iterator
from enum import Enum
from typing import Any, ClassVar, Self, cast

from .hooks import PostHook, PreHook
from .model import AgentReply, AgentRequest
from .util.key_value_cache import KeyValueCache


class Session:
    """
    Session is the base class for a tracking state across related interactions with agents.

    Agent Kernel provides an implementation of the Session class for each supported agent framework,
    allowing the runtime to track and share state across multiple related agent logic invocations.

    Sessions may be volatile (meaning that they are not persisted) or durable (meaning that they
    are persisted and are available across multiple instantiations of the runtime). This is governed
    by the runtime configuration.

    Session class stores framework-specific session data objects in a key-value store, allowing
    different agent frameworks to store and retrieve their own session data without interfering with
    each other.

    In addition, there are two pre-defined key-value caches for storing data that is either volatile
    (i.e., not persisted across runtime invocations) or non-volatile (i.e., persisted across runtime
    invocations). These caches can be used by application code to store data that is not part of the
    agent context but needs to be retained across multiple interactions within the same session.
    """

    class Keys(Enum):
        """
        Pre-defined session data keys for caches.
        """

        VOLATILE_CACHE = "v_cache"
        NON_VOLATILE_CACHE = "nv_cache"

    current_session: ClassVar[contextvars.ContextVar[Self | None]] = contextvars.ContextVar("current_session", default=None)

    @classmethod
    def current(cls) -> Self | None:
        """
        Returns the current session.
        :return: The current Session instance.
        """
        return cls.current_session.get()

    def __init__(self, id: str):
        """
        Initializes a Session instance.
        :param id: Unique identifier for the session.
        """
        self._log: logging.Logger = logging.getLogger(f"ak.core.session [{id}]")
        self._id: str = id
        self._data: dict[str, Any] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

        # Pre-initialize key-value caches to be used by application code
        # which will not be part of the agent context.
        self.set(Session.Keys.VOLATILE_CACHE.value, KeyValueCache())
        self.set(Session.Keys.NON_VOLATILE_CACHE.value, KeyValueCache())

        self._token: Any = None

    def __repr__(self) -> str:
        """
        Returns a string representation of the Session instance.
        :return: String representation of the Session.
        """
        return f"Session({self._id})"

    async def __aenter__(self) -> Self:
        """
        Async context manager entry method that acquires a lock and sets the current session.
        This method is called when entering an async context manager (using 'async with').

        It acquires the internal lock to ensure that the session is used by only one coroutine
        at a time. It also sets the current session context variable.

        :return: The same instance (self) to be used within the async with block.
        :raises: Any exceptions that may occur during lock acquisition or session setting.
        """
        await self._lock.acquire()
        try:
            self._token = Session.current_session.set(self)
            return self
        except Exception:
            self._lock.release()
            raise

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        Async context manager exit method that releases the lock and resets the current session.
        This method is called when exiting an async context manager (using 'async with').
        It releases the internal lock to allow other coroutines to use the session.
        It also resets the current session context variable to its previous value.

        :param exc_type: The type of exception raised (if any).
        :param exc_val: The value of the exception raised (if any).
        :param exc_tb: The traceback of the exception raised (if any).
        :return: None
        :raises: Any exceptions that may occur during lock release or session resetting.
        """
        try:
            if self._token:
                Session.current_session.reset(self._token)
        finally:
            self._token = None
            self._lock.release()

    @property
    def id(self) -> str:
        """
        Returns the unique identifier for the session.
        :return: Unique identifier for the session.
        """
        return self._id

    def get(self, key: str) -> Any:
        """
        Retrieves the specified session data object.
        :param key: The key of the session data object.
        :return: The matching session object associated with the key, or None
        if there is no data object with the specified key.
        """
        result = self._data.get(key)
        self._log.debug(f"Retrieved session data object for key {key}: {result}")
        return result

    def get_all(self, durable: bool = True, volatile: bool = True) -> Iterator[tuple[str, Any]]:
        """
        Returns all session data objects.
        :param durable: Whether to include non-volatile (durable) data objects.
        :param volatile: Whether to include volatile data objects.
        :return: Iterator over matching session object key value pairs.
        """
        for key, value in self._data.items():
            if (durable and key != Session.Keys.VOLATILE_CACHE.value) or (volatile and key == Session.Keys.VOLATILE_CACHE.value):
                yield key, value

    def get_volatile_cache(self) -> KeyValueCache:
        """
        Returns the volatile key-value cache associated with this session.
        :return: The volatile KeyValueCache instance.
        """
        return cast(KeyValueCache, self.get(Session.Keys.VOLATILE_CACHE.value))

    def get_non_volatile_cache(self) -> KeyValueCache:
        """
        Returns the non-volatile key-value cache associated with this session.
        :return: The non-volatile KeyValueCache instance.
        """
        return cast(KeyValueCache, self.get(Session.Keys.NON_VOLATILE_CACHE.value))

    def set(self, key: str, value: Any) -> Any:
        """
        Sets a session data object for the specified key.
        :param key: The key of the session data object.
        :param value: The session data object.
        """
        self._log.debug(f"Setting session data object for key {key}: {value}")
        self._data[key] = value
        return value

    def delete(self, key: str) -> None:
        """
        Deletes the session data object for the specified key.
        :param key: The key of the session data object to be deleted.
        """
        if key in self._data:
            self._log.debug(f"Deleting session data object for key {key}")
            del self._data[key]

    def clear(self) -> None:
        """
        Clears all session data objects.
        """
        self._log.debug(f"Clearing all session data objects")
        self._data = {
            Session.Keys.VOLATILE_CACHE.value: self.get_volatile_cache(),
            Session.Keys.NON_VOLATILE_CACHE.value: self.get_non_volatile_cache(),
        }
        self.get_volatile_cache().clear()
        self.get_non_volatile_cache().clear()


class Runner(ABC):
    """
    Runner is the base class for all agent runners.

    Agent Kernel provides an implementation of the Runner class for each supported agent framework,
    allowing the runtime to execute agent logic in a framework-agnostic manner. These
    implementations inherit from the Runner class and encapsulate the agent runner provided by that
    framework.
    """

    def __init__(self, name: str):
        """
        Initializes a Runner instance.
        :param name: Name of the runner.
        """
        self._name = name

    def __repr__(self) -> str:
        """
        Returns a string representation of the Runner instance.
        :return: String representation of the Runner.
        """
        return f"Runner({self._name})"

    @property
    def name(self) -> str:
        """
        Returns the name of the runner.
        """
        return self._name

    @property
    def supports_streaming(self) -> bool:
        return True

    @abstractmethod
    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the agent with the provided multi-modal inputs.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The list of requests to provide to the agent.
        :return: The result of the agent's execution.
        """
        raise NotImplementedError()

    @abstractmethod
    async def stream(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AsyncGenerator[str, None]:
        """
        Streams the agent response token by token.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The list of requests to provide to the agent.
        :return: An async generator yielding string token deltas.
        """
        raise NotImplementedError()


class Agent(ABC):
    """
    Agent is the base class for all agents.

    Agent Kernel provides an implementation of the Agent class for each supported agent framework,
    allowing the runtime to manage agents in a framework-agnostic manner. These implementations
    inherit from the Agent class and encapsulate the agent implementation provided by that
    framework.
    """

    def __init__(self, name: str, runner: Runner):
        """
        Initializes an Agent instance.
        :param name: Name of the agent.
        :param runner: Runner associated with the agent.
        """
        self._name: str = name
        self._runner: Runner = runner
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []

    def __repr__(self) -> str:
        """
        Returns a string representation of the Agent instance.
        :return: String representation of the Agent.
        """
        return f"Agent({self._name})"

    @property
    def name(self) -> str:
        """
        Returns the name of the agent.
        """
        return self._name

    @property
    def runner(self) -> Runner:
        """
        Returns the runner associated with the agent.
        """
        return self._runner

    @property
    def pre_hooks(self) -> list[PreHook]:
        """
        Returns the list of pre-execution hooks registered for the agent.
        """
        return self._pre_hooks

    @property
    def post_hooks(self) -> list[PostHook]:
        """
        Returns the list of post-execution hooks registered for the agent.
        """
        return self._post_hooks

    @abstractmethod
    def get_description(self) -> str:
        """
        Returns the description of the agent.
        """
        pass

    @abstractmethod
    def override_system_prompt(self, prompt: str) -> None:
        """
        Appends additional instructions to the agent's system prompt.

        Called by ``_setup_system_prompt()`` at init time to inject system-level
        tool instructions (e.g., multimodal attachment analysis guidance).

        :param prompt: The instruction text to append.
        """
        raise NotImplementedError()

    @abstractmethod
    def attach_tool(self, tool: Any) -> None:
        """
        Attaches a tool to the agent.
        :param tool: The tool to attach.
        """
        raise NotImplementedError()

    @abstractmethod
    def get_a2a_card(self) -> Any:
        """
        Returns the A2A AgentCard associated with the agent.
        """
        pass

    def _setup_system_prompt(self) -> None:
        """
        Appends system-defined instructions to the agent's prompt during initialization.
        Should be invoked by subclasses in their initialization process after configuration.
        """
        from agentkernel.core.tool import SystemToolFactory

        suffix = SystemToolFactory.get_system_prompt_suffix()
        self.override_system_prompt(prompt=suffix)

    def _attach_system_tools(self) -> None:
        """
        Attaches system-level tools to the agent during initialization.
        """
        from agentkernel.core.tool import SystemToolFactory

        for tool in SystemToolFactory.get_all():
            self.attach_tool(tool.func)
