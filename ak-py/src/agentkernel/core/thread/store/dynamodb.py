"""
DynamoDB-backed thread store.

Expected table schema:
    Partition Key: ``session_id`` (S)
    Sort Key:      ``sk``         (S)
    TTL attribute: ``expiry_time`` (N) — Unix epoch seconds (optional)

Item layout (one thread spans multiple items sharing session_id):
    sk = "meta"          -> thread metadata: data (JSON), user_id, group_id, updated_at
    sk = "msg#<seq>"     -> one message: data (JSON), where <seq> is a sortable,
                            monotonic, unique key so messages sort chronologically.

Appending a message is a single put_item of a new item — atomic and append-only,
so concurrent appends never lose or rewrite messages, and no single item grows
unbounded.
"""

import datetime
import logging
import time
import uuid
from typing import List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from ...config import AKConfig
from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore

_META_SK = "meta"
_MSG_PREFIX = "msg#"


def _new_seq() -> str:
    """Return a sortable, monotonic, unique message sequence key."""
    return f"{time.time_ns():020d}{uuid.uuid4().hex[:8]}"


class DynamoDBThreadStore(ThreadStore):
    """
    DynamoDB-backed implementation of the ThreadStore interface.
    """

    _ddb_resource = None
    _ddb_table = None

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.dynamodb")
        cfg = AKConfig.get().thread.dynamodb
        if cfg is None or not cfg.table_name:
            raise ValueError("AKConfig.thread.dynamodb.table_name must be set to use DynamoDBThreadStore")
        self._table_name = cfg.table_name
        self._ttl = cfg.ttl

    @property
    def table(self):
        """
        Returns the boto3 DynamoDB Table resource, connecting lazily if needed.
        """
        if self._ddb_table is None:
            self._connect()
        return self._ddb_table

    def _connect(self):
        """
        Establish a connection to DynamoDB and resolve the configured table, with retries.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to DynamoDB resource")
                self._ddb_resource = boto3.resource("dynamodb")
                self._ddb_table = self._ddb_resource.Table(self._table_name)
                self._ddb_table.load()
                self._log.debug("Connected to DynamoDB table %s", self._table_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning("DynamoDB connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err:
            raise last_err

    def _expiry(self) -> Optional[int]:
        return int(time.time()) + int(self._ttl) if self._ttl and self._ttl > 0 else None

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata item. Creation is conditional: if a
        concurrent request already created the thread, the existing metadata
        is returned untouched.
        :param thread: The thread to persist.
        :return: The persisted (or already existing) thread.
        """
        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        item = {
            "session_id": thread.session_id,
            "sk": _META_SK,
            "data": metadata.model_dump_json(),
            "user_id": thread.user_id,
            "updated_at": metadata.updated_at.isoformat(),
        }
        if thread.group_id:
            item["group_id"] = thread.group_id
        expiry = self._expiry()
        if expiry is not None:
            item["expiry_time"] = expiry
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(session_id)")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return self.load_metadata(thread.session_id)
        return metadata

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata item by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        resp = self.table.get_item(Key={"session_id": session_id, "sk": _META_SK})
        item = resp.get("Item")
        if not item:
            return None
        return self._to_thread(item)

    @staticmethod
    def _to_thread(item: dict) -> Thread:
        """Build a Thread from a metadata item, applying the authoritative
        top-level updated_at attribute over the (possibly stale) value embedded
        in the data blob."""
        thread = Thread.model_validate_json(item["data"])
        if item.get("updated_at"):
            thread.updated_at = datetime.datetime.fromisoformat(item["updated_at"])
        return thread

    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Append a message as a new item and blind-update the metadata updated_at.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        meta = self.table.get_item(Key={"session_id": session_id, "sk": _META_SK}).get("Item")
        if not meta:
            raise KeyError(f"Thread {session_id} not found")

        expiry = self._expiry()
        item = {
            "session_id": session_id,
            "sk": f"{_MSG_PREFIX}{_new_seq()}",
            "data": message.model_dump_json(),
        }
        if expiry is not None:
            item["expiry_time"] = expiry
        self.table.put_item(Item=item)

        # Blind-update the metadata item's updated_at (and refresh its TTL so an
        # actively-used thread's metadata does not expire mid-conversation).
        # Attribute names use placeholders to stay safe against reserved words.
        set_clauses = ["#updated = :t"]
        names = {"#updated": "updated_at"}
        values = {":t": _utc_now().isoformat()}
        if expiry is not None:
            set_clauses.append("#expiry = :e")
            names["#expiry"] = "expiry_time"
            values[":e"] = expiry
        self.table.update_item(
            Key={"session_id": session_id, "sk": _META_SK},
            UpdateExpression="SET " + ", ".join(set_clauses),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages, ordered chronologically by sort key.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message.
        :return: A tuple of (messages page, next_offset).
        """
        if offset < 0:
            offset = 0
        needed = offset + limit + 1  # one extra to detect a following page
        condition = Key("session_id").eq(session_id) & Key("sk").begins_with(_MSG_PREFIX)

        items: list = []
        resp = self.table.query(KeyConditionExpression=condition, ScanIndexForward=True, Limit=needed)
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp and len(items) < needed:
            resp = self.table.query(
                KeyConditionExpression=condition,
                ScanIndexForward=True,
                Limit=needed - len(items),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))

        messages = [ThreadMessage.model_validate_json(it["data"]) for it in items[offset : offset + limit]]
        next_offset = offset + limit if len(items) > offset + limit else None
        return messages, next_offset

    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Thread], Optional[int]]:
        """
        List thread metadata filtered by user_id and/or group_id via a table scan
        of metadata items, most-recently updated first.
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads to return.
        :param offset: Zero-based index of the first thread.
        :return: A tuple of (threads page, next_offset).
        """
        from .base import paginate

        filter_expression = Attr("sk").eq(_META_SK)
        if user_id is not None:
            filter_expression = filter_expression & Attr("user_id").eq(user_id)
        if group_id is not None:
            filter_expression = filter_expression & Attr("group_id").eq(group_id)

        threads: List[Thread] = []
        resp = self.table.scan(FilterExpression=filter_expression)
        while True:
            for item in resp.get("Items", []):
                threads.append(self._to_thread(item))
            if "LastEvaluatedKey" not in resp:
                break
            resp = self.table.scan(FilterExpression=filter_expression, ExclusiveStartKey=resp["LastEvaluatedKey"])

        threads.sort(key=lambda t: t.updated_at, reverse=True)
        return paginate(threads, limit, offset)

    def clear(self) -> None:
        """
        Scan the entire table and delete all items.

        This is a destructive operation intended for development/testing only.
        """
        with self.table.batch_writer() as batch:
            resp = self.table.scan(ProjectionExpression="session_id, sk")
            while True:
                for item in resp.get("Items", []):
                    batch.delete_item(Key={"session_id": item["session_id"], "sk": item["sk"]})
                if "LastEvaluatedKey" not in resp:
                    break
                resp = self.table.scan(ProjectionExpression="session_id, sk", ExclusiveStartKey=resp["LastEvaluatedKey"])
