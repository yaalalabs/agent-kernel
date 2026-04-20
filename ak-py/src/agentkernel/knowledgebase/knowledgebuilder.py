import json
import logging
from typing import Any, Dict, List, Optional

from .base import KnowledgeBase

log = logging.getLogger("ak.KnowledgeBuilder")


class KnowledgeBuilder:
    def __init__(self, backends: List[KnowledgeBase], semantic_map: Optional[Dict[str, str]] = None):
        """
        Initialize a knowledge builder that routes reads and writes to named backends.

        The builder creates a registry from the provided backend instances using each
        backend's ``backend_name`` as the lookup key. If a semantic map is provided,
        placeholder tags in incoming queries (for example, ``<orders_table>``) are
        translated to physical resource names before a backend call is executed.
        This is important because callers can keep using stable, domain-level names
        while physical table/index/graph names change across environments, tenants,
        or migrations.
        For an AI agent, this reduces errors and hallucinations because it can
        generate queries with simple logical placeholders instead of remembering
        different catalog, schema, table names, or long physical identifiers.
        The semantic map then resolves those placeholders to the correct runtime
        resources.

        Example:
            The agent can issue the same logical query in any environment using
            semantic placeholders instead of hard-coded table/schema paths:
            ``SELECT * FROM <MONGO_SOURCE> WHERE status = 'active'``
            ``SELECT * FROM <SHEETS_SOURCE> LIMIT 10``

            Each KnowledgeBuilder instance has one semantic_map. In practice,
            you provide different maps per deployment:

            Dev instance:
            ``semantic_map={"<MONGO_SOURCE>": "mongodb.sandbox.clients", "<SHEETS_SOURCE>": "sheets.dev.kb"}``

            Prod instance:
            ``semantic_map={"<MONGO_SOURCE>": "mongodb.prod.customers", "<SHEETS_SOURCE>": "sheets.prod.policies"}``

            The agent's query logic stays identical, but resolves to the correct
            backend resources for that deployment.

        Construction example:
            >>> kb = KnowledgeBuilder(
            ...     backends=[neo4j_backend, trino_backend],
            ...     semantic_map={"<orders_table>": "analytics.sales.orders"},
            ... )

        :param backends: Instantiated knowledge backends to register. Each backend
            must expose a unique ``backend_name`` and implement the ``KnowledgeBase``
            interface methods used by this builder.
        :param semantic_map: Optional mapping of logical placeholders to physical
            identifiers used by backend queries. When omitted, no placeholder
            translation is applied.
        :return: None.
        """
        validated_backends: Dict[str, KnowledgeBase] = {}

        for backend in backends:
            backend_name = backend.backend_name

            if not backend_name:
                raise ValueError("Knowledge base backend_name must be non-empty.")

            if backend_name in validated_backends:
                raise ValueError(f"Duplicate knowledge base backend_name: {backend_name!r}")

            validated_backends[backend_name] = backend

        self.backends = validated_backends
        self.semantic_map = semantic_map or {}

    def _resolve_placeholders(self, text: str) -> str:
        """
        Translate semantic placeholders to backend-specific identifiers.

        :param text: Input text that may contain logical placeholder tags.
        :return: Text with placeholders resolved when mappings are available.
        """
        if not text or not self.semantic_map:
            return text
        resolved_text = text
        for logical_tag, physical_path in self.semantic_map.items():
            if logical_tag in resolved_text:
                resolved_text = resolved_text.replace(logical_tag, physical_path)
        return resolved_text

    def build(self):
        """
        Build and return callable tools for schema discovery, reads, and writes.

        :return: List of callable tool functions.
        """

        def get_schemas() -> str:
            """
            Retrieve the schema and metadata for all available knowledge base backends.

            :return: JSON string containing backend schema definitions.
            """
            log.debug(f"[get_schemas] backends={list(self.backends.keys())}")
            return json.dumps({name: backend.schema() for name, backend in self.backends.items()}, indent=2)

        def read_kb(backend: str, query: str, limit: int = 3) -> str:
            """
            Query a knowledge base backend for relevant information.

            :param backend: Backend name to query, as returned by get_schemas().
            :param query: Backend-specific query text.
            :param limit: Maximum number of results to return.
            :return: Formatted query result string or error message.
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

            :param backend: Backend name to write to, as returned by get_schemas().
            :param text: Human-readable description of the information.
            :param source: Origin label for the written record.
            :param query: Optional backend-specific write query (for example SQL or Cypher).
            :param params_json: JSON object string of query parameters.
            :return: Success or failure message.
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
                except Exception:
                    return "Error: params_json must be a valid JSON object string."

                if not isinstance(parsed_params, dict):
                    return "Error: params_json must be a valid JSON object string."

                metadata["params"] = parsed_params
                metadata["cypher_params"] = parsed_params  # Legacy alias

            try:
                db.write([{"text": text, "metadata": metadata}])
                return f"Stored successfully in '{backend}'."
            except Exception as e:
                log.error(f"[write_kb] Write error on {backend}: {e}")
                return f"Failed to write to '{backend}': {str(e)}"

        def get_all_kb_descriptions() -> str:
            """
            Retrieve a summary of all knowledge base backends and their descriptions.

            :return: Newline-delimited descriptions for each configured backend.
            """
            descriptions = []
            for name, backend in self.backends.items():
                try:
                    descriptions.append(backend.get_description())
                except Exception as e:
                    descriptions.append(f"{name}: Error retrieving description ({e})")
            return "\n".join(descriptions)

        return [get_schemas, read_kb, write_kb, get_all_kb_descriptions]
