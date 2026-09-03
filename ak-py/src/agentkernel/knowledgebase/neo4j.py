import hashlib
import json
import logging
import os
from typing import Any, Iterable, List, Mapping

from neo4j import GraphDatabase

from .base import KnowledgeBase
from .errors import KnowledgeError
from .model import KnowledgeCapabilities

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

        super().__init__(
            capabilities=KnowledgeCapabilities(kinds=["graph", "structured"], query=True, query_language="cypher", writable=True),
            name=name,
        )

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
        Persist records to Neo4j by executing the Cypher carried in each record's metadata.

        Reads ``metadata["query"]`` and ``metadata["params"]``, falling back to the
        legacy ``cypher_query`` / ``cypher_params`` names. A record carrying neither
        cannot be stored by this backend: it is skipped so the rest of the batch still
        runs, and the skips are reported once the batch is through. Reporting them is
        what stops the tool layer from calling a write that stored nothing a success.

        :param records: Iterable of records with text and metadata fields.
        :param kwargs: Additional keyword arguments reserved for interface compatibility.
        :return: None.
        :raises KnowledgeError: If any record carried no Cypher; raised after the rest ran.
        """
        stored, skipped = 0, 0
        for record in records:
            meta = dict(record.get("metadata", {}))
            # cypher_* are the pre-#553 key names, still read so a caller that has not
            # migrated keeps working.
            statement = meta.get("query") or meta.get("cypher_query")
            params = meta.get("params") or meta.get("cypher_params") or {}

            if not statement:
                log.warning("[neo4j.write] record carries no query; skipping. metadata keys=%s", sorted(meta))
                skipped += 1
                continue

            self._run(statement, params)
            stored += 1

        if skipped:
            raise KnowledgeError(
                f"[KB][{self.backend_name}] {skipped} of {stored + skipped} record(s) carried no Cypher and were not stored "
                f"({stored} stored). A Neo4j write needs the statement in metadata['query']."
            )

    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Mapping[str, Any]]:
        """
        Execute a Cypher read query and return normalized records.

        :param statement: Cypher query to execute.
        :param limit: Maximum number of records requested by the caller.
        :param kwargs: Additional keyword arguments reserved for interface compatibility.
        :return: List of normalized records for the knowledge interface.
        """

        if limit <= 0:
            return []

        normalized_query = statement.strip().rstrip(";")
        if not normalized_query:
            return []

        limited_query = f"CALL () {{\n{normalized_query}\n}}\nRETURN *\nLIMIT $ak_read_limit"
        records, _, _ = self._run(limited_query, {"ak_read_limit": int(limit)})
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
