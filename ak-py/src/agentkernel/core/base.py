import asyncio
import contextvars
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import Enum
from typing import Any, ClassVar, Self, cast

from deprecated import deprecated

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

    VOLATILE_CACHE_KEY: str = Keys.VOLATILE_CACHE.value
    """Deprecated since 0.2.12, use Session.Keys.VOLATILE_CACHE.value instead."""

    NON_VOLATILE_CACHE_KEY: str = Keys.NON_VOLATILE_CACHE.value
    """Deprecated since 0.2.12, use Session.Keys.NON_VOLATILE_CACHE.value instead."""

    current_session: ClassVar[contextvars.ContextVar[Self | None]] = contextvars.ContextVar("current_session", default=None)

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

    @deprecated(version="0.2.12", reason="Use get_all() instead.")
    def get_all_keys(self):
        """
        Returns a list of all keys in the session data.
        :return: A list of all keys in the session data.
        """
        return self._data.keys()

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

    @deprecated(version="0.2.12", reason="Use async with on the session to acquire it.")
    def set_context(self):
        """
        Sets the current session context variable to this session.
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

    @deprecated(
        version="0.2.12",
        reason="Use Agent.pre_hooks.extend() instead. Note that unlike attach_pre_hooks(), extend() does not perform duplicate checking.",
    )
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

    @deprecated(
        version="0.2.12",
        reason="Use Agent.post_hooks.extend() instead. Note that unlike attach_post_hooks(), extend() does not perform duplicate checking.",
    )
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
        pass

    @abstractmethod
    def attach_tool(self, tool: Any) -> None:
        """
        Attaches a tool to the agent.
        :param tool: The tool to attach.
        """
        pass

    @abstractmethod
    def get_a2a_card(self) -> Any:
        """
        Returns the A2A AgentCard associated with the agent.
        """
        pass

    # Registry for system tool instructions — each entry is (tool_name, instruction_text)
    _system_tool_instructions: list[tuple[str, str]] = []

    @classmethod
    def register_system_tool_instruction(cls, tool_name: str, instruction: str) -> None:
        """
        Register a system-level tool instruction to be injected into agent prompts.

        This is the extension point for system tools (multimodal, future tools, etc.)
        to register their instruction text. All registered instructions are collected
        by ``get_system_prompt_suffix()`` and injected into agent prompts at init time.

        :param tool_name: Unique name for the tool (avoids duplicates).
        :param instruction: Instruction text to inject into agent prompts.
        """
        if not any(name == tool_name for name, _ in cls._system_tool_instructions):
            cls._system_tool_instructions.append((tool_name, instruction))

    @staticmethod
    def get_system_prompt_suffix() -> str:
        """
        Collects and returns all registered system tool instructions.

        :return: Combined instruction text from all registered system tools,
                 or empty string if none are registered.
        """
        if not Agent._system_tool_instructions:
            return ""
        parts = [instruction for _, instruction in Agent._system_tool_instructions]
        return "\n".join(parts)

    def _setup_system_prompt(self) -> None:
        """
        Appends the Agent Kernel system prompt suffix to the agent's system prompt at init time.
        Only applies when multimodal is enabled in AKConfig.
        Subclasses should call this in __init__ after setting up the underlying agent.
        The actual injection is done by override_system_prompt() which each subclass implements.
        """
        from .config import AKConfig

        config = getattr(AKConfig.get(), "multimodal", None)
        if config and config.enabled:

            suffix = self.get_system_prompt_suffix()
            if suffix:
                self.override_system_prompt(prompt=suffix)

    @classmethod
    def get_system_tools(cls) -> list[Any]:
        """
        Retrieves the global system tools applicable to all agents (e.g., multimodal tools).
        """
        from .config import AKConfig

        tools = []
        config = getattr(AKConfig.get(), "multimodal", None)
        if config and config.enabled:
            from .multimodal import analyze_attachments

            tools.append(analyze_attachments)

        return tools

    def _attach_system_tools(self) -> None:
        """
        Attaches Agent Kernel system-level tools to the agent at init time.
        Calls self.attach_tool() with each raw Callable — each framework's attach_tool
        implementation is responsible for wrapping it into the framework-specific tool format.
        """
        for tool in self.get_system_tools():
            self.attach_tool(tool)
