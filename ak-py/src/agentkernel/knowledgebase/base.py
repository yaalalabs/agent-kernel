from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Mapping, MutableMapping


KnowledgeRecord = MutableMapping[str, Any]
SearchRecord = Mapping[str, Any]


class AbstractKnowledgeBase(ABC):
    """
    Generic, backend-agnostic knowledge base contract.

    Implementations only need to provide:
    - `add_records(records, **kwargs)`
    - `search_records(query, limit, **kwargs)`

    Optional capabilities can be overridden as needed (`delete_records`, `clear`, `close`).
    """

    @abstractmethod
    def add_records(self, records: Iterable[KnowledgeRecord], **kwargs) -> None:
        """Add one or many normalized records into the knowledge backend."""

    @abstractmethod
    def search_records(self, query: str, limit: int = 3, **kwargs) -> List[SearchRecord]:
        """Search records by query string and return normalized search results."""
    
    def add(self, records: Iterable[KnowledgeRecord], **kwargs) -> None:
        """Backward-compatible alias for adding records."""
        self.add_records(records, **kwargs)

    def search(self, query: str, limit: int = 3, **kwargs) -> List[SearchRecord]:
        """Backward-compatible alias for searching records."""
        return self.search_records(query, limit=limit, **kwargs)

    def add_one(self, record: KnowledgeRecord, **kwargs) -> None:
        """Convenience helper for backends that ingest one record at a time."""
        self.add_records([record], **kwargs)

    def delete_records(self, **kwargs) -> int:
        """Optional capability: delete records and return the number deleted."""
        raise NotImplementedError(f"{self.__class__.__name__} does not implement delete_records().")

    def clear(self) -> None:
        """Optional capability: clear backend content."""
        raise NotImplementedError(f"{self.__class__.__name__} does not implement clear().")

    def close(self) -> None:
        """Optional cleanup hook for backends that hold resources."""
        return None
