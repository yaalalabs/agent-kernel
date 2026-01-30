import asyncio
import contextvars
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List, Self

from deprecated import deprecated

from .config import AKConfig
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

    # deprecated(version="0.2.12", reason="Use Session.Keys.VOLATILE_CACHE.value instead.")
    VOLATILE_CACHE_KEY = Keys.VOLATILE_CACHE.value

    # deprecated(version="0.2.12", reason="Use Session.Keys.NON_VOLATILE_CACHE.value instead.")
    NON_VOLATILE_CACHE_KEY = Keys.NON_VOLATILE_CACHE.value

    current_session: contextvars.ContextVar["Session"] = contextvars.ContextVar("current_session", default=None)

    @classmethod
    def current(cls) -> Self | None:
        """
        Returns the current session.
        :return: The current Session instance.
        """
        return cls.current_session.get()

    @classmethod
    @deprecated(version="0.2.12", reason="Use Session.current() instead.")
    def get_current_session_id(cls) -> str:
        """
        Returns the current session identifier from the context variable.
        :return: The current session identifier.
        """
        session = cls.current()
        return session.id if session else ""

    def __init__(self, id: str):
        """
        Initializes a Session instance.
        :param id: Unique identifier for the session.
        """
        self._log = logging.getLogger(f"ak.core.session [{id}]")
        self._id = id
        self._data = {}
        self._lock = asyncio.Lock()

        # Pre-initialize key-value caches to be used by application code
        # which will not be part of the agent context.
        self.set(Session.Keys.VOLATILE_CACHE.value, KeyValueCache())
        self.set(Session.Keys.NON_VOLATILE_CACHE.value, KeyValueCache())

        self._token = None

    def __repr__(self):
        """
        Returns a string representation of the Session instance.
        :return: String representation of the Session.
        """
        return f"Session(id={self._id})"

    async def __aenter__(self) -> Self:
        """
        Async context manager entry method that acquires a lock and sets the current session.
        This method is called when entering an async context manager (using 'async with').

        It acquires the internal lock to ensure that the session is used by only one coroutine
        at a time. It also sets the current session context variable.

        :param self: The Session instance entering the context.
        :return: The same instance (self) to be used within the async with block.
        :raises: Any exceptions that may occur during lock acquisition or session setting.
        """
        await self._lock.acquire()
        self._token = Session.current_session.set(self)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self._token:
                Session.current_session.reset(self._token)
        finally:
            self._token = None
            if self._lock.locked():
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

    @deprecated(version="0.2.12", reason="Use get_all() instead.")
    def get_all_keys(self):
        """
        Returns a list of all keys in the session data.
        :return: A list of all keys in the session data.
        """
        return self._data.keys()

    def get_all(self, durable: bool = True, volatile: bool = True):
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
        return self.get(Session.Keys.VOLATILE_CACHE.value)

    def get_non_volatile_cache(self) -> KeyValueCache:
        """
        Returns the non-volatile key-value cache associated with this session.
        :return: The non-volatile KeyValueCache instance.
        """
        return self.get(Session.Keys.NON_VOLATILE_CACHE.value)

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

    @deprecated(version="0.2.12", reason="Use async with on the session to acquire it.")
    def set_context(self):
        """
        Sets the current session context variable to this session's ID.
        """
        self._token = Session.current_session.set(self)

    @deprecated(version="0.2.12", reason="Use async with on the session to acquire it.")
    def reset_context(self):
        """
        Resets the current session context variable to the previous value.
        """
        if self._token:
            Session.current_session.reset(self._token)
            self._token = None


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

    @property
    def name(self) -> str:
        """
        Returns the name of the runner.
        """
        return self._name

    @abstractmethod
    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        """
        Runs the agent with the provided multi-modal inputs.
        :param agent: The agent to run.
        :param session: The session to use for the agent.
        :param requests: The list of requests to provide to the agent.
        :return: The result of the agent's execution.
        """
        raise NotImplementedError


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
        self._name = name
        self._runner = runner
        self._pre_hooks = []
        self._post_hooks = []

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

    def attach_pre_hooks(self, hooks: list[PreHook]):
        """
        Attaches pre-execution hooks to the agent.
        Duplicate hook objects are ignored to prevent multiple registrations
        of the same hook.
        :param hooks: List of pre-execution hooks to attach.
        """
        for hook in hooks:
            if hook not in self._pre_hooks:
                self._pre_hooks.append(hook)

    def attach_post_hooks(self, hooks: list[PostHook]):
        """
        Attaches post-execution hooks to the agent.
        Duplicate hook objects are ignored to prevent multiple registrations
        of the same hook.
        :param hooks: List of post-execution hooks to attach.
        """
        for hook in hooks:
            if hook not in self._post_hooks:
                self._post_hooks.append(hook)

    @staticmethod
    def _generate_a2a_card(agent_name: str, description: str, skills: List):
        """
        Helper method to generate an A2A AgentCard.
        :param agent_name: Name of the agent.
        :param description: Description of the agent.
        :param skills: List of AgentSkill objects.
        :return: An A2A AgentCard instance.
        """
        from a2a.types import AgentCapabilities, AgentCard

        return AgentCard(
            name=agent_name,
            description=description,
            url=f"{AKConfig.get().a2a.url}/{agent_name}",
            version=AKConfig.get().library_version,
            default_input_modes=["text"],
            default_output_modes=["json"],
            preferred_transport="HTTP+JSON",
            capabilities=AgentCapabilities(streaming=False),
            skills=skills,
        )

    @abstractmethod
    def get_a2a_card(self):
        """
        Returns the A2A AgentCard associated with the agent.
        """
        pass

    @abstractmethod
    def get_description(self):
        """
        Returns the description of the agent.
        """
        pass
