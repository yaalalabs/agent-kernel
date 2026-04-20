from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Mapping

Record = Mapping[str, Any]


class KnowledgeBase(ABC):
    """
    Backend-agnostic contract for all knowledge base implementations.

    To add a new backend, subclass this and implement:
      - connect()
      - write()
      - read()
      - backend_name
      - get_description()

    Backends can also receive runtime schema configuration via add_schema().
    The schema() method is an instance method that returns the configured
    schema describing what this backend stores and how.
    """

    def __init__(self):
        """
        Initialize base knowledge backend state.

        :return: None.
        """
        self._dynamic_schema = {}

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

    def schema(self) -> Mapping[str, Any]:
        """
        Return the backend schema exposed to the agent.

        :return: Final schema mapping including backend identity.
        :raises ValueError: If no schema has been configured.
        """
        if not self._dynamic_schema:
            raise ValueError(f"Schema for '{self.backend_name}' has not been set! " "Call .add_schema() before passing to the Agent.")

        final_schema = {"backend": self.backend_name}
        final_schema.update(self._dynamic_schema)
        return final_schema

    @abstractmethod
    def connect(self, **kwargs) -> None:
        """
        Establish the backend connection.

        :param kwargs: Backend-specific connection options.
        :return: None.
        """

    @abstractmethod
    def write(self, records: Iterable[Record], **kwargs) -> None:
        """
        Persist one or more records into the backend.

        :param records: Records to persist.
        :param kwargs: Backend-specific write options.
        :return: None.
        """

    @abstractmethod
    def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """
        Return the most relevant records for a query.

        :param query: Backend-specific query string.
        :param limit: Maximum number of records to return.
        :param kwargs: Backend-specific read options.
        :return: List of matched records.
        """

    def format_results(self, rows: List[Record]) -> str:
        """
        Format backend records into a readable string for the agent.

        :param rows: Records returned by a backend read.
        :return: Human-readable formatted output.
        """
        if not rows:
            return "No relevant knowledge found."
        return "\n".join(f"- {r.get('text', '')} (source: {r.get('metadata', {}).get('source', 'N/A')})" for r in rows)

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
