"""The OKF system-prompt section: what an agent is told about the bundles it can reach.

Composed from configuration alone -- database names, their descriptions, and the role each
assignment carries. No ``OKFManager`` is constructed to render it and no store is walked, which
is what makes the prompt independent of construction order: an agent built before any bundle is
opened still receives its full instructions.

The navigation protocol below was hand-written in every OKF application's agent instructions
before this capability existed. It ships here so an application no longer has to know it.
"""

from typing import ClassVar, Dict, Mapping, Optional

from .roles import OKFRole, OKFRoleRegistry

_HEADER = "[Organizational knowledge (OKF)]"

_PREAMBLE = (
    "You have access to Open Knowledge Format bundles. Each one is a navigable tree of concept "
    "documents, not a search index -- browse and fetch before you search."
)

# Preserved in substance from the protocol OKF applications wrote by hand: schemas once, browse
# before search, fetch for the full concept and its links, search only when navigation fails,
# answer citing the concept path and its trust tier.
_PROTOCOL = (
    "How to use them:\n"
    "1. Call get_schemas() exactly once at the start of a session, never again. It tells you each "
    "bundle's version, how many concepts it holds, which concept types exist, and which top-level "
    "namespaces you can browse.\n"
    "2. Navigate before you search. Call browse_kb() with an empty path to read a bundle's own front "
    "page, then browse a namespace to see what it holds. A namespace with a curated listing returns "
    "that listing verbatim -- trust it, a person wrote it.\n"
    "3. Read the concept. Call fetch_kb() with the exact concept path you saw while browsing, for "
    "example 'tables/orders.md'. Only fetch_kb returns a concept's full body and its links to other "
    "concepts, so this is the step that actually answers the question.\n"
    "4. Search only when you cannot navigate. Call search_kb() -- or read_kb(), which routes to the "
    "same relevance search on a bundle -- with the words you expect to appear in the concept. Ranking "
    "is lexical, so use domain terms, not a sentence.\n"
    "5. Answer from the concept you read, and name the concept path you took it from. Every result "
    "carries a trust signal: 'human-reviewed' was checked by a person, 'machine-confirmed' by an "
    "automated check, 'unverified' by nobody. Say which when it matters. If nothing in the bundle "
    "covers the question, say so before answering from general knowledge."
)


class OKFPromptComposer:
    """Renders one agent's OKF instructions from the configured roles and descriptions."""

    #: One sentence per role, rendered under the database it applies to. An agent holding
    #: different roles in different bundles gets both, each scoped to its own bundle -- which is
    #: why the mandate is per line rather than once per agent.
    MANDATES: ClassVar[Dict[OKFRole, str]] = {
        OKFRole.CONSUMER: "Your role is CONSUMER: navigate this bundle and answer from it. Do not write to it.",
        OKFRole.PRODUCER: "Your role is PRODUCER: add new knowledge to this bundle as you learn it, using write_kb.",
        OKFRole.CURATOR: ("Your role is CURATOR: review, correct, update and maintain the existing knowledge in this bundle, using write_kb."),
    }

    def __init__(self, registry: OKFRoleRegistry, descriptions: Mapping[str, Optional[str]]) -> None:
        """
        Initialize the composer.

        :param registry: Who holds which role in which database.
        :param descriptions: Database name mapped to its configured description, if any.
        :return: None.
        """
        self._registry = registry
        self._descriptions = descriptions

    def compose(self, agent_name: Optional[str]) -> str:
        """
        Render the whole OKF prompt section for one agent.

        :param agent_name: Agent to render for.
        :return: The section, or an empty string when the agent holds no role anywhere.
        """
        if not agent_name:
            return ""

        assignments = self._registry.assignments_for(agent_name)
        if not assignments:
            return ""

        lines = [_HEADER, _PREAMBLE, "", "Knowledge bases available to you:"]

        # Grouped by database so an agent holding two roles in one bundle -- which configuration
        # permits for consumer plus a writable role -- reads one entry carrying both mandates,
        # rather than the same bundle listed twice.
        for database in self._registry.databases_for(agent_name):
            roles = [assignment.role for assignment in assignments if assignment.database == database]
            access = "read and write" if any(role.writable for role in roles) else "read only"
            description = (self._descriptions.get(database) or "").strip()

            lines.append(f"- {database} ({access}){f': {description}' if description else ''}")
            lines.extend(f"  {self.MANDATES[role]}" for role in roles)

        lines.extend(["", _PROTOCOL])
        return "\n".join(lines)
