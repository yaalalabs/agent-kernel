import hashlib
import json
import logging
import os
from typing import Any, Iterable, List, Mapping

from neo4j import GraphDatabase

from .base import KnowledgeBase

log = logging.getLogger("ak.Neo4jManager")


class Neo4jManager(KnowledgeBase):
    """
    Neo4j backend — best for entities, relationships, and structured facts.
    Supports both natural-language graph RAG and raw Cypher execution.
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        name: str = "",
        description: str | None = None,
    ):
        """
        Initialize the Neo4j backend manager.

        :param uri: Neo4j connection URI.
        :param user: Neo4j username.
        :param password: Neo4j password.
        :param database: Optional Neo4j database name.
        :param name: Logical backend name used by the knowledge builder.
        :param description: Human-readable backend description.
        :return: None.
        """

        super().__init__()

        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USERNAME", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.database = database
        self.driver = None
        self.name = name
        self.description = description or "neo4j graph database"
        self.connect()

    @property
    def backend_name(self) -> str:
        """
        Return the logical backend name.

        :return: Backend name.
        """
        return self.name if self.name else "neo4j"

    def connect(self, **kwargs) -> None:
        """
        Establish a connection to Neo4j and verify connectivity.

        :param kwargs: Additional keyword arguments reserved for interface compatibility.
        :return: None.
        """
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            log.debug("[neo4j.connect] connected uri=%r user=%r database=%r", self.uri, self.user, self.database)
        except Exception as exc:
            log.error("[neo4j.connect] failed uri=%r user=%r database=%r error=%s", self.uri, self.user, self.database, str(exc))
            raise

    def close(self) -> None:
        """
        Close the active Neo4j driver if one exists.

        :return: None.
        """
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def _run(self, query: str, parameters: Mapping[str, Any] | None = None):
        """
        Execute a Cypher query with optional parameters.

        :param query: Cypher query to execute.
        :param parameters: Parameters to bind to the query.
        :return: Tuple returned by the Neo4j driver execute_query call.
        """
        params = dict(parameters or {})
        log.debug("[neo4j.run] uri=%r database=%r query=%r params=%r", self.uri, self.database, query, params)
        try:
            if self.database:
                return self.driver.execute_query(query, parameters_=params, database_=self.database)
            return self.driver.execute_query(query, parameters_=params)

        # for free tier neo4j instances, the database might not exist until the first write happens. Handle that gracefully.
        except Exception as exc:
            if self.database and "DatabaseNotFound" in str(exc):
                log.warning("[neo4j.run] database not found, retrying without explicit database. uri=%r database=%r", self.uri, self.database)
                self.database = None
                return self.driver.execute_query(query, parameters_=params)
            log.error("[neo4j.run] failed uri=%r database=%r error=%s", self.uri, self.database, str(exc))
            raise

    def write(self, records: Iterable[Mapping[str, Any]], **kwargs) -> None:
        """
        Persist records to Neo4j using either raw Cypher metadata or note upserts.

        :param records: Iterable of records with text and metadata fields.
        :param kwargs: Additional keyword arguments reserved for interface compatibility.
        :return: None.
        """
        for record in records:
            text = str(record.get("text", "")).strip()
            meta = dict(record.get("metadata", {}))
            source = meta.get("source", "agent")
            cypher_query = meta.get("cypher_query")
            cypher_params = meta.get("cypher_params") or {}

            if cypher_query:
                self._run(cypher_query, cypher_params)
                self._log_cypher_fact(text or "stored_fact", source, cypher_query, cypher_params)
            elif text:
                self._upsert_memory(text, source)

    # for unstructured data without a Cypher query, store as a MemoryNote node.
    def _upsert_memory(self, text: str, source: str) -> None:
        """
        Upsert an unstructured memory note node.

        :param text: Memory text to persist.
        :param source: Source label for the memory.
        :return: None.
        """
        self._run(
            "MERGE (m:MemoryNote {text: $text, source: $source}) " "ON CREATE SET m.created_at = datetime() " "SET m.updated_at = datetime()",
            {"text": text, "source": source},
        )

    # for logging cypher-based so we can look up when the agent stored a fact with a specific query + params.
    def _log_cypher_fact(self, text: str, source: str, cypher_query: str, params: Mapping) -> None:
        """
        Log metadata for a Cypher-based fact write using a stable fingerprint.

        :param text: Human-readable fact text.
        :param source: Source label associated with the fact.
        :param cypher_query: Cypher query used for the write.
        :param params: Query parameter mapping.
        :return: None.
        """
        raw = f"{text}|{source}|{cypher_query}|{json.dumps(params, sort_keys=True)}"
        self._run(
            "MERGE (f:CypherFact {fingerprint: $fp}) "
            "ON CREATE SET f.created_at = datetime() "
            "SET f.updated_at = datetime(), f.text = $text, f.source = $source, "
            "    f.cypher_query = $cq, f.cypher_params_json = $cpj",
            {
                "fp": hashlib.md5(raw.encode()).hexdigest(),
                "text": text,
                "source": source,
                "cq": cypher_query,
                "cpj": json.dumps(params, sort_keys=True),
            },
        )

    def read(self, query: str, limit: int = 10, **kwargs) -> List[Mapping[str, Any]]:
        """
        Execute a Cypher read query and return normalized records.

        :param query: Cypher query to execute.
        :param limit: Maximum number of records requested by the caller.
        :param kwargs: Additional keyword arguments reserved for interface compatibility.
        :return: List of normalized records for the knowledge interface.
        """

        records, _, _ = self._run(query)
        if records:
            return [{"text": json.dumps(r.data(), default=str), "metadata": {"source": "graph"}} for r in records]
        return []

    def get_description(
        self,
    ) -> str:
        """
        Provide a human-readable description of this backend for the agent.

        :return: Description string in the format '<backend_name>: <description>'.
        """
        return f"{self.backend_name}: {self.description}"
