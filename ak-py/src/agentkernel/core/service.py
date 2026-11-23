import logging
import uuid
from collections.abc import AsyncGenerator

from ..core import Agent, AgentRequest, Runtime, Session
from ..core.model import AgentDescriptor, AgentReply, AgentReplyAny, AgentReplyText, AgentRequestText, AgentSurface, Principal, StreamChunk
from ..core.registry import AgentNotFoundError


class AgentService:
    """
    AgentService class provides a utility method for interacting with runtime, agents and sessions.
    The agent service encapsulates a conversation of a single session with a single agent.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.core.service.agentservice")
        self._agent = None
        self._session = None
        self._runtime = Runtime.current()

    @property
    def runtime(self) -> Runtime:
        """
        Returns the runtime instance.
        """
        return self._runtime

    @property
    def agent(self) -> Agent | None:
        """
        Returns the selected agent.
        """
        return self._agent

    @property
    def session(self) -> Session | None:
        """
        Returns the selected session.
        """
        return self._session

    def reset(self):
        """
        Resets the selected agent and session to reuse the agent service instance for sequential runs.
        """
        self._agent = None
        self._session = None

    @staticmethod
    def ensure_agent_available(name: str | None, *, hosted: bool = False, surface: AgentSurface | None = None) -> None:
        """
        Checks that a request naming ``name`` could be served, without selecting anything.

        A named agent must be known to the agent registry, and an unnamed request needs the
        registry to know at least one agent to default to. The registry is asked, not this
        process's own agents, so a process that only accepts requests (the io handler over a
        shared registry) answers for agents another process hosts; select() still needs the agent
        to be hosted here. Surfaces that commit state before the agent ever runs — a thread
        write, a scheduled task — call this first, so a request that could never be answered
        fails while the caller is still listening instead of at run time.

        A surface that runs the agent in its own process passes ``hosted=True``: an agent the
        registry knows from another process cannot be selected there, so only the agents hosted
        here count and the store is never read. Without it a request for such an agent would pass
        this check, commit its state, and then fail to run.

        A request that entered by one of the agent surfaces carries it (``BaseChatRequest.surface``)
        and passes it here: an agent whose descriptor leaves that surface out is not available to
        the request, named or as the default, so an agent kept off ``rest`` is not served over the
        REST API by a caller who knows its name. A request with no surface (messaging, the CLI, a
        scheduled occurrence) is not governed by the descriptor's ``surfaces``.

        The two failures are different errors. A request that names an agent it cannot have gets
        ``AgentNotFoundError``, which an HTTP route answers with a 404: the answer an agent the
        caller may not see gets, so the status does not say whether a name exists. That holds for
        the ``hosted`` form as well, where an agent another process hosts is, to this one, an agent
        it does not have, and for an agent kept off the request's surface. A request that names no
        agent while there is none to default to has no name to hide, and stays a ``ValueError`` (a
        400).

        Without ``hosted``, an unnamed request is asked only whether the registry knows any agent,
        whatever the surface: the default is picked by the process that runs the agent, which
        applies the surface to its own agents, and reading every descriptor here to second-guess
        it would list the whole store on each request that names no agent.

        For an agent that is not hosted here this reads the registry's store (one read for a named
        agent, the registry's emptiness check for an unnamed request), so an ``async`` caller over
        a shared registry runs it off the event loop.

        Static because it only interrogates the agent registry: it holds no agent and no session,
        so the callers that are not mid-conversation (the thread and schedule surfaces) reach it as
        ``AgentService.ensure_agent_available(...)`` rather than building a throwaway instance. It
        is kept here, next to select(), because it is select()'s rule.

        :param name: Name of the requested agent, or None for the default agent.
        :param hosted: Whether the agent must be hosted by this process, not merely known to the registry.
        :param surface: The surface the request entered by, or None for a request no surface governs.
        :raises AgentNotFoundError: If the request names an agent that is not available.
        :raises ValueError: If the request names no agent and there is none to default to.
        """
        registry = Runtime.current().registry
        # The agents this process hosts answer first: the store is read only for what is not hosted here.
        if name:
            agent = registry.get(name)
            if agent is not None:
                descriptor = agent.descriptor
            else:
                descriptor = None if hosted else registry.descriptor(name)
            if descriptor is None or not AgentService._serves(descriptor, surface):
                raise AgentNotFoundError(name)
        elif not any(AgentService._serves(agent.descriptor, surface) for agent in registry.agents().values()):
            if hosted or registry.is_empty():
                raise ValueError("No agent available")

    @staticmethod
    def _serves(descriptor: AgentDescriptor, surface: AgentSurface | None) -> bool:
        """
        Whether an agent is served to a request that entered by ``surface``.

        :param descriptor: The agent's descriptor.
        :param surface: The surface the request entered by, or None for a request no surface governs.
        :return: True when the request carries no surface, or the descriptor exposes the agent on it.
        """
        return surface is None or descriptor.exposed_on(surface)

    def select(self, session_id: str | None = None, name: str | None = None, surface: AgentSurface | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.

        Only an agent served on the request's surface is selected (see ensure_agent_available): a
        named agent kept off it selects nothing, and an unnamed request defaults to the first agent
        that is on it.

        :param session_id: Unique identifier for the session.
        :param name: Name of the agent to select.
        :param surface: The surface the request entered by, or None for a request no surface governs.
        """
        if name:
            selected = self._runtime.agents().get(name)
            if selected and self._serves(selected.descriptor, surface):
                self._agent = selected
            else:
                self._log.warning(f"No agent found with name '{name}'")
        else:
            self._log.info("No agent was requested. Defaulting to first agent in the list")
            self._agent = next((agent for agent in self._runtime.agents().values() if self._serves(agent.descriptor, surface)), None)
            if self._agent:
                self._log.info(f"Selected agent: {self._agent.name}")
            else:
                self._log.error("No agents available")

        # Create a session only if an agent is selected
        if self._agent:
            if session_id is not None:
                self._old(session_id)
            else:
                self.new()
        else:
            self._log.warning("No agent selected. Session was not created.")

    def _old(self, session_id: str):
        """
        Attempts to load an existing session.
        :param session_id: Unique identifier for the session.
        """
        self._log.debug(f"Attempting to reuse existing session: {session_id}")
        self._session = self._runtime.sessions().load(session_id)

    def new(self):
        """
        Creates a new session.
        """
        session_id = str(uuid.uuid4())
        self._log.info(f"Starting new session: {session_id}")
        self._session = self._runtime.sessions().new(session_id)

    def clear(self):
        """
        Clears the current session data.
        """
        if self._session:
            self._log.info(f"Clearing session: {self._session.id}")
            self._session.clear()
        else:
            self._log.warning("No session available to clear.")

    def load(self, session_id: str, name: str):
        """
        Loads an agent module by name.

        :param session_id: Unique identifier for the session.
        :param name: Name of the agent module to load.
        """
        try:
            self._runtime.load(name)
            if not self._agent:
                self.select(session_id)
        except ImportError as e:
            self._log.info(f"No module found with name '{name}': {e}")
            return None

    async def run(self, prompt: str) -> str:
        """
        Async method to run the agent.

        :param prompt: Prompt to send to the agent.
        """
        requests = [AgentRequestText(prompt=prompt)]

        result = await self.run_multi(requests)
        if isinstance(result, AgentReplyText):
            result = result.response
        elif isinstance(result, AgentReplyAny):
            result = str(result)
        else:
            result = "Non-text reply given"

        return result

    async def run_multi(self, requests: list[AgentRequest], principal: Principal | None = None) -> AgentReply:
        """
        Async method to run the agent.

        :param requests: List of requests to send to the agent. This list can contain multi modal inputs. It will be submitted to the agent as a single request
                        AgentRequestText objects will be concatenated into a single text prompt.
                        AgentRequestAny is handled only by pre-hooks, not by the agent itself
        :param principal: The principal the surface authenticated, published for the run (see Runtime.run);
                        None runs anonymously.
        """
        if not self._agent:
            raise ValueError("No agent selected. Please select an agent before running.")
        if not self._session:
            raise ValueError("No session available. Please create or load a session before running.")

        result = await self._runtime.run(self._agent, self._session, requests, principal=principal)
        return result

    async def stream_multi(self, requests: list[AgentRequest], principal: Principal | None = None) -> AsyncGenerator[StreamChunk, None]:
        """
        Async generator that streams the agent response token by token.

        :param requests: List of requests to send to the agent.
        :param principal: The principal the surface authenticated, published for the run (see Runtime.stream);
                        None runs anonymously.
        :return: An async generator yielding StreamChunk objects.
        """
        if not self._agent:
            raise ValueError("No agent selected. Please select an agent before running.")
        if not self._session:
            raise ValueError("No session available. Please create or load a session before running.")

        async for chunk in self._runtime.stream(self._agent, self._session, requests, principal=principal):  # using async due to aync iterator
            yield chunk

    def get_response_session_id(self, session_id: str | None = None) -> str | None:
        """
        Method will return the session's ID if exists. If not, it will
        return the ID sent by the user. If neither exists, it will return None.

        :param session_id: Unique identifier for the session.
        """
        if self._session:
            return self._session.id
        else:
            return session_id
