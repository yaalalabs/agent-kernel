from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, Iterable, List, Mapping

Record = Mapping[str, Any]


class KnowledgeBase(ABC):
    """
    Backend-agnostic contract for all knowledge base implementations.

    To add a new backend, subclass this and implement:
      - connect()
      - add_records()
      - search_records()
      - schema()  ← classmethod, tells the agent what this backend stores and how

    """

    def __init__(self):
        self._dynamic_schema = {}

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Unique name for this backend, used in tool calls and schemas."""

    def add_schema(self, schema_config: dict) -> "KnowledgeBase":
        self._dynamic_schema.update(schema_config)
        return self

    def schema(self) -> Mapping[str, Any]:
        """Returns the schema to the Agent."""
        if not self._dynamic_schema:
            raise ValueError(f"Schema for '{self.backend_name}' has not been set! " "Call .add_schema() before passing to the Agent.")

        final_schema = {"backend": self.backend_name}
        final_schema.update(self._dynamic_schema)
        return final_schema

    @abstractmethod
    def connect(self, **kwargs) -> None:
        """Establish the backend connection."""

    @abstractmethod
    def write(self, records: Iterable[Record], **kwargs) -> None:
        """Persist one or more records into the backend."""

    @abstractmethod
    def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """Return the most relevant records for a query."""

    def format_results(self, rows: List[Record]) -> str:
        """Format search results into a readable string for the agent."""
        if not rows:
            return "No relevant knowledge found."
        return "\n".join(f"- {r.get('text', '')} (source: {r.get('metadata', {}).get('source', 'N/A')})" for r in rows)

    def close(self) -> None:
        """Optional cleanup hook for backends that hold external resources."""
        print(f"[KB][{self.backend_name}] close() default no-op", flush=True)

    @abstractmethod
    def get_description(self) -> str:
        """Return a human-readable description of this backend's purpose and capabilities."""
        pass
