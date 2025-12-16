import logging
import time
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key as DDBKey
from boto3.dynamodb.types import Binary

from ..base import Session
from ..config import AKConfig
from .base import SessionCache, SessionStore
from .serde import BinarySerde


class DynamoDBDriver:
    """
    DynamoDBDriver provides connection management and helpers for a simple
    three-attribute item layout: session_id, key and value (Binary).
    """

    _ddb_resource = None
    _ddb_table = None

    def __init__(self):
        self._log = logging.getLogger("ak.core.session.dynamodb.driver")
        cfg = AKConfig.get().session.dynamodb
        if cfg is None or not cfg.table_name:
            raise ValueError("AKConfig.session.dynamodb.table_name must be set to use DynamoDBSessionStore")
        self._table_name = cfg.table_name
        self._ttl = cfg.ttl

    @property
    def table(self):
        """
        Returns the boto3 DynamoDB Table resource, connecting lazily if needed.

        :return: The DynamoDB Table resource for the configured table name.
        """
        if self._ddb_table is None:
            self._connect()
        return self._ddb_table

    def _connect(self):
        """
        Establish a connection to DynamoDB and resolve the configured table.

        Retries a few times with a small delay between attempts. Raises the last
        encountered exception if all attempts fail.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to DynamoDB resource")
                self._ddb_resource = boto3.resource("dynamodb")
                self._ddb_table = self._ddb_resource.Table(self._table_name)
                # lightweight call to ensure table exists/accessible
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

    def put(self, session_id: str, key: str, value: bytes) -> None:
        """
        Put a single item for the given session and key.

        When TTL is configured (> 0), attaches an `expiry_time` attribute with a
        UNIX epoch (seconds) timestamp for DynamoDB TTL.

        :param session_id: The session identifier (partition key).
        :param key: The item key within the session (sort key).
        :param value: The serialized value as bytes.
        """
        try:
            item = {
                "session_id": session_id,
                "key": key,
                "value": Binary(value),
            }
            if self._ttl and self._ttl > 0:
                item["expiry_time"] = int(time.time()) + int(self._ttl)
            self.table.put_item(Item=item)
        except Exception as e:
            self._log.error("Failed to put item session_id=%s key=%s: %s", session_id, key, e)
            raise

    def get(self, session_id: str, key: str) -> Optional[bytes]:
        """
        Get a single item's raw bytes for the given session and key.

        :param session_id: The session identifier (partition key).
        :param key: The item key within the session (sort key).
        :return: The stored bytes value, or None if the item does not exist.
        """
        try:
            resp = self.table.get_item(Key={"session_id": session_id, "key": key})
            item = resp.get("Item")
            if not item:
                return None
            val = item.get("value")
            # boto3 Binary objects expose .value or are bytes-like
            if hasattr(val, "value"):
                return val.value
            return val
        except Exception as e:
            self._log.error("Failed to get item session_id=%s key=%s: %s", session_id, key, e)
            raise

    def query_keys(self, session_id: str) -> list[str]:
        """
        Query for all sort keys associated with a given session partition key.

        :param session_id: The session identifier (partition key).
        :return: A list of keys (sort keys) stored under the session.
        """
        keys: list[str] = []
        try:
            kwargs = {"KeyConditionExpression": DDBKey("session_id").eq(session_id)}
            resp = self.table.query(**kwargs)
            items = resp.get("Items", [])
            keys.extend([it.get("key") for it in items if "key" in it])
            # pagination
            while "LastEvaluatedKey" in resp:
                resp = self.table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
                items = resp.get("Items", [])
                keys.extend([it.get("key") for it in items if "key" in it])
        except Exception as e:
            self._log.error("Failed to query keys for session_id=%s: %s", session_id, e)
            raise
        return keys

    def scan_and_clear_all(self) -> None:
        """
        Scan the entire table and delete all items.

        Intended for development/test parity with Redis clear by prefix. Use with
        extreme caution in shared environments.
        """
        try:
            with self.table.batch_writer() as batch:
                resp = self.table.scan(
                    ProjectionExpression="#pk,#sk",
                    ExpressionAttributeNames={
                        "#pk": "session_id",
                        "#sk": "key",
                    },
                )
                items = resp.get("Items", [])
                for it in items:
                    batch.delete_item(Key={"session_id": it["session_id"], "key": it["key"]})
                while "LastEvaluatedKey" in resp:
                    resp = self.table.scan(
                        ProjectionExpression="#pk,#sk",
                        ExpressionAttributeNames={"#pk": "session_id", "#sk": "key"},
                        ExclusiveStartKey=resp["LastEvaluatedKey"],
                    )
                    items = resp.get("Items", [])
                    for it in items:
                        batch.delete_item(Key={"session_id": it["session_id"], "key": it["key"]})
        except Exception as e:
            self._log.error("Failed to clear DynamoDB table %s: %s", self._table_name, e)
            raise


class DynamoDBSessionStore(SessionStore):
    """
    DynamoDB-backed implementation of SessionStore.
    Table schema uses:
      - session_id: partition key (string)
      - key: sort key (string)
      - value: binary attribute (serialized using BinarySerde)
    """

    def __init__(self, cache: SessionCache = None):
        """
        Initialize the DynamoDB-backed SessionStore.

        Prepares the serializer and a DynamoDB driver that encapsulates access
        to the configured table.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.dynamodb")
        self._serde = BinarySerde()
        self._driver = DynamoDBDriver()
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Load a session by its unique identifier.

        Reads all keys for the session from DynamoDB and reconstructs a Session
        by deserializing each value via BinarySerde.

        :param session_id: Unique identifier for the session.
        :param strict: If True, raises a KeyError if the session is not found.
        :return: The populated Session, or a new Session if not found and strict is False.
        """
        self._log.debug(f"Loading dynamodb session with ID {session_id}")
        if self._cache:
            session = self._cache.get(session_id)
            if session:
                self._log.debug(f"Session {session_id} found in cache")
                return session
        keys = self._driver.query_keys(session_id)
        if not keys:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning("Session %s not found, creating new session", session_id)
            return self.new(session_id)

        session = Session(session_id)
        for k in keys:
            payload = self._driver.get(session_id, k)
            if payload is None:
                continue
            session.set(k, self._serde.loads(payload))
        if self._cache:
            self._cache.set(session)
        return session

    def new(self, session_id: str) -> Session:
        """
        Initialize a new, empty Session instance

        :param session_id: Unique identifier for the session.
        :return: A new Session instance for the provided identifier.
        """
        self._log.debug("Creating new session with ID %s", session_id)
        session = Session(session_id)
        if self._cache:
            self._cache.set(session)
        return session

    def store(self, session: Session) -> None:
        """
        Persist all session key/value pairs as individual DynamoDB items.
        :param session: The session to persist.
        """
        for key in session.get_all_keys():
            if key == Session.VOLATILE_CACHE_KEY:  # Do not store volatile cache
                continue
            value = session.get(key)
            payload = self._serde.dumps(value)
            self._driver.put(session.id, key, payload)
        if self._cache:
            self._cache.set(session)

    def clear(self) -> None:
        """
        Clear all items from the configured DynamoDB table.

        This is a destructive operation intended for development/testing only.
        """
        self._driver.scan_and_clear_all()
        if self._cache:
            self._cache.clear()
