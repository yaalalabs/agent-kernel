import logging
import os
from typing import Any, Iterable, List, Mapping

import trino
import trino.exceptions

from .base import KnowledgeBase

logger = logging.getLogger(__name__)

STARBURST_HOST = os.getenv("STARBURST_HOST", "")
STARBURST_USER = os.getenv("STARBURST_USER", "")
STARBURST_PASSWORD = os.getenv("STARBURST_PASSWORD", "")
STARBURST_PORT = int(os.getenv("STARBURST_PORT", "443"))


class StarburstManager(KnowledgeBase):
    """
    Read-only Starburst Galaxy backend.

    The agent is responsible for generating all SQL queries. This class simply
    executes whatever SQL the agent provides against Starburst Galaxy and returns
    normalised results.

    To help the agent generate correct queries, provide catalog, schema, and
    table_name at construction time — these are exposed in the schema so the
    agent always knows the fully-qualified table path (catalog.schema.table).

    Supports any Starburst-connected source: MongoDB, PostgreSQL, Google Sheets,
    and any other catalog registered in Galaxy.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        catalog: str = "",
        schema: str = "",
        table_name: str = "",
        name: str = "starburst",
        description: str | None = None,
    ) -> None:
        """
        Args:
            host:        Starburst Galaxy cluster hostname (no https://).
            port:        HTTPS port, almost always 443.
            user:        Galaxy login email / username.
            password:    Galaxy password or personal access token.
            catalog:     Trino catalog name, e.g. "kb_mongo".
            schema:      Schema inside the catalog, e.g. "my_company_kb".
            table_name:  Table name, e.g. "clients".
            name:        Backend identifier used in the agent tool list.
            description: Human-readable description of this backend.
        """
        super().__init__()

        self.host = host or STARBURST_HOST
        self.port = port or STARBURST_PORT
        self.user = user or STARBURST_USER
        self.password = password or STARBURST_PASSWORD
        self.catalog = catalog
        self.schema = schema
        self.table_name = table_name
        self.name = name
        self.description = description or (f"Starburst Galaxy read-only backend. " f"Query target: {catalog}.{schema}.{table_name}")

        self.connection = None
        self.connect()

    @property
    def backend_name(self) -> str:
        return self.name

    def connect(self, **kwargs) -> None:
        """Open a connection to Starburst Galaxy."""
        missing = [
            k
            for k, v in {
                "host": self.host,
                "user": self.user,
                "password": self.password,
            }.items()
            if not v
        ]
        if missing:
            raise ValueError(f"[KB][{self.name}] Missing config: {', '.join(missing)}")

        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

        self.connection = trino.dbapi.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            catalog=self.catalog or None,
            schema=self.schema or None,
            http_scheme="https",
            auth=trino.auth.BasicAuthentication(self.user, self.password),
            request_timeout=60,
        )
        logger.info(f"[KB][{self.name}] Connected → {self.host} " f"| {self.catalog}.{self.schema}.{self.table_name}")

    def close(self) -> None:
        """Release the Starburst connection."""
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception as exc:
                logger.warning(f"[KB][{self.name}] Close error: {exc}")
            finally:
                self.connection = None

    def write(self, records: Iterable[Mapping[str, Any]] = None, **kwargs) -> None:
        """Starburst backend is strictly read-only."""
        raise NotImplementedError(f"[KB][{self.name}] StarburstManager is read-only.")

    def get_description(self) -> str:
        return f"{self.backend_name}: {self.description}"

    def read(self, query: str = "", limit: int = 5, **kwargs) -> List[Mapping[str, Any]]:
        """
        Execute an agent-generated SQL query against Starburst Galaxy.

        The agent receives the fully-qualified table path (catalog.schema.table)
        from the schema and uses it to construct correct SQL. This method simply
        validates, executes, and normalises the results.

        Args:
            query: SQL statement from the agent (SELECT / SHOW / DESCRIBE only).
            limit: Fallback row cap appended if the agent omits LIMIT.

        Returns:
            List of {"text": ..., "metadata": {"source": ...}} dicts.
        """
        if not query or not query.strip():
            logger.warning(f"[KB][{self.name}] Empty query received.")
            return []

        sql = query.strip().rstrip(";")

        # Only allow read-safe statements
        if not sql.upper().split()[0] in ("SELECT", "SHOW", "DESCRIBE"):
            logger.error(f"[KB][{self.name}] Rejected non-read SQL: {sql[:80]}")
            return []

        # Append a safe LIMIT if the agent omitted one
        if "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {limit}"

        return self._execute(sql, retried=False)

    def _execute(self, sql: str, retried: bool) -> List[Mapping[str, Any]]:
        """
        Run the SQL against Starburst Galaxy.
        Reconnects once automatically on a stale/dropped connection.
        """
        if self.connection is None:
            self.connect()

        cursor = self.connection.cursor()
        try:
            logger.debug(f"[KB][{self.name}] Executing: {sql}")
            cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            source = f"{self.catalog}.{self.schema}.{self.table_name}"

            results = [
                {
                    "text": " | ".join(f"{k}: {v}" for k, v in zip(columns, row)),
                    "metadata": {"source": source},
                }
                for row in rows
            ]

            logger.info(f"[KB][{self.name}] {len(results)} row(s) returned.")
            return results

        except trino.exceptions.TrinoConnectionError as exc:
            if not retried:
                logger.warning(f"[KB][{self.name}] Stale connection — reconnecting… ({exc})")
                self.connect()
                return self._execute(sql, retried=True)
            logger.error(f"[KB][{self.name}] Connection failed after retry: {exc}")
            return []

        except Exception as exc:
            logger.error(f"[KB][{self.name}] Query failed: {exc}", exc_info=True)
            return []

        finally:
            try:
                cursor.close()
            except Exception:
                pass
