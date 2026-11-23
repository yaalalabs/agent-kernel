"""StaticAuthorizer: grants and a per-agent tool policy, read from the ``authorization.static`` block."""

import asyncio
import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ValidationError

from ...core.config import _GrantConfig, _ToolPolicyConfig
from ...core.model import AccessLevel, AgentDescriptor, Principal
from ...core.tool import SystemToolFactory
from ...core.util.factory import AKConfigError
from .base import Authorizer, Decision

if TYPE_CHECKING:
    from ...core.config import _AuthorizationConfig


class SubjectMatcher:
    """The subject grammar of a grant: which principals a subject entry names."""

    EVERYONE: ClassVar[str] = "*"
    AUTHENTICATED: ClassVar[str] = "authenticated"
    # The forms that name something: `<kind>:<name>`, the name never empty.
    NAMED_KINDS: ClassVar[frozenset[str]] = frozenset({"user", "group", "role", "provider"})
    FORMS: ClassVar[str] = "'*', 'authenticated', 'user:<subject>', 'group:<name>', 'role:<name>' or 'provider:<name>'"

    @classmethod
    def is_valid(cls, form: str) -> bool:
        """Whether ``form`` is one of the six subject forms.

        :param form: A subject entry of a grant.
        :return: True for a form `matches` can evaluate.
        """
        if form in (cls.EVERYONE, cls.AUTHENTICATED):
            return True
        kind, separator, name = form.partition(":")
        return bool(separator) and kind in cls.NAMED_KINDS and bool(name)

    @classmethod
    def matches(cls, form: str, principal: Principal) -> bool:
        """Whether a subject entry names ``principal``.

        ``user:<subject>`` matches the subject of a principal an identity provider authenticated, of any
        kind. It never matches a messaging or realtime sender, whose subject is a platform id the platform
        may not have verified and that could collide with a configured subject (an edge sender is granted
        through ``provider:``, ``authenticated`` or ``*``), nor the anonymous principal, whose subject is
        only a placeholder. ``provider:<name>`` matches the provider by its exact name, or every provider
        under a prefix when the name ends in a colon (``provider:messaging:``).

        :param form: A subject entry of a grant.
        :param principal: The principal asking.
        :return: True when the entry names the principal; False for a form that is not a subject.
        """
        if form == cls.EVERYONE:
            return True
        if form == cls.AUTHENTICATED:
            return not principal.is_anonymous
        kind, separator, name = form.partition(":")
        if not separator or not name:
            return False
        if kind == "user":
            return name == principal.subject and not principal.is_anonymous and not principal.is_shared_channel
        if kind == "group":
            return name in principal.groups
        if kind == "role":
            return name in principal.roles
        if kind == "provider":
            return principal.provider == name or (name.endswith(":") and principal.provider.startswith(name))
        return False


class _PolicyTable:
    """What the two tables of the static policy share: turning one entry into its configuration model."""

    @staticmethod
    def _entry[M: BaseModel](entry: Any, model: type[M], where: str, what: str) -> M:
        """Return ``entry`` as ``model``: as it is when the configuration already built it, validated otherwise.

        :param entry: A configuration model, or the mapping one is built from.
        :param model: The configuration model of the table's entries.
        :param where: The setting the entry was read from, for the error.
        :param what: What the entry is, for the error.
        :raises AKConfigError: If the entry does not validate.
        """
        if isinstance(entry, model):
            return entry
        try:
            return model.model_validate(entry)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(str(part) for part in error['loc']) or 'the entry'}: {error['msg']}" for error in e.errors())
            raise AKConfigError(f"{where} is not a usable {what} ({problems})") from e


class GrantTable(_PolicyTable):
    """The grants of the static policy, checked once: every entry usable, every level parsed.

    A grant applies to every (subject, agent) pair it names. An agent entry is an agent id, ``*`` for
    every agent, or ``tag:<name>`` for the agents whose descriptor carries the tag.
    """

    ANY_AGENT: ClassVar[str] = "*"
    TAG: ClassVar[str] = "tag:"

    def __init__(self, grants: Iterable[Any]):
        """
        :param grants: The grants, each a ``_GrantConfig`` or the mapping one is built from.
        :raises AKConfigError: Naming the grant by its index, for an entry that does not validate, an empty
            list of subjects or agents, a subject that is not one of the six forms, or an agent entry that
            names nothing.
        """
        self._grants = tuple(self._checked(index, grant) for index, grant in enumerate(grants))

    @property
    def grants(self) -> tuple[_GrantConfig, ...]:
        """The normalized grants, in the order they were given."""
        return self._grants

    def __len__(self) -> int:
        return len(self._grants)

    def held_by(self, principal: Principal) -> list[_GrantConfig]:
        """Return the grants at least one subject of which names ``principal``."""
        return [grant for grant in self._grants if any(SubjectMatcher.matches(form, principal) for form in grant.subjects)]

    @classmethod
    def selects_by_tag(cls, grant: _GrantConfig) -> bool:
        """Whether deciding which agents a grant covers takes the agents' tags."""
        return any(entry.startswith(cls.TAG) for entry in grant.agents)

    @classmethod
    def covers(cls, grant: _GrantConfig, agent_id: str, tags: Collection[str]) -> bool:
        """Whether a grant names an agent, by its id, by ``*`` or by one of the tags it carries.

        :param grant: The grant.
        :param agent_id: The agent's id, matched exactly.
        :param tags: The tags of the agent's descriptor; empty when it has none or is not known.
        """
        return any(
            entry == cls.ANY_AGENT or entry == agent_id or (entry.startswith(cls.TAG) and entry[len(cls.TAG) :] in tags) for entry in grant.agents
        )

    @classmethod
    def _checked(cls, index: int, entry: Any) -> _GrantConfig:
        where = f"authorization.static.grants[{index}]"
        grant = cls._entry(entry, _GrantConfig, where, "grant")
        if not grant.subjects:
            raise AKConfigError(f"{where}.subjects is empty: a grant names at least one subject")
        if not grant.agents:
            raise AKConfigError(f"{where}.agents is empty: a grant names at least one agent, '*' or a 'tag:<name>'")
        for form in grant.subjects:
            if not SubjectMatcher.is_valid(form):
                raise AKConfigError(f"{where}: '{form}' is not a subject. A subject is {SubjectMatcher.FORMS}")
        for agent in grant.agents:
            if not agent:
                raise AKConfigError(f"{where}.agents has an empty entry: name an agent id, '*' or a 'tag:<name>'")
            if agent == cls.TAG:
                raise AKConfigError(f"{where}: '{agent}' names no tag; write 'tag:<name>'")
        return grant


class ToolPolicyTable(_PolicyTable):
    """The tool policies of the static policy, one per agent."""

    def __init__(self, policies: Iterable[Any]):
        """
        :param policies: The policies, each a ``_ToolPolicyConfig`` or the mapping one is built from.
        :raises AKConfigError: Naming the policy by its index, for an entry that does not validate or a
            second policy for an agent: which allow-list would then apply is not something to guess at.
        """
        self._by_agent: dict[str, _ToolPolicyConfig] = {}
        for index, entry in enumerate(policies):
            where = f"authorization.static.tools[{index}]"
            policy = self._entry(entry, _ToolPolicyConfig, where, "tool policy")
            if policy.agent in self._by_agent:
                raise AKConfigError(f"{where} is a second tool policy for agent '{policy.agent}'; merge it into the first")
            self._by_agent[policy.agent] = policy

    def for_agent(self, agent_id: str) -> _ToolPolicyConfig | None:
        """Return the policy of an agent, or None when the configuration states none for it."""
        return self._by_agent.get(agent_id)


class StaticAuthorizer(Authorizer):
    """Decides from the policy in the ``authorization.static`` block: its grants and its per-agent tool policies.

    The level a principal holds on an agent is the highest over every grant that names both. There are no
    negative grants at the agent level; ``deny`` exists for tools only. A tool is offered when it is not
    denied, is in the allow-list when the agent has one, and its tier is at or below that level. A tool's
    tier is the policy's ``tiers`` entry, else the tier the tool declares when it is one of Agent Kernel's
    own, else ``read``.

    The authorizer keeps no copy of the registry: a ``tag:`` entry is resolved when the question is asked,
    through ``descriptor_lookup``, and only for a principal one of whose grants selects by tag. Over a
    shared registry that lookup is a blocking store read, so it runs off the event loop.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger("ak.identity.authz.static")

    def __init__(
        self,
        grants: Iterable[Any],
        tools: Iterable[Any],
        descriptor_lookup: Callable[[], list[AgentDescriptor]],
        system_tiers: Callable[[str], Mapping[str, AccessLevel]] | None = None,
    ):
        """
        :param grants: The ``authorization.static.grants`` entries, as configuration models or mappings.
        :param tools: The ``authorization.static.tools`` entries, as configuration models or mappings.
        :param descriptor_lookup: Returns every descriptor the registry knows; what ``tag:`` entries are
            resolved against.
        :param system_tiers: Returns, for an agent id, the tier each of Agent Kernel's own tools on that
            agent declares, by tool name. Omitted, no tool declares a tier.
        :raises AKConfigError: If a grant or a tool policy cannot be used.
        """
        self._grants = GrantTable(grants)
        self._policies = ToolPolicyTable(tools)
        self._descriptor_lookup = descriptor_lookup
        self._system_tiers = system_tiers
        if not len(self._grants):
            self._log.warning(
                "authorization.static.grants is empty: every agent is denied to every principal. "
                "Add a grant, or remove the authorization block to run without authorization"
            )

    @classmethod
    def from_config(
        cls,
        config: "_AuthorizationConfig",
        descriptor_lookup: Callable[[], list[AgentDescriptor]] | None = None,
        system_tiers: Callable[[str], Mapping[str, AccessLevel]] | None = None,
    ) -> "StaticAuthorizer":
        """Build the authorizer from an ``authorization`` block of type ``static``.

        :param config: The authorization block; its ``static`` section is required by the config validator.
        :param descriptor_lookup: What ``tag:`` entries are resolved against; the registry of whichever
            runtime is current when a decision needs it, when omitted.
        :param system_tiers: The tiers Agent Kernel's own tools declare, by agent id; those of the system
            tools the configuration attaches to the agent, when omitted.
        :return: The authorizer.
        :raises AKConfigError: If the block has no ``static`` section, or as the constructor.
        """
        if config.static is None:
            raise AKConfigError("authorization.type static requires the authorization.static block")
        return cls(
            grants=config.static.grants,
            tools=config.static.tools,
            descriptor_lookup=descriptor_lookup if descriptor_lookup is not None else cls._registry_descriptors,
            system_tiers=system_tiers if system_tiers is not None else cls._system_tool_tiers,
        )

    @staticmethod
    def _registry_descriptors() -> list[AgentDescriptor]:
        """Every descriptor the current runtime's registry knows, read when a decision needs them."""
        # Imported here: the runtime reaches the authorization package, never the reverse at import time.
        from ...core.runtime import Runtime

        return Runtime.current().registry.descriptors()

    @staticmethod
    def _system_tool_tiers(agent_id: str) -> dict[str, AccessLevel]:
        """The tier each system tool attached to an agent declares, by tool name.

        Asked of the same factory an agent's tools are attached from, so it answers for an agent this
        process does not host as well, as long as both processes read the same configuration.
        """
        return {tool.name: tool.tier for tool in SystemToolFactory.get_all(agent_id)}

    async def agent_level(self, principal: Principal, agent_id: str) -> AccessLevel | None:
        held = self._grants.held_by(principal)
        tags: Collection[str] = ()
        if self._needs_tags(held):
            tags = (await self._tags_by_agent()).get(agent_id, ())
        return self._level(held, agent_id, tags)

    async def check_tool(self, principal: Principal, agent_id: str, tool: str) -> Decision:
        policy = self._policies.for_agent(agent_id)
        refusal = self._policy_refusal(policy, agent_id, tool)
        if refusal is not None:
            # Decided without the level: a denied tool is not something a higher level would unlock.
            return refusal
        level = await self.agent_level(principal, agent_id)
        return self._tier_decision(tool, self._tier(policy, tool, lambda: self._declared_tiers(agent_id)), level)

    async def filter_tools(self, principal: Principal, agent_id: str, tools: list[str]) -> list[str]:
        if not tools:
            return []
        policy = self._policies.for_agent(agent_id)
        # One level and one read of the declared tiers for the whole list, where the default asks per tool.
        level = await self.agent_level(principal, agent_id)
        declared = self._declared_tiers(agent_id)
        return [
            tool
            for tool in tools
            if self._policy_refusal(policy, agent_id, tool) is None
            and self._tier_decision(tool, self._tier(policy, tool, lambda: declared), level).allowed
        ]

    async def visible_agents(self, principal: Principal, candidates: list[str]) -> list[str]:
        held = self._grants.held_by(principal)
        # One registry read for the whole list, where the default would read it for each candidate.
        tags_by_agent = await self._tags_by_agent() if self._needs_tags(held) else {}
        return [agent_id for agent_id in candidates if self._level(held, agent_id, tags_by_agent.get(agent_id, ())) is not None]

    @staticmethod
    def _needs_tags(held: list[_GrantConfig]) -> bool:
        """Whether any grant of the principal selects agents by tag, the one case that reads the registry."""
        return any(GrantTable.selects_by_tag(grant) for grant in held)

    @staticmethod
    def _level(held: list[_GrantConfig], agent_id: str, tags: Collection[str]) -> AccessLevel | None:
        """The highest level over the principal's grants that cover an agent, or None when none does."""
        return max((grant.level for grant in held if GrantTable.covers(grant, agent_id, tags)), default=None)

    async def _tags_by_agent(self) -> dict[str, list[str]]:
        """Read the registry, off the event loop, and return each known agent's tags by its id."""
        descriptors = await asyncio.to_thread(self._descriptor_lookup)
        return {descriptor.id: descriptor.tags for descriptor in descriptors}

    def _declared_tiers(self, agent_id: str) -> Mapping[str, AccessLevel]:
        """The tiers the system tools of an agent declare; empty when the authorizer was given no lookup."""
        return self._system_tiers(agent_id) if self._system_tiers is not None else {}

    @staticmethod
    def _tier(policy: _ToolPolicyConfig | None, tool: str, declared: Callable[[], Mapping[str, AccessLevel]]) -> AccessLevel:
        """The tier of a tool: the policy's entry, else the one the tool declares, else ``read``.

        :param policy: The agent's tool policy, when the configuration states one.
        :param tool: The tool's name.
        :param declared: Returns the tiers the agent's system tools declare; called only when the policy
            names no tier for the tool.
        """
        if policy is not None and tool in policy.tiers:
            return policy.tiers[tool]
        return declared().get(tool, AccessLevel.READ)

    @staticmethod
    def _policy_refusal(policy: _ToolPolicyConfig | None, agent_id: str, tool: str) -> Decision | None:
        """The refusal the agent's deny list or allow-list gives a tool, whoever asks; None when neither refuses it."""
        if policy is None:
            return None
        if tool in policy.deny:
            return Decision(allowed=False, reason=f"Tool '{tool}' is denied for agent '{agent_id}'")
        if policy.allow is not None and tool not in policy.allow:
            return Decision(allowed=False, reason=f"Tool '{tool}' is not in the allow-list of agent '{agent_id}'")
        return None

    @staticmethod
    def _tier_decision(tool: str, tier: AccessLevel, level: AccessLevel | None) -> Decision:
        """Allow a tool whose tier is at or below the level held; a principal with no level is refused every tool."""
        if level is None or level < tier:
            return Decision(allowed=False, reason=f"Tool '{tool}' requires level {tier}; the current principal has {level or 'none'}")
        return Decision(allowed=True)
