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
        return self.name

    def connect(self, **kwargs) -> None:
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            log.debug("[neo4j.connect] connected uri=%r user=%r database=%r", self.uri, self.user, self.database)
        except Exception as exc:
            log.error("[neo4j.connect] failed uri=%r user=%r database=%r error=%s", self.uri, self.user, self.database, str(exc))
            raise

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def _run(self, query: str, parameters: Mapping[str, Any] | None = None):
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
        self._run(
            "MERGE (m:MemoryNote {text: $text, source: $source}) " "ON CREATE SET m.created_at = datetime() " "SET m.updated_at = datetime()",
            {"text": text, "source": source},
        )

    # for logging cypher-based so we can look up when the agent stored a fact with a specific query + params.
    def _log_cypher_fact(self, text: str, source: str, cypher_query: str, params: Mapping) -> None:
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
        search for query using cypher text generated
        """

        records, _, _ = self._run(query)
        if records:
            return [{"text": json.dumps(r.data(), default=str), "metadata": {"source": "graph"}} for r in records]
        return []

    def get_description(
        self,
    ) -> str:
        """Provide a human-readable description of this backend for the agent."""
        return f"{self.backend_name}: {self.description }"
