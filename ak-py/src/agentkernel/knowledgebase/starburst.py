import logging
import os
from typing import Any, Iterable, List, Mapping, Optional

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
        Initialize a read-only Starburst Galaxy backend manager.

        :param host: Starburst Galaxy cluster hostname (without scheme).
        :param port: HTTPS port used by the cluster, typically ``443``.
        :param user: Starburst username or login email.
        :param password: Starburst password or personal access token.
        :param catalog: Trino catalog name for the target data source.
        :param schema: Schema name inside the selected catalog.
        :param table_name: Primary table name exposed in backend metadata.
        :param name: Backend identifier used by the knowledge router.
        :param description: Optional human-readable backend description.
        :return: None.
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
        """
        Return the backend identifier used by the tool routing layer.

        :return: Backend name configured during initialization.
        """
        return self.name if self.name else "starburst"

    def connect(self, **kwargs) -> None:
        """
        Open or refresh the authenticated connection to Starburst Galaxy.

        :param kwargs: Reserved for interface compatibility.
        :return: None.
        :raises ValueError: If required connection settings are missing.
        """
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
        """
        Close the active Starburst connection.

        :return: None.
        """
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception as exc:
                logger.warning(f"[KB][{self.name}] Close error: {exc}")
            finally:
                self.connection = None

    def write(self, records: Optional[Iterable[Mapping[str, Any]]] = None, **kwargs) -> None:
        """
        Reject write attempts because this backend is read-only.

        :param records: Unused write payload.
        :param kwargs: Reserved for interface compatibility.
        :return: None.
        :raises NotImplementedError: Always raised for this backend.
        """
        raise NotImplementedError(f"[KB][{self.name}] StarburstManager is read-only.")

    def get_description(self) -> str:
        """
        Return a human-readable backend summary.

        :return: Description string in ``<backend_name>: <description>`` format.
        """
        return f"{self.backend_name}: {self.description}"

    def read(self, query: str = "", limit: int = 5, **kwargs) -> List[Mapping[str, Any]]:
        """
        Execute a validated read-only SQL query against Starburst Galaxy.

        Allowed statements are restricted to ``SELECT``, ``SHOW``, and
        ``DESCRIBE``. If no ``LIMIT`` clause is present, a safe fallback limit is
        appended before execution.

        :param query: Agent-generated SQL statement.
        :param limit: Fallback row limit applied when SQL has no LIMIT clause.
        :param kwargs: Reserved for interface compatibility.
        :return: Normalized list of records with ``text`` and ``metadata`` keys.
        """
        if not query or not query.strip():
            logger.warning(f"[KB][{self.name}] Empty query received.")
            return []

        sql = query.strip().rstrip(";")
        if not sql:
            logger.warning(f"[KB][{self.name}] Empty query after normalization.")
            return []

        statement = sql.upper().split()[0]

        # Only allow read-safe statements
        if statement not in ("SELECT", "SHOW", "DESCRIBE"):
            logger.error(f"[KB][{self.name}] Rejected non-read SQL: {sql[:80]}")
            return []

        # Append a safe LIMIT if the agent omitted one for SELECT statements.
        if statement == "SELECT" and "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {limit}"

        return self._execute(sql, retried=False)

    def _execute(self, sql: str, retried: bool) -> List[Mapping[str, Any]]:
        """
        Execute SQL against Starburst with single-retry reconnect behavior.

        :param sql: SQL statement to execute.
        :param retried: ``True`` when this invocation is already a retry attempt.
        :return: Normalized query result rows. Returns an empty list on failure.
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
