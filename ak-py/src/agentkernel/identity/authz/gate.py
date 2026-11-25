"""AccessGate: the one consumer of the agent registry and the authorizer."""

import asyncio
import contextvars
import logging
import threading
from collections.abc import Coroutine, Iterable
from threading import RLock
from typing import Any, ClassVar

from ...core.base import Agent, Session
from ...core.model import AccessLevel, AgentDescriptor, Principal, ToolFilter
from ...core.registry import AgentNotFoundError
from ...core.runtime import Runtime
from ...core.util.async_bridge import run_async_sync
from ...core.util.factory import AKConfigError
from .base import Authorizer
from .factory import AuthorizerFactory


class AccessGate:
    """Decides what a principal may do with the agents a process serves, before anything runs.

    The gate puts two things together: the registry, which says which agents exist and how each is described,
    and the authorizer, which says what the policy gives a principal. A surface asks it before it commits
    anything (a session load, a thread write, an enqueue) and ``Runtime`` asks it again where every run
    passes, so a caller that reaches an agent by another route is decided the same way.

    ``get()`` is the enabled-check: it returns None when no ``authorization`` block is configured, and then
    nothing is restricted.

    The questions that reach the authorizer have two forms. The ``_async`` form is awaited by coroutines
    (``Runtime.run``), so a remote engine never blocks the event loop. The plain form is for synchronous
    callers; reached from inside a coroutine through a synchronous seam (``AgentHandler.initialize`` under
    ``ChatService.execute``), it drives the question on a thread of its own.
    """

    _instance: ClassVar["AccessGate | None"] = None
    _lock: ClassVar[RLock] = RLock()
    _log: ClassVar[logging.Logger] = logging.getLogger("ak.identity.authz.gate")

    def __init__(self, authorizer: Authorizer):
        """
        :param authorizer: The backend that decides levels and tool calls.
        """
        self._authorizer = authorizer
        # The findings already warned about, so a module loaded later does not repeat them.
        self._warned: set[str] = set()

    @classmethod
    def get(cls) -> "AccessGate | None":
        """Return the process-wide gate, or None when no ``authorization`` block is configured.

        The gate follows the shared authorizer: when that is built again (a reset, in tests), the next call
        returns a gate over the new one.

        :return: The shared gate, or None.
        :raises AKConfigError: If the ``authorization`` block cannot be built into an authorizer.
        """
        authorizer = AuthorizerFactory.get()
        if authorizer is None:
            return None
        with cls._lock:
            if cls._instance is None or cls._instance._authorizer is not authorizer:
                cls._instance = cls(authorizer)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared gate so the next get() builds one. Intended for testing."""
        with cls._lock:
            cls._instance = None

    # -- may the principal use the agent ---------------------------------------------------------

    async def authorize_agent_async(self, principal: Principal, agent_id: str, descriptor: AgentDescriptor | None = None) -> AccessLevel:
        """Return the level ``principal`` holds on an agent, or refuse.

        The two refusals are different errors. An agent the principal holds no level on but may see is a
        ``PermissionError`` (a 403). One it may not see is the ``AgentNotFoundError`` of an agent that does
        not exist, text included (a 404), so the answer never says a hidden name exists.

        :param principal: Who is asking; the anonymous principal when nothing authenticated the request.
        :param agent_id: The id of the agent.
        :param descriptor: The agent's descriptor, when the caller holds it (``Runtime``, for the agent it was
            handed); looked up in the current runtime's registry otherwise.
        :return: The level the policy gives the principal on the agent.
        :raises AgentNotFoundError: If the registry knows no such agent, or the principal may not see it.
        :raises PermissionError: If the principal may see the agent and holds no level on it.
        """
        if descriptor is None:
            descriptor = await self._descriptor(agent_id)
        if descriptor is None:
            raise AgentNotFoundError(agent_id)
        level = await self._authorizer.agent_level(principal, agent_id)
        if level is None:
            if not self._admitted_by_visibility(principal, descriptor):
                raise AgentNotFoundError(agent_id)
            raise self._no_level(principal, agent_id)
        return level

    def authorize_agent(self, principal: Principal, agent_id: str, descriptor: AgentDescriptor | None = None) -> AccessLevel:
        """The synchronous form of ``authorize_agent_async``."""
        level: AccessLevel = self._wait(self.authorize_agent_async(principal, agent_id, descriptor))
        return level

    # -- which agents may the principal see ------------------------------------------------------

    async def visible_async(self, principal: Principal, descriptor: AgentDescriptor) -> bool:
        """Whether ``principal`` may see an agent: it holds a level on it, or the agent's visibility admits it.

        ``public`` admits everyone and ``internal`` everyone who is signed in; ``private`` admits nobody, so
        such an agent is seen only by the principals a grant names. Visibility never confers a level.

        :param principal: Who is asking.
        :param descriptor: The agent's descriptor.
        :return: True when the agent may be listed to the principal.
        """
        if self._admitted_by_visibility(principal, descriptor):
            return True
        return await self._authorizer.agent_level(principal, descriptor.id) is not None

    def visible(self, principal: Principal, descriptor: AgentDescriptor) -> bool:
        """The synchronous form of ``visible_async``."""
        return bool(self._wait(self.visible_async(principal, descriptor)))

    async def visible_agents_async(self, principal: Principal) -> list[AgentDescriptor]:
        """Return the descriptors of the agents ``principal`` may see, out of everything the registry knows.

        The authorizer is asked once for the whole registry (a backend that lists resources answers natively),
        and the agents a visibility admits are added.

        :param principal: Who is asking.
        :return: The visible descriptors, in the registry's order.
        """
        # A listing of the registry: over a shared store it is a blocking read.
        descriptors = await asyncio.to_thread(Runtime.current().registry.descriptors)
        held = set(await self._authorizer.visible_agents(principal, [descriptor.id for descriptor in descriptors]))
        return [descriptor for descriptor in descriptors if descriptor.id in held or self._admitted_by_visibility(principal, descriptor)]

    def visible_agents(self, principal: Principal) -> list[AgentDescriptor]:
        """The synchronous form of ``visible_agents_async``."""
        return list(self._wait(self.visible_agents_async(principal)))

    async def narrow_async(self, principal: Principal, descriptors: Iterable[AgentDescriptor]) -> list[AgentDescriptor]:
        """Return descriptors as ``principal`` is shown them: each with the tools it is offered.

        What a surface lists about an agent (a catalog entry, an A2A card) must not name a tool the
        caller would be denied. ``tools`` keeps the ones the authorizer allows the principal, and
        ``skills`` follows it: a skill whose id is one of the agent's tools stays only while that
        tool does, since the skills default to one per tool, and a skill that names no tool (one
        declared through ``Module.describe``) stays. A principal that sees an agent only through
        its visibility holds no level on it and is offered no tool.

        The decision is over the tools the descriptor records, so an agent another process hosts is
        narrowed like one hosted here. The descriptors handed in are not changed.

        :param principal: Who the listing is for.
        :param descriptors: The descriptors to show, already narrowed to the ones the principal may see.
        :return: A copy of each, in the order given.
        """
        shown: list[AgentDescriptor] = []
        for descriptor in descriptors:
            if not descriptor.tools:
                shown.append(descriptor)
                continue
            offered = set(await self._authorizer.filter_tools(principal, descriptor.id, list(descriptor.tools)))
            tools = [tool for tool in descriptor.tools if tool in offered]
            skills = [skill for skill in descriptor.skills if skill.id not in descriptor.tools or skill.id in offered]
            shown.append(descriptor.model_copy(update={"tools": tools, "skills": skills}))
        return shown

    def narrow(self, principal: Principal, descriptors: Iterable[AgentDescriptor]) -> list[AgentDescriptor]:
        """The synchronous form of ``narrow_async``."""
        return list(self._wait(self.narrow_async(principal, descriptors)))

    # -- which tools is the principal offered ----------------------------------------------------

    async def tool_filter_async(self, principal: Principal, agent: Agent, level: AccessLevel | None = None) -> ToolFilter:
        """Build the tool decision of one run: the tools the principal is offered, and why each other is not.

        The filter is over the tools the agent reports (``Agent.get_tool_names``). ``Runtime`` publishes it for
        the run; the framework adapters read it and never ask the authorizer themselves.

        :param principal: Who the run acts as.
        :param agent: The agent about to run.
        :param level: The level already resolved for the principal on the agent, to save asking again.
        :return: The filter.
        :raises PermissionError: If the principal holds no level on the agent: there is no run to filter for.
        """
        agent_id = agent.descriptor.id
        if level is None:
            level = await self._authorizer.agent_level(principal, agent_id)
        if level is None:
            raise self._no_level(principal, agent_id)
        names = agent.get_tool_names()
        allowed = frozenset(await self._authorizer.filter_tools(principal, agent_id, names))
        reasons: dict[str, str] = {}
        for name in names:
            if name not in allowed and name not in reasons:
                reasons[name] = (await self._authorizer.check_tool(principal, agent_id, name)).reason
        return ToolFilter(level=level, allowed=allowed, reasons=reasons)

    def tool_filter(self, principal: Principal, agent: Agent, level: AccessLevel | None = None) -> ToolFilter:
        """The synchronous form of ``tool_filter_async``."""
        tool_filter: ToolFilter = self._wait(self.tool_filter_async(principal, agent, level))
        return tool_filter

    # -- may the principal continue the session --------------------------------------------------

    def authorize_session(self, principal: Principal, session: Session) -> None:
        """Refuse a principal that is not the one the session belongs to.

        A session nobody owns yet is open. One owned through a direct channel belongs to its owner alone,
        recognised by namespace and subject. One owned through a shared channel (a messaging platform, a
        realtime gateway) belongs to its platform scope: anyone arriving from the same provider and namespace
        continues it, and nobody who merely learned its id does. A shared session is matched on that scope
        and nothing else, so a principal of another provider is not let in by carrying the same namespace and
        subject strings as the sender who opened it.

        :param principal: Who the run acts as.
        :param session: The session the run would use.
        :raises PermissionError: If the session belongs to another principal; the anonymous principal is
            refused like any other that is not the owner.
        """
        owner = session.get_owner()
        if owner is None:
            return
        if owner.provider.startswith(Principal.SHARED_CHANNEL_PREFIXES):
            admitted = (owner.provider, owner.namespace) == (principal.provider, principal.namespace)
        else:
            admitted = (owner.namespace, owner.subject) == (principal.namespace, principal.subject)
        if not admitted:
            raise PermissionError(f"Session '{session.id}' belongs to another principal")

    # -- does the policy fit the agents ----------------------------------------------------------

    def validate_configuration(self, agents: Iterable[Agent], *, registry_wide: bool = True) -> None:
        """Check the policy against agents this process hosts, when it starts serving them.

        Two things stop the process: an agent with tools Agent Kernel cannot gate at call time (the policy
        would not hold for them), and whatever the authorizer finds unworkable in its own policy for one of
        the agents. What the authorizer only finds worth a warning is logged, once per finding.

        :param agents: The hosted agents to check.
        :param registry_wide: Whether every agent has registered, so the findings that compare the policy with
            the whole registry can be made. A module that is one of several passes False as it loads.
        :raises AKConfigError: If the policy cannot be enforced for one of the agents.
        """
        hosted = list(agents)
        for agent in hosted:
            ungated = sorted(agent.ungated_tool_names())
            if ungated:
                raise AKConfigError(
                    f"authorization is configured but agent '{agent.descriptor.id}' on {agent.runner.name} "
                    f"has tools Agent Kernel cannot gate: {ungated}"
                )
        descriptors = Runtime.current().registry.descriptors() if registry_wide else None
        for finding in self._authorizer.validate(hosted, descriptors):
            if finding not in self._warned:
                self._warned.add(finding)
                self._log.warning(finding)

    # -- internals -------------------------------------------------------------------------------

    @staticmethod
    def _admitted_by_visibility(principal: Principal, descriptor: AgentDescriptor) -> bool:
        """Whether the agent's declared visibility alone lets the principal see it."""
        return descriptor.visibility == "public" or (descriptor.visibility == "internal" and not principal.is_anonymous)

    @staticmethod
    def _no_level(principal: Principal, agent_id: str) -> PermissionError:
        """The refusal for an agent the principal may see and holds no level on."""
        return PermissionError(f"Principal '{principal.subject}' holds no level on agent '{agent_id}'")

    @staticmethod
    async def _descriptor(agent_id: str) -> AgentDescriptor | None:
        """The descriptor of an agent: the hosted agent's own, else the one the registry's store holds."""
        registry = Runtime.current().registry
        hosted = registry.get(agent_id)
        if hosted is not None:
            return hosted.descriptor
        # Not hosted here: a blocking read over a shared store.
        return await asyncio.to_thread(registry.descriptor, agent_id)

    @staticmethod
    def _wait(question: Coroutine[Any, Any, Any]) -> Any:
        """Drive one question to its answer from synchronous code.

        With no event loop running in this thread the shared bridge runs it. Inside a coroutine the loop is
        busy with the caller, so the question runs to completion on a thread of its own, with the caller's
        context, and the caller waits for it.

        :param question: The coroutine to run.
        :return: What it returns; what it raises is raised here.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_async_sync(question)
        outcome: dict[str, Any] = {}
        context = contextvars.copy_context()

        def _answer() -> None:
            try:
                outcome["value"] = context.run(asyncio.run, question)
            except BaseException as error:  # handed to the waiting caller, whatever it is
                outcome["error"] = error

        worker = threading.Thread(target=_answer, name="ak-access-gate", daemon=True)
        worker.start()
        worker.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]
