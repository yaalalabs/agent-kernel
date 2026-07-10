"""
Azure Cosmos DB (Table API) backed thread store.

Layout (all entities for a thread share PartitionKey = session_id):
    RowKey = "meta"        -> metadata: data (JSON), user_id, group_id, updated_at
    RowKey = "msg#<seq>"   -> one message: data (JSON), where <seq> is a sortable,
                              monotonic, unique key so messages sort by RowKey.

Appending a message upserts a single new entity (atomic, append-only) and
blind-merges updated_at onto the metadata entity, so concurrent appends never
lose or rewrite messages and no entity grows unbounded.
"""

import datetime
import logging
import time
import uuid
from typing import List, Optional, Tuple

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient

from ...config import AKConfig
from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore, paginate

_META_ROW = "meta"
_MSG_PREFIX = "msg#"
# Upper bound for a RowKey range query over the "msg#" prefix ("$" is the next
# ASCII character after "#").
_MSG_UPPER = "msg$"


def _new_seq() -> str:
    """Return a sortable, monotonic, unique message sequence key."""
    return f"{time.time_ns():020d}{uuid.uuid4().hex[:8]}"


def _odata_quote(value: str) -> str:
    """Escape a string literal for an OData filter by doubling single quotes."""
    return value.replace("'", "''")


class CosmosDBThreadStore(ThreadStore):
    """
    Cosmos DB Table API-backed implementation of the ThreadStore interface.
    """

    _table_service_client = None
    _table_client = None

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.cosmosdb")
        cfg = AKConfig.get().thread.cosmosdb
        if cfg is None or not cfg.connection_string:
            raise ValueError("AKConfig.thread.cosmosdb.connection_string must be set to use CosmosDBThreadStore")
        if not cfg.table_name:
            raise ValueError("AKConfig.thread.cosmosdb.table_name must be set to use CosmosDBThreadStore")
        self._connection_string = cfg.connection_string
        self._table_name = cfg.table_name
        self._ttl = cfg.ttl

    @property
    def table_client(self):
        """
        Returns the Azure Table client, connecting lazily if needed.
        """
        if self._table_client is None:
            self._connect()
        return self._table_client

    def _connect(self):
        """
        Establish a connection to Cosmos DB Table API, with retries.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to Cosmos DB Table API")
                self._table_service_client = TableServiceClient.from_connection_string(conn_str=self._connection_string)
                self._table_client = self._table_service_client.get_table_client(table_name=self._table_name)
                try:
                    self._table_client.get_entity(partition_key="__health_check__", row_key="__health_check__")
                except ResourceNotFoundError:
                    pass  # Expected — just checking the table is accessible
                self._log.debug("Connected to Cosmos DB Table %s", self._table_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning("Cosmos DB connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err:
            raise last_err

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata entity.
        :param thread: The thread to persist.
        :return: The persisted thread.
        """
        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        entity = {
            "PartitionKey": thread.session_id,
            "RowKey": _META_ROW,
            "data": metadata.model_dump_json(),
            "user_id": thread.user_id,
            "group_id": thread.group_id or "",
            "updated_at": metadata.updated_at.isoformat(),
        }
        self.table_client.upsert_entity(entity=entity)
        return metadata

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata entity by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        try:
            entity = self.table_client.get_entity(partition_key=session_id, row_key=_META_ROW)
        except ResourceNotFoundError:
            return None
        payload = entity.get("data")
        if payload is None:
            return None
        thread = Thread.model_validate_json(payload)
        if entity.get("updated_at"):
            thread.updated_at = datetime.datetime.fromisoformat(entity["updated_at"])
        return thread

    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Upsert a message entity and blind-merge updated_at onto the metadata entity.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        try:
            self.table_client.get_entity(partition_key=session_id, row_key=_META_ROW)
        except ResourceNotFoundError:
            raise KeyError(f"Thread {session_id} not found")

        self.table_client.upsert_entity(
            entity={
                "PartitionKey": session_id,
                "RowKey": f"{_MSG_PREFIX}{_new_seq()}",
                "data": message.model_dump_json(),
            }
        )
        from azure.data.tables import UpdateMode

        self.table_client.update_entity(
            entity={"PartitionKey": session_id, "RowKey": _META_ROW, "updated_at": _utc_now().isoformat()},
            mode=UpdateMode.MERGE,
        )

    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages ordered by RowKey (chronological).
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message.
        :return: A tuple of (messages page, next_offset).
        """
        if offset < 0:
            offset = 0
        query_filter = f"PartitionKey eq '{_odata_quote(session_id)}' and RowKey ge '{_MSG_PREFIX}' and RowKey lt '{_MSG_UPPER}'"
        # Azure Tables returns entities in RowKey order within a partition, so we
        # can stop after collecting one page's worth plus a lookahead (bounded
        # memory). RowKey embeds the sortable seq; sort the collected window
        # defensively before slicing so intra-window reordering can't misorder a page.
        needed = offset + limit + 1
        collected = []
        for entity in self.table_client.query_entities(query_filter=query_filter):
            collected.append(entity)
            if len(collected) >= needed:
                break
        collected.sort(key=lambda e: e["RowKey"])
        messages = [ThreadMessage.model_validate_json(e["data"]) for e in collected[offset : offset + limit]]
        next_offset = offset + limit if len(collected) > offset + limit else None
        return messages, next_offset

    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Thread], Optional[int]]:
        """
        List thread metadata filtered by user_id and/or group_id, most-recently updated first.
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads to return.
        :param offset: Zero-based index of the first thread.
        :return: A tuple of (threads page, next_offset).
        """
        filters = [f"RowKey eq '{_META_ROW}'"]
        if user_id is not None:
            filters.append(f"user_id eq '{_odata_quote(user_id)}'")
        if group_id is not None:
            filters.append(f"group_id eq '{_odata_quote(group_id)}'")
        query_filter = " and ".join(filters)

        threads = []
        for entity in self.table_client.query_entities(query_filter=query_filter):
            payload = entity.get("data")
            if payload is None:
                continue
            thread = Thread.model_validate_json(payload)
            if entity.get("updated_at"):
                thread.updated_at = datetime.datetime.fromisoformat(entity["updated_at"])
            threads.append(thread)
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        return paginate(threads, limit, offset)

    def clear(self) -> None:
        """
        Delete all entities from the configured table.

        This is a destructive operation intended for development/testing only.
        """
        for entity in self.table_client.list_entities():
            partition_key = entity.get("PartitionKey")
            row_key = entity.get("RowKey")
            if partition_key and row_key:
                try:
                    self.table_client.delete_entity(partition_key=partition_key, row_key=row_key)
                except Exception as delete_err:
                    self._log.warning("Failed to delete entity %s/%s: %s", partition_key, row_key, delete_err)
