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
    "You have access to one or more Open Knowledge Format (OKF) bundles. A bundle is not a search "
    "index and not a database -- it is a directory tree of markdown files that you can navigate and "
    "read, the way a person explores a documentation folder. You can list any directory in it, and "
    "you can retrieve any file in it by name and read its full contents.\n"
    "\n"
    "What is in a bundle:\n"
    "- One file is one concept. Its path inside the bundle -- for example 'tables/orders.md' -- is "
    "its identity. There is no separate id: the path is how you ask for it.\n"
    "- A concept is YAML frontmatter followed by a body. The frontmatter carries its 'type' (an open "
    "vocabulary the bundle's authors chose, such as 'BigQuery Table' or 'Dataset'), and usually a "
    "title, description, tags and status.\n"
    "- Concepts link to each other by path. Following those links is often faster than searching, "
    "and only a retrieved file shows you its links.\n"
    "- A directory may hold an 'index.md': a listing a person wrote by hand for that directory. It "
    "is curated, so prefer it over guessing what the directory contains.\n"
    "- A directory may hold a 'log.md' recording what changed in it and when.\n"
    "- Directories are meaningful. They group related concepts into namespaces, so the tree itself "
    "tells you how this organisation divides its knowledge."
)

# Preserved in substance from the protocol OKF applications wrote by hand: schemas once, browse
# before search, fetch for the full concept and its links, search only when navigation fails,
# answer citing the concept path and its trust tier.
_PROTOCOL = (
    "How to use them:\n"
    "1. Call get_schemas() exactly once at the start of a session, never again. It tells you each "
    "bundle's OKF version, how many concepts it holds, which concept types exist in it, and which "
    "top-level namespaces you can browse. Use it to decide which bundle a question belongs to.\n"
    "2. Navigate before you search. Call browse_kb() with an empty path to see the bundle's own "
    "front page, then browse a namespace such as 'tables' to see what it holds. Browsing a "
    "directory that has an index.md returns that curated listing verbatim -- trust it, a person "
    "wrote it. Browsing is how you find out what exists; it costs nothing to look.\n"
    "3. Get the file. Call fetch_kb() with the exact concept path you saw while browsing, for "
    "example 'tables/orders.md'. You may pass several paths separated by commas. Only fetch_kb "
    "returns a concept's full body and its links to other concepts, so this is the step that "
    "actually answers the question -- browsing and searching only ever show you summaries. When a "
    "fetched concept links to another, fetch that one too rather than guessing what it says.\n"
    "4. Search only when you cannot navigate. Call search_kb() -- or read_kb(), which performs the "
    "same relevance search on a bundle -- with the words you expect to appear in the concept. "
    "Ranking is lexical, not semantic: use the domain's own terms, not a sentence. Then fetch what "
    "the search points you at, because search results are summaries, not bodies.\n"
    "5. Answer from the concept you actually read, and name the concept path you took it from so "
    "the reader can check you. If nothing in the bundle covers the question, say so plainly before "
    "answering from general knowledge -- never present your own knowledge as the bundle's.\n"
    "\n"
    "Reading what comes back:\n"
    "- Every result carries a trust signal derived from who has verified that concept. "
    "'human-reviewed' means a person checked it. 'machine-confirmed' means only an automated check "
    "did. 'unverified' means nobody has. Say which when it matters to the answer, and never present "
    "an unverified concept as settled fact.\n"
    "- A concept may be marked stale, meaning it is past the review date its authors set. It is "
    "still the bundle's answer; say that it may be out of date rather than withholding it.\n"
    "- Trust and staleness are advisory signals, never filters. A concept is returned to you "
    "whatever they say, and deciding what they mean for the answer is your job, not the tool's.\n"
    "- A bundle is read tolerantly: a malformed or unusual file is reported alongside the data "
    "rather than hidden, so an occasional diagnostic in a schema is normal and not an error."
)


class OKFPromptComposer:
    """Renders one agent's OKF instructions from the configured roles and descriptions."""

    #: One sentence per role, rendered under the database it applies to. An agent holding
    #: different roles in different bundles gets both, each scoped to its own bundle -- which is
    #: why the mandate is per line rather than once per agent.
    MANDATES: ClassVar[Dict[OKFRole, str]] = {
        OKFRole.CONSUMER: (
            "Your role here is CONSUMER. Navigate this bundle and answer from it: browse its namespaces, follow the links "
            "between concepts, and fetch the files you need to read in full. You have no way to change this bundle and "
            "must not claim you have -- if asked to record or correct something here, say that you can only read it, and "
            "report what the concept currently says instead."
        ),
        OKFRole.PRODUCER: (
            "Your role here is PRODUCER. As well as reading this bundle, add new knowledge to it with write_kb as you "
            "learn things it does not yet record. Before writing, browse and search to confirm the knowledge is genuinely "
            "new -- a duplicate concept is worse than no concept, because later readers cannot tell which one is current. "
            "Write one self-contained fact per call, in prose a stranger could act on without your conversation for "
            "context, and say where it came from. Each write becomes a new concept file under 'generated/' with a path "
            "chosen for you and your authorship recorded; you cannot choose its path or overwrite an existing concept, "
            "so never promise to edit one in place."
        ),
        OKFRole.CURATOR: (
            "Your role here is CURATOR. As well as reading this bundle, keep what it already holds correct and current "
            "with write_kb. Fetch and read the existing concept in full before you judge it -- browse and search show you "
            "summaries, and a summary is not enough to decide something is wrong. Prioritise concepts marked stale or "
            "carrying a weak trust signal ('unverified', or 'machine-confirmed' where a person should have looked). Your "
            "correction is written as a new concept under 'generated/' rather than replacing the original, so state "
            "plainly which concept path you are correcting, what was wrong with it, and what the correct position is."
        ),
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

    @classmethod
    def for_agent(cls, agent_name: Optional[str]) -> str:
        """
        Render the OKF section for one agent from the configured capability.

        The entry point ``SystemToolFactory.get_prompt_sections`` calls: these instructions are
        the agent's system prompt, so they are composed here and written into it, never carried
        on a tool's description.

        :param agent_name: Agent to render for.
        :return: The section, or "" when the capability is off or the agent holds no role.
        """
        # Imported inside the method rather than at module scope: this module is composed from
        # configuration alone, and the capability manager pulls the store and builder tier
        # behind it.
        from .capability import OKFCapabilityManager

        manager = OKFCapabilityManager.get()
        if manager is None:
            return ""

        composer = cls(manager.roles, {name: config.description for name, config in manager.databases.items()})
        return composer.compose(agent_name)

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
