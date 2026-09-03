import json
import logging
from typing import Any, Dict, List, Optional

from .base import KnowledgeBase
from .model import KnowledgeCapabilities

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

    @staticmethod
    def _capabilities_of(backend: KnowledgeBase) -> Optional[KnowledgeCapabilities]:
        """
        Return a backend's capability declaration, or None when it has none.

        A subclass that overrides ``__init__`` without calling ``super().__init__()``
        never gets a declaration. That is a bug in the backend, but it must not take
        down tool construction for every other backend, so it reads as "declares
        nothing" rather than raising AttributeError.

        :param backend: Registered backend to inspect.
        :return: The declaration, or None when the backend never declared one.
        """
        return getattr(backend, "capabilities", None)

    def _declares(self, backend: KnowledgeBase, capability: str) -> bool:
        """
        Report whether one backend declares a capability.

        :param backend: Registered backend to inspect.
        :param capability: KnowledgeCapabilities field name, for example "fetch".
        :return: True when the backend declares that capability.
        """
        capabilities = self._capabilities_of(backend)
        return bool(capabilities and getattr(capabilities, capability, False))

    def _backends_declaring(self, capability: str) -> List[str]:
        """
        List the registered backends declaring a capability.

        Used both to gate which tools ``build()`` emits and to tell an agent which
        backends a mis-routed call should have gone to.

        :param capability: KnowledgeCapabilities field name, for example "browse".
        :return: Backend names declaring that capability, in registration order.
        """
        return [name for name, backend in self.backends.items() if self._declares(backend, capability)]

    def _unsupported(self, backend_name: str, capability: str) -> str:
        """
        Build the message returned when a tool is routed at a backend that cannot serve it.

        :param backend_name: Backend the agent addressed.
        :param capability: Capability the tool needs.
        :return: Message naming the backends that do declare the capability.
        """
        return f"Backend '{backend_name}' does not support {capability}. Backends that do: {self._backends_declaring(capability)}."

    def build(self):
        """
        Build and return callable tools for schema discovery, reads, and writes.

        Four tools are always returned. Up to three more are appended, each only when
        some registered backend declares the capability behind it, so an application's
        agent never sees a tool nothing can serve.

        :return: List of callable tool functions.
        """
        for name, backend in self.backends.items():
            if self._capabilities_of(backend) is None:
                log.warning(
                    "[build] Backend %r has no capabilities declaration and will be treated as declaring nothing. "
                    "Its __init__ must call super().__init__(capabilities=...).",
                    name,
                )

        def get_schemas() -> str:
            """
            Retrieve the schema and metadata for all available knowledge base backends.

            :return: JSON string containing backend schema definitions.
            """
            log.debug(f"[get_schemas] backends={list(self.backends.keys())}")
            schemas: dict[str, Any] = {}
            for name, backend in self.backends.items():
                try:
                    schemas[name] = backend.schema()
                except Exception as e:
                    log.error(f"[get_schemas] Schema error on {name}: {e}")
                    schemas[name] = {"error": str(e)}
            return json.dumps(schemas, indent=2)

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
                metadata["query"] = resolved_query
                try:
                    parsed_params = json.loads(params_json)
                except Exception:
                    return "Error: params_json must be a valid JSON object string."

                if not isinstance(parsed_params, dict):
                    return "Error: params_json must be a valid JSON object string."

                metadata["params"] = parsed_params

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

        def search_kb(backend: str, query: str, limit: int = 3) -> str:
            """
            Find the knowledge most relevant to a natural-language question.

            Use this instead of read_kb when the backend also accepts a query language
            and you want relevance ranking rather than an exact statement.

            :param backend: Backend name to search, as returned by get_schemas().
            :param query: Natural-language description of what you are looking for.
            :param limit: Maximum number of results to return.
            :return: Formatted search result string or error message.
            """
            log.debug(f"[search_kb] backend={backend!r} raw_query={query!r}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"

            if not self._declares(db, "search"):
                return self._unsupported(backend, "search")

            resolved_query = self._resolve_placeholders(query)
            if resolved_query != query:
                log.debug(f"[search_kb] Translated query to: {resolved_query!r}")

            try:
                results = db.search(resolved_query, limit=limit)
                return db.format_results(results)
            except Exception as e:
                log.error(f"[search_kb] Execution error on {backend}: {e}")
                return f"Execution Error: {str(e)}"

        def fetch_kb(backend: str, ids: str) -> str:
            """
            Retrieve specific records by the identities a previous result showed.

            Identities appear in square brackets at the start of each result line.

            :param backend: Backend name to fetch from, as returned by get_schemas().
            :param ids: One identity, or several separated by commas.
            :return: Formatted records string or error message.
            """
            log.debug(f"[fetch_kb] backend={backend!r} raw_ids={ids!r}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"

            if not self._declares(db, "fetch"):
                return self._unsupported(backend, "fetch")

            # Resolution runs per segment, after the split, so a placeholder standing for a
            # namespace root resolves the same way whether it arrives alone or in a list.
            resolved_ids = [self._resolve_placeholders(segment) for segment in (raw.strip() for raw in ids.split(",")) if segment]
            if not resolved_ids:
                return "Error: provide at least one id."

            try:
                results = db.fetch(resolved_ids)
                return db.format_results(results)
            except Exception as e:
                log.error(f"[fetch_kb] Execution error on {backend}: {e}")
                return f"Execution Error: {str(e)}"

        def browse_kb(backend: str, path: str = "", limit: int = 50) -> str:
            """
            List what a knowledge base holds under a namespace, without searching it.

            Use this to discover what is available before fetching or searching.

            :param backend: Backend name to browse, as returned by get_schemas().
            :param path: Namespace to list; empty lists the top level.
            :param limit: Maximum number of entries to return.
            :return: Formatted listing string or error message.
            """
            log.debug(f"[browse_kb] backend={backend!r} raw_path={path!r}")
            db = self.backends.get(backend)
            if not db:
                return f"Unknown backend '{backend}'. Available: {list(self.backends.keys())}"

            if not self._declares(db, "browse"):
                return self._unsupported(backend, "browse")

            resolved_path = self._resolve_placeholders(path)
            if resolved_path != path:
                log.debug(f"[browse_kb] Translated path to: {resolved_path!r}")

            try:
                results = db.browse(resolved_path, limit=limit)
                return db.format_results(results)
            except Exception as e:
                log.error(f"[browse_kb] Execution error on {backend}: {e}")
                return f"Execution Error: {str(e)}"

        tools = [get_schemas, read_kb, write_kb, get_all_kb_descriptions]

        # search_kb has the narrowest gate of the three: for a search-only backend read_kb
        # already reaches search(), so the tool is only worth its slot in the prompt once a
        # backend declares query as well and read() therefore routes away from search().
        if any(self._declares(backend, "search") and self._declares(backend, "query") for backend in self.backends.values()):
            tools.append(search_kb)
        if self._backends_declaring("fetch"):
            tools.append(fetch_kb)
        if self._backends_declaring("browse"):
            tools.append(browse_kb)

        return tools
