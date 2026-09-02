from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Mapping

from .errors import KnowledgeCapabilityError
from .model import KnowledgeCapabilities

Record = Mapping[str, Any]


class KnowledgeBase(ABC):
    """
    Backend-agnostic contract for all knowledge base implementations.

    To add a new backend, subclass this and implement:
      - backend_name
      - connect()
      - get_description()

    Then declare what the backend supports in a :class:`KnowledgeCapabilities` passed
    to ``super().__init__()``, and implement the matching operations from
    ``search`` / ``query`` / ``fetch`` / ``browse`` / ``write``. Every operation is
    optional; an undeclared one raises :class:`KnowledgeCapabilityError`, so the
    declaration and the implemented set must agree.

    ``read()`` is concrete and routes to ``query()`` or ``search()`` on the declaration,
    which is what lets one agent tool serve every backend.

    Backends can also receive runtime schema configuration via add_schema(), or
    self-describe by overriding _derived_schema(). The schema() method is an instance
    method that returns the configured schema describing what this backend stores and how.
    """

    capabilities: KnowledgeCapabilities

    def __init__(self, capabilities: KnowledgeCapabilities, name: str | None = None) -> None:
        """
        Initialize base knowledge backend state and validate the declaration.

        :param capabilities: What this backend supports.
        :param name: Backend name used in validation errors. Defaults to the class name.
        :return: None.
        :raises ValueError: If the declaration is unreachable or query-incoherent.
        """
        self._dynamic_schema: dict[str, Any] = {}
        self.capabilities = capabilities
        # backend_name is deliberately not read here: subclasses call super().__init__()
        # before assigning the attributes the property depends on. The operations below
        # may read it, because by then the subclass is fully constructed.
        self.validate_capabilities(capabilities, name or type(self).__name__)

    @staticmethod
    def validate_capabilities(capabilities: KnowledgeCapabilities, subject: str) -> None:
        """
        Reject a capability declaration no backend could honour.

        Static so the reusable backend contract can exercise it without constructing
        a backend.

        :param capabilities: Declaration to check.
        :param subject: Backend name used in the error messages.
        :return: None.
        :raises ValueError: If the declaration is unreachable or query-incoherent.
        """
        # Reachability is checked first so a backend declaring nothing at all reports the
        # more fundamental problem rather than a query-language detail.
        if not (capabilities.search or capabilities.query or capabilities.fetch or capabilities.browse or capabilities.writable):
            raise ValueError(
                f"Knowledge backend '{subject}' declares no capability: at least one of " "search, query, fetch, browse, writable must be True."
            )
        if capabilities.query and not (capabilities.query_language or "").strip():
            raise ValueError(f"Knowledge backend '{subject}' declares query=True without a query_language.")
        if not capabilities.query and (capabilities.query_language or "").strip():
            raise ValueError(f"Knowledge backend '{subject}' declares query_language " f"{capabilities.query_language!r} without query=True.")

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """
        Return a unique backend name used by tools and schema metadata.

        :return: Backend name.
        """

    def add_schema(self, schema_config: dict) -> "KnowledgeBase":
        """
        Merge schema configuration into the dynamic backend schema.

        :param schema_config: Schema configuration dictionary to merge.
        :return: Current backend instance.
        """
        self._dynamic_schema.update(schema_config)
        return self

    def _derived_schema(self) -> Mapping[str, Any]:
        """
        Return a schema the backend can describe by itself, without add_schema().

        Backends declaring ``derives_schema`` must return a non-empty mapping here.

        :return: Derived schema mapping; empty when the backend cannot self-describe.
        """
        return {}

    def schema(self) -> Mapping[str, Any]:
        """
        Return the backend schema exposed to the agent.

        :return: Final schema mapping including backend identity and capabilities.
        :raises ValueError: If neither add_schema() nor _derived_schema() supplied a schema.
        """
        derived = dict(self._derived_schema())
        # backend and capabilities do not count as content, so the guard runs before they are added.
        if not self._dynamic_schema and not derived:
            raise ValueError(f"Schema for '{self.backend_name}' has not been set! " "Call .add_schema() before passing to the Agent.")

        final_schema: dict[str, Any] = {"backend": self.backend_name}
        final_schema.update(derived)
        final_schema.update(self._dynamic_schema)
        # Written last and therefore not overridable: capabilities is the declaration the
        # tool layer routes on, and a deployment must not be able to contradict it.
        final_schema["capabilities"] = self.capabilities.model_dump()
        return final_schema

    @abstractmethod
    def connect(self, **kwargs) -> None:
        """
        Establish the backend connection.

        :param kwargs: Backend-specific connection options.
        :return: None.
        """

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """
        Return the most relevant records for a natural-language query.

        :param query: Natural-language query text.
        :param limit: Maximum number of records to return.
        :param kwargs: Backend-specific search options.
        :return: List of matched records.
        :raises KnowledgeCapabilityError: If the backend does not declare ``search``.
        """
        raise KnowledgeCapabilityError(self.backend_name, "search")

    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Record]:
        """
        Execute a query-language statement and return the resulting records.

        :param statement: Statement in the backend's declared ``query_language``.
        :param limit: Maximum number of records to return.
        :param kwargs: Backend-specific query options.
        :return: List of resulting records.
        :raises KnowledgeCapabilityError: If the backend does not declare ``query``.
        """
        raise KnowledgeCapabilityError(self.backend_name, "query")

    def fetch(self, ids: List[str], **kwargs) -> List[Record]:
        """
        Return records by their backend-native identities.

        :param ids: Record identities to retrieve.
        :param kwargs: Backend-specific fetch options.
        :return: List of retrieved records; unknown identities are omitted.
        :raises KnowledgeCapabilityError: If the backend does not declare ``fetch``.
        """
        raise KnowledgeCapabilityError(self.backend_name, "fetch")

    def browse(self, path: str = "", limit: int = 50, **kwargs) -> List[Record]:
        """
        Enumerate what the backend holds under a namespace.

        :param path: Namespace to enumerate; empty means the top level.
        :param limit: Maximum number of entries to return.
        :param kwargs: Backend-specific browse options.
        :return: List of records describing the namespace contents.
        :raises KnowledgeCapabilityError: If the backend does not declare ``browse``.
        """
        raise KnowledgeCapabilityError(self.backend_name, "browse")

    def write(self, records: Iterable[Record], **kwargs) -> None:
        """
        Persist one or more records into the backend.

        :param records: Records to persist.
        :param kwargs: Backend-specific write options.
        :return: None.
        :raises KnowledgeCapabilityError: If the backend does not declare ``writable``.
        """
        raise KnowledgeCapabilityError(self.backend_name, "write")

    def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """
        Return the most relevant records for a query, routing on the declaration.

        Backends declaring ``query`` receive the text as a statement; every other
        backend receives it as a relevance search. This is the single entrypoint the
        generic read tool uses, so one tool serves every backend.

        :param query: Backend-specific query string.
        :param limit: Maximum number of records to return.
        :param kwargs: Backend-specific read options, forwarded unchanged.
        :return: List of matched records.
        """
        if self.capabilities.query:
            return self.query(query, limit=limit, **kwargs)
        return self.search(query, limit=limit, **kwargs)

    def format_results(self, rows: List[Record]) -> str:
        """
        Format backend records into a readable string for the agent.

        Backends declaring ``fetch`` prefix each line with the record identity, so the
        agent can feed it straight back to the fetch tool.

        :param rows: Records returned by a backend read.
        :return: Human-readable formatted output.
        """
        if not rows:
            return "No relevant knowledge found."

        lines = []
        for row in rows:
            metadata = row.get("metadata", {}) or {}
            text, source = row.get("text", ""), metadata.get("source", "N/A")
            record_id = metadata.get("id")
            # An unusable id degrades to the plain line rather than rendering "[None]".
            if self.capabilities.fetch and isinstance(record_id, str) and record_id:
                lines.append(f"- [{record_id}] {text} (source: {source})")
            else:
                lines.append(f"- {text} (source: {source})")
        return "\n".join(lines)

    def close(self) -> None:
        """
        Close backend resources if needed.

        :return: None.
        """
        pass

    @abstractmethod
    def get_description(self) -> str:
        """
        Return a human-readable description of backend purpose and capabilities.

        :return: Backend description string.
        """
        pass
