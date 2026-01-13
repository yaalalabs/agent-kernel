import contextvars
import logging
from abc import ABC, abstractmethod
from typing import Any, List

from ..core.hooks import PostHook, PreHook
from .config import AKConfig
from .model import AgentReply, AgentRequest
from .util.key_value_cache import KeyValueCache

current_session = contextvars.ContextVar("session_id", default="")


class Session:
    """
    Session is the base class for a tracking state across related interactions with agents.

    Agent Kernel provides an implementation of the Session class for each supported agent framework,
    allowing the runtime to track and share state across multiple related agent logic invocations.

    Sessions may be volatile (meaning that they are not persisted) or durable (meaning that they
    are persisted and are available across multiple invocations of the runtime). This is governed by
    the runtime configuration.

    Session class stores framework-specific session data objects in a key-value store, allowing
    different agent frameworks to store and retrieve their own session data without interfering with
    each other.

    In addition, there are two pre-defined key-value caches for storing data that is either volatile
    (i.e., not persisted across runtime invocations) or non-volatile (i.e., persisted across runtime
    invocations). These caches can be used by application code to store data that is not part of the
    agent context but needs to be retained across multiple interactions within the same session.
    """

    VOLATILE_CACHE_KEY = "v_cache"
    NON_VOLATILE_CACHE_KEY = "nv_cache"

    @classmethod
    def get_current_session_id(cls) -> str:
        """
        Returns the current session identifier from the context variable.
        :return: The current session identifier.
        """
        return current_session.get()

    def get_volatile_cache(self) -> KeyValueCache:
        """
        Returns the volatile key-value cache associated with this session.
        :return: The volatile KeyValueCache instance.
        """
        return self.get(self.VOLATILE_CACHE_KEY)

    def get_non_volatile_cache(self) -> KeyValueCache:
        """
        Returns the non-volatile key-value cache associated with this session.
        :return: The non-volatile KeyValueCache instance.
        """
        return self.get(self.NON_VOLATILE_CACHE_KEY)

    def __init__(self, id: str):
        """
        Initializes a Session instance.
        :param id: Unique identifier for the session.
        """
        self._log = logging.getLogger("ak.core.session")
        self._id = id
        self._data = {}

        # Pre-initialize key-value caches to be used by application code
        # which will not be part of the agent context.
        self.set(self.VOLATILE_CACHE_KEY, KeyValueCache())
        self.set(self.NON_VOLATILE_CACHE_KEY, KeyValueCache())

        self._token = None

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
        self._log.debug(f"Retrieved session {self._id} data object for key {key}: {result}")
        return result

    def get_all_keys(self):
        """
        Returns a list of all keys in the session data.
        :return: A list of all keys in the session data.
        """
        return self._data.keys()

    def set(self, key: str, value: Any) -> Any:
        """
        Sets a session data object for the specified key.
        :param key: The key of the session data object.
        :param value: The session data object.
        """
        self._log.debug(f"Setting session {self._id} data object for key {key}: {value}")
        self._data[key] = value
        return value

    def delete(self, key: str) -> None:
        """
        Deletes the session data object for the specified key.
        :param key: The key of the session data object to be deleted.
        """
        if key in self._data:
            self._log.debug(f"Deleting session {self._id} data object for key {key}")
            del self._data[key]

    def clear(self) -> None:
        """
        Clears all session data objects.
        """
        self._log.debug(f"Clearing session {self._id} data objects")
        self._data = {
            self.VOLATILE_CACHE_KEY: self.get_volatile_cache(),
            self.NON_VOLATILE_CACHE_KEY: self.get_non_volatile_cache(),
        }
        self.get_volatile_cache().clear()
        self.get_non_volatile_cache().clear()

    def set_context(self):
        """
        Sets the current session context variable to this session's ID.
        """
        self._token = current_session.set(self._id)

    def reset_context(self):
        """
        Resets the current session context variable to the previous value.
        """
        if self._token:
            current_session.reset(self._token)


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
