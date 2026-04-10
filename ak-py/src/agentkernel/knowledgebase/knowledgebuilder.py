import json
import logging
from typing import Any, Dict, List, Optional

from ..core.config import AKConfig
from .base import KnowledgeBase

log = logging.getLogger("ak.KnowledgeBuilder")


def _resolve_log_level() -> int:
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
    def __init__(self, backends: List[KnowledgeBase], semantic_map: Optional[Dict[str, str]] = None):
        """
        Args:
            backends: List of instantiated KnowledgeBase objects.
            semantic_map: Dictionary mapping logical tags (e.g., '<mongo>') to physical identifiers.
        """
        self.backends: Dict[str, KnowledgeBase] = {b.backend_name: b for b in backends}
        self.semantic_map = semantic_map or {}

    def _resolve_placeholders(self, text: str) -> str:
        """Internal helper to safely translate abstract table names."""
        if not text or not self.semantic_map:
            return text
        resolved_text = text
        for logical_tag, physical_path in self.semantic_map.items():
            if logical_tag in resolved_text:
                resolved_text = resolved_text.replace(logical_tag, physical_path)
        return resolved_text

    def build(self):

        def get_schemas() -> str:
            """
            Retrieve the schema and metadata for all available knowledge base backends.
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
            """
            log.debug(f"[read_kb] backend={backend!r} raw_query={query!r}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"

            # --- THE MIDDLEWARE INTERCEPTION ---
            resolved_query = self._resolve_placeholders(query)
            if resolved_query != query:
                log.debug(f"[read_kb] Translated query to: {resolved_query!r}")

            try:
                results = db.read(resolved_query, limit=limit)
                return db.format_results(results)
            except Exception as e:
                log.error(f"[read_kb] Execution error on {backend}: {e}")
                return f"Execution Error: {str(e)}"

        def write_kb(backend: str, text: str = "", source: str = "agent", query: str = "", params_json: str = "{}") -> str:
            """
            Persist information into a knowledge base backend.

            Args:
                backend: The name of the backend to write to (from get_schemas()).
                text: Human-readable description of the information.
                source: Origin of the information (default: 'agent').
                query: Optional backend-specific write query (SQL/Cypher).
                params_json: JSON string of parameters for the query.
            """
            log.debug(f"[write_kb] backend={backend!r} has_text={bool(text)} has_query={bool(query)}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'."

            if not text and not query:
                return "Error: provide at least one of 'text' or 'query'."

            # Apply semantic routing to write queries as well
            resolved_query = self._resolve_placeholders(query)

            metadata: dict[str, Any] = {"source": source}
            if resolved_query:
                # Handle legacy mapping INTERNALLY so the Agent doesn't have to think about it
                metadata["query"] = resolved_query
                metadata["cypher_query"] = resolved_query
                try:
                    parsed_params = json.loads(params_json)
                    metadata["params"] = parsed_params
                    metadata["cypher_params"] = parsed_params  # Legacy alias
                except Exception:
                    return "Error: params_json must be a valid JSON object string."

            try:
                db.write([{"text": text, "metadata": metadata}])
                return f"Stored successfully in '{backend}'."
            except Exception as e:
                log.error(f"[write_kb] Write error on {backend}: {e}")
                return f"Failed to write to '{backend}': {str(e)}"

        def get_all_kb_descriptions() -> str:
            """
            Retrieve a summary of all knowledge base backends and their descriptions.
            """
            descriptions = []
            for name, backend in self.backends.items():
                try:
                    descriptions.append(backend.get_description())
                except Exception as e:
                    descriptions.append(f"{name}: Error retrieving description ({e})")
            return "\n".join(descriptions)

        return [get_schemas, read_kb, write_kb, get_all_kb_descriptions]
