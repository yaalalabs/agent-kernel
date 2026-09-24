"""OKF role vocabulary and the agent-to-database assignments the ``okf`` block declares.

The three roles are specific to the Open Knowledge Format capability and introduce no generic
role or permission framework into Agent Kernel: nothing outside ``knowledgebase/okf/`` learns
the words consumer, producer or curator, and the flat ``agents`` allow-list every other
capability uses is untouched.

This module reads no configuration. It is handed an already-parsed mapping, which is what lets
a caller -- or a test -- build a registry from a literal dict.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Tuple

from ...core.util.factory import AKConfigError

if TYPE_CHECKING:
    from ...core.config import _OKFDatabaseConfig


class OKFRole(StrEnum):
    """What an agent may do with one OKF bundle, and what it is instructed to do with it."""

    CONSUMER = "consumer"
    PRODUCER = "producer"
    CURATOR = "curator"

    @property
    def writable(self) -> bool:
        """
        Report whether this role grants write access.

        The single place the producer/curator-versus-consumer distinction is encoded. Every
        permission question routes through it, so adding a fourth role later changes this
        property rather than a scattering of ``in ("producer", "curator")`` comparisons.

        :return: True for producer and curator, False for consumer.
        """
        return self is not OKFRole.CONSUMER


@dataclass(frozen=True)
class OKFAssignment:
    """One agent's role in one database.

    Frozen because a registry is built once and read from every agent construction and every
    tool call, including the consumer threads an agent-runner fleet uses.
    """

    database: str
    role: OKFRole


class OKFRoleRegistry:
    """Who may reach which OKF bundle, and with what permission.

    Built once from the config block and immutable afterwards, so it needs no lock to be read
    concurrently. Permission is per ``(agent, database)`` pair rather than per agent: an agent
    may be a producer of one bundle and a consumer of another, and both hold simultaneously.
    """

    def __init__(self, assignments: Mapping[str, Tuple[OKFAssignment, ...]]) -> None:
        """
        Initialize the registry from already-validated assignments.

        Prefer :meth:`from_config`, which performs the validations. This constructor is the
        seam that lets a caller build a registry from literal data.

        :param assignments: Agent name mapped to that agent's assignments.
        :return: None.
        """
        self._assignments: Dict[str, Tuple[OKFAssignment, ...]] = {agent: tuple(items) for agent, items in assignments.items()}
        # Both derived once: every lookup below is a dict hit, because they happen per tool call.
        self._databases: Dict[str, Tuple[str, ...]] = {
            agent: tuple(dict.fromkeys(item.database for item in items)) for agent, items in self._assignments.items()
        }
        self._writable: Dict[str, frozenset] = {
            agent: frozenset(item.database for item in items if item.role.writable) for agent, items in self._assignments.items()
        }

    @classmethod
    def from_config(cls, databases: Mapping[str, "_OKFDatabaseConfig"]) -> "OKFRoleRegistry":
        """
        Build a registry from the parsed ``okf.databases`` mapping, validating as it goes.

        :param databases: Database name mapped to its parsed configuration.
        :return: The registry.
        :raises AKConfigError: If a database names no agent, or names one agent as both its
                               producer and its curator.
        """
        assignments: Dict[str, List[OKFAssignment]] = {}

        for database, config in databases.items():
            # Deduplicated per role so a name repeated in one list does not become two
            # assignments, which would later append the same mandate to a prompt twice.
            named = {role: tuple(dict.fromkeys(cls._clean(getattr(config, role.value, None)))) for role in OKFRole}

            if not any(named.values()):
                raise AKConfigError(
                    f"OKF database '{database}' names no agent. Every declared database must list at least one agent under "
                    f"'consumer', 'producer' or 'curator'; a bundle no agent can reach is never intended, and it is the "
                    f"mistake that otherwise fails silently."
                )

            both = sorted(set(named[OKFRole.PRODUCER]) & set(named[OKFRole.CURATOR]))
            if both:
                raise AKConfigError(
                    f"OKF database '{database}' names {both} as both 'producer' and 'curator'. The two grant identical "
                    f"permissions and differ only in the instructions appended to the agent, so one agent cannot hold both "
                    f"for the same database. Holding different roles in different databases is supported."
                )

            for role, agent_names in named.items():
                for agent_name in agent_names:
                    assignments.setdefault(agent_name, []).append(OKFAssignment(database=database, role=role))

        return cls({agent: tuple(items) for agent, items in assignments.items()})

    @staticmethod
    def _clean(names: Optional[List[str]]) -> List[str]:
        """
        Drop blank entries and surrounding whitespace from one role list.

        :param names: Raw list from configuration, possibly None.
        :return: Usable agent names.
        """
        return [name.strip() for name in (names or []) if name and name.strip()]

    def assignments_for(self, agent_name: str) -> Tuple[OKFAssignment, ...]:
        """
        Return every role this agent holds, in database declaration order.

        :param agent_name: Agent to look up.
        :return: The agent's assignments; empty when it holds none.
        """
        return self._assignments.get(agent_name, ())

    def databases_for(self, agent_name: str) -> Tuple[str, ...]:
        """
        Return the databases this agent may reach at all, in declaration order.

        :param agent_name: Agent to look up.
        :return: Database names, each appearing once.
        """
        return self._databases.get(agent_name, ())

    def writable_databases_for(self, agent_name: str) -> frozenset:
        """
        Return the databases this agent may write to.

        :param agent_name: Agent to look up.
        :return: Database names the agent holds a writable role in.
        """
        return self._writable.get(agent_name, frozenset())

    def may_write(self, agent_name: str, database: str) -> bool:
        """
        Report whether this agent may write to this database.

        The question ``write_kb`` asks at call time, which is why it is a pair lookup rather
        than a property of the agent.

        :param agent_name: Agent making the call.
        :param database: Database being written to.
        :return: True when the agent holds a writable role in that database.
        """
        return database in self.writable_databases_for(agent_name)

    def has_any_role(self, agent_name: str) -> bool:
        """
        Report whether this agent appears anywhere in the block.

        :param agent_name: Agent to look up.
        :return: True when the agent holds at least one role.
        """
        return bool(self._assignments.get(agent_name))
