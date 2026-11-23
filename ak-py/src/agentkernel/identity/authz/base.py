"""The Authorizer seam: what a principal may do with an agent and with each of its tools."""

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from ...core.model import AccessLevel, Principal


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
