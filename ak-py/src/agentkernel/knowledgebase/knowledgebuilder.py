import json
import logging
from typing import Any, Dict, List

from ..core.config import AKConfig
from .base import KnowledgeBase

log = logging.getLogger("ak.KnowledgeBuilder")


def _resolve_log_level() -> int:
    """
    Resolve the logger level from global AK configuration.

    :return: A valid ``logging`` module integer level.
    :rtype: int
    """
    return logging.DEBUG if AKConfig.get().debug else logging.INFO


resolved_log_level = _resolve_log_level()
log.setLevel(resolved_log_level)

if not log.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(resolved_log_level)
    handler.setFormatter(logging.Formatter("\033[36m(kernel) >> %(message)s\033[0m"))
    log.addHandler(handler)

log.propagate = False


class KnowledgeBuilder:
    def __init__(self, backends: List[KnowledgeBase]):
        self.backends: Dict[str, KnowledgeBase] = {b.backend_name: b for b in backends}

    def build(self):

        def get_schemas() -> str:
            """
            Retrieve the schema and metadata for all available knowledge base backends.

            Returns a JSON object describing each backend's capabilities, including descriptions,
            payload formats, and usage guidelines. Call this first to understand what backends are
            available and how to use them.

            Returns:
                str: JSON-formatted schema containing backend names, descriptions, and interface details.
            """
            log.debug(f"[get_schemas] backends={list(self.backends.keys())}")
            return json.dumps({name: backend.schema() for name, backend in self.backends.items()}, indent=2)

        def read_kb(backend: str, query: str, limit: int = 3) -> str:
            """
            Query a knowledge base backend for relevant information.

            Args:
                backend: The name of the backend to query (from get_schemas()).
                query: The search query appropriate for the backend.
                limit: Maximum number of results to return (default: 3).

            Returns:
                Formatted search results with content and metadata, or error message if backend not found.
            """
            log.debug(f"[read_kb] backend={backend!r} query={query!r}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"
            return db.format_results(db.read(query, limit=limit))

        def write_kb(
            backend: str,
            text: str = "",
            source: str = "agent",
            query: str = "",
            params_json: str = "{}",
            cypher_query: str = "",
            cypher_params_json: str = "{}",
        ) -> str:
            """
            Persist information into a knowledge base backend.

            Args:
                backend: The name of the backend to write to (from get_schemas()).
                text: Human-readable description of the information (REQUIRED).
                source: Origin of the information, e.g., 'agent', 'user', 'system' (default: 'agent').
                query: Optional backend-specific write query (Cypher/SQL/etc.).
                params_json: JSON string of parameters for the query.
                cypher_query: Backward-compatible alias for Neo4j query.
                cypher_params_json: Backward-compatible alias for Neo4j params.

            Returns:
                Success message or error details.
            """
            resolved_query = query or cypher_query
            resolved_params_json = params_json if query else cypher_params_json

            log.debug(f"[write_kb] backend={backend!r} has_text={bool(text)} has_query={bool(resolved_query)}", extra={"backend": backend})
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'."

            if not text and not resolved_query:
                return "Error: provide at least one of 'text' or 'query'."

            metadata: dict[str, Any] = {"source": source}
            if resolved_query:
                metadata["query"] = resolved_query
                metadata["cypher_query"] = resolved_query
                try:
                    parsed_params = json.loads(resolved_params_json)
                    metadata["params"] = parsed_params
                    metadata["cypher_params"] = parsed_params
                    log.debug(
                        "[write_kb.query] backend=%r query=%r params=%r",
                        backend,
                        resolved_query,
                        parsed_params,
                    )
                except Exception:
                    return "Error: params_json/cypher_params_json must be a valid JSON object string."

            db.write([{"text": text, "metadata": metadata}])
            return f"Stored successfully in '{backend}'."

        def get_all_kb_descriptions() -> str:
            """
            Retrieve a summary of all knowledge base backends and their descriptions.

            This is a helper method to quickly get an overview of what each backend is for,
            without needing to parse the full schema. It extracts the 'description' field from
            each backend's schema and formats it into a readable list.

            Returns:
                str: A formatted string listing each backend and its description.
            """
            descriptions = []

            for name, backend in self.backends.items():
                try:
                    descriptions.append(backend.get_description())
                except Exception as e:
                    descriptions.append(f"{name}: Error retrieving description ({e})")
            return "\n".join(descriptions)

        return [get_schemas, read_kb, write_kb, get_all_kb_descriptions]
