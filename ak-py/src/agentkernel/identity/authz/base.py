"""The Authorizer seam: what a principal may do with an agent and with each of its tools."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from ...core.model import AccessLevel, AgentDescriptor, Principal

if TYPE_CHECKING:
    from ...core.base import Agent


class Decision(BaseModel):
    """Whether a principal may call one tool, and when it may not, why.

    The reason of a refusal is what the model is told in place of the tool's result, so it names the tool
    and the rule that refused it and nothing about anyone else's access.
    """

    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str = ""


class AuthorizerCapabilities(BaseModel):
    """What a backend can do beyond the two questions every backend answers."""

    model_config = ConfigDict(frozen=True)

    # Whether the backend lists the agents a principal may see itself (a relationship store does), in place
    # of being asked about each candidate in turn.
    lists_resources: bool = False


class Authorizer(ABC):
    """A backend that decides what a principal may do: the level it holds on an agent, and each tool call.

    A backend answers two questions, ``agent_level`` and ``check_tool``; the two list forms have defaults
    built on them, which a backend overrides when it can answer a list in one go. It decides from the
    principal it is handed (its subject, groups, roles and claims) and stores nothing about it: roles are
    produced by the configured role mapper, and a backend is free to ignore them.

    An authorizer reads no configuration in its methods. The factory builds it from the ``authorization``
    block alone: a built-in backend from the section named after it, a bring-your-own one by handing the
    whole block to its constructor. Building it raises ``AKConfigError`` when its settings cannot be used.

    One instance serves the whole process and may be awaited on more than one event loop: the server's, for
    a run, and a short-lived one when a synchronous caller asks from inside a coroutine (the access gate
    drives the question on a thread of its own). A backend that talks to an engine therefore does not bind a
    connection to the loop it was first awaited on.
    """

    capabilities: ClassVar[AuthorizerCapabilities] = AuthorizerCapabilities()

    @abstractmethod
    async def agent_level(self, principal: Principal, agent_id: str) -> AccessLevel | None:
        """Return the level ``principal`` holds on an agent.

        :param principal: Who is asking; the anonymous principal when nothing authenticated the request.
        :param agent_id: The id of the agent, as its descriptor carries it.
        :return: The highest level the policy gives the principal on the agent, or None when it gives none.
        """
        raise NotImplementedError

    @abstractmethod
    async def check_tool(self, principal: Principal, agent_id: str, tool: str) -> Decision:
        """Decide whether ``principal`` may call one tool of an agent.

        :param principal: Who is asking.
        :param agent_id: The id of the agent the tool belongs to.
        :param tool: The tool's name, as the agent's descriptor reports it.
        :return: The decision; a refusal carries the reason.
        """
        raise NotImplementedError

    async def filter_tools(self, principal: Principal, agent_id: str, tools: list[str]) -> list[str]:
        """Return the tools of an agent ``principal`` may call, in the order given.

        :param principal: Who is asking.
        :param agent_id: The id of the agent the tools belong to.
        :param tools: The tool names to decide on.
        :return: The names ``check_tool`` allows.
        """
        return [tool for tool in tools if (await self.check_tool(principal, agent_id, tool)).allowed]

    async def visible_agents(self, principal: Principal, candidates: list[str]) -> list[str]:
        """Return the candidate agents ``principal`` holds a level on, in the order given.

        :param principal: Who is asking.
        :param candidates: The agent ids to choose among; the registry's, when a surface lists agents.
        :return: The ids ``agent_level`` answers with a level for.
        """
        return [agent_id for agent_id in candidates if await self.agent_level(principal, agent_id) is not None]

    def validate(self, agents: Iterable["Agent"], descriptors: Iterable[AgentDescriptor] | None = None) -> list[str]:
        """Compare the policy with the agents a process is about to serve, when it starts serving them.

        The access gate calls this as agents load. The default finds nothing, which is right for a backend
        whose policy lives in an engine it cannot read back. A backend that holds its policy overrides it:
        what cannot work for a hosted agent is an error, so the process does not start on a policy that
        silently protects nothing, and what merely matches nothing yet is a finding to warn about.

        :param agents: The agents this process hosts that are being checked.
        :param descriptors: Every descriptor the registry knows, for the findings that need all of them; None
            when not every agent has registered yet, and those findings are left out.
        :return: The findings worth a warning, each a full sentence naming the setting; the gate logs each once.
        :raises AKConfigError: If the policy cannot work for one of the agents.
        """
        return []
