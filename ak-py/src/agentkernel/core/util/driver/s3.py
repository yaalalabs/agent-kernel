"""Shared S3 connection driver."""

from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from .base import BaseDriver

# The codes S3 reports for "that object is not there", across get_object and head_object.
_MISSING_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


class S3Driver(BaseDriver):
    """
    S3 connection driver parameterized by bucket.

    Owns the connection lifecycle (lazy boto3 client, with retry) and a generic
    byte-oriented object surface keyed by absolute object key; key schemas, prefixes,
    and path containment stay in the consuming stores.

    Unlike the DynamoDB driver, connecting performs no probe call: the S3 equivalent of
    ``Table.load()`` is ``head_bucket``, which requires a bucket-level permission a
    consumer scoped to a single read-only prefix legitimately may not hold. A bad bucket
    therefore surfaces on first use rather than at construction.
    """

    def __init__(self, bucket: str, region: Optional[str] = None, client: Optional[Any] = None):
        """
        Initialize the driver. Constructor arguments are trusted; config reading and
        validation happen in the stores.

        :param bucket: S3 bucket name.
        :param region: AWS region name; defaults to the boto3 environment default.
        :param client: Pre-built S3 client, used as the injection seam in tests.
        """
        super().__init__("ak.core.util.driver.s3")
        if not bucket:
            raise ValueError("S3Driver requires a bucket name.")
        self._bucket = bucket
        self._region = region
        self._client = client

    @property
    def bucket(self) -> str:
        """
        Returns the bucket this driver is bound to.

        :return: S3 bucket name.
        """
        return self._bucket

    @property
    def client(self):
        """
        Returns the boto3 S3 client, connecting lazily if needed.

        :return: The boto3 S3 client.
        """
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._connect()
        return self._client

    def _connect(self) -> None:
        """Creates the boto3 S3 client, with retries."""

        def connect():
            self._log.debug("Creating S3 client region=%s", self._region)
            return boto3.client("s3", region_name=self._region)

        self._client = self._connect_with_retries(connect, Exception)

    @staticmethod
    def _error_code(exc: ClientError) -> str:
        """Extracts the S3 error code from a client error, or '' when absent."""
        return str(exc.response.get("Error", {}).get("Code", ""))

    def _missing(self, key: str) -> FileNotFoundError:
        """Builds the not-found error consumers see instead of a ClientError."""
        return FileNotFoundError(f"no such object: s3://{self._bucket}/{key}")

    def get_bytes(self, key: str) -> bytes:
        """
        Get a whole object's body.

        :param key: Absolute object key.
        :return: The object's bytes.
        :raises FileNotFoundError: If no object exists at that key.
        """
        try:
            response = self.client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            # Consumers see one exception type for "absent", whatever the storage backend.
            if self._error_code(e) in _MISSING_CODES:
                raise self._missing(key) from e
            self._log.error("Failed to get object %s from bucket %s: %s", key, self._bucket, e)
            raise
        return response["Body"].read()

    def get_range_bytes(self, key: str, start: int, end: int) -> bytes:
        """
        Get a byte range of an object, using a ranged GET so only that range is transferred.

        ``start`` and ``end`` are inclusive, matching S3's ``Range`` header. An object too
        short for the range (including a zero-length one) falls back to a full get rather
        than failing, so callers get whatever bytes exist.

        :param key: Absolute object key.
        :param start: First byte offset to return.
        :param end: Last byte offset to return, inclusive.
        :return: The requested bytes, or fewer if the object is shorter.
        :raises FileNotFoundError: If no object exists at that key.
        """
        try:
            response = self.client.get_object(Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}")
        except ClientError as e:
            code = self._error_code(e)
            if code in _MISSING_CODES:
                raise self._missing(key) from e
            if code == "InvalidRange":
                return self.get_bytes(key)
            self._log.error("Failed to get range %s-%s of object %s: %s", start, end, key, e)
            raise
        return response["Body"].read()

    def put_bytes(self, key: str, data: bytes) -> None:
        """
        Put an object, replacing any existing body.

        :param key: Absolute object key.
        :param data: Bytes to store.
        """
        try:
            self.client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except ClientError as e:
            self._log.error("Failed to put object %s into bucket %s: %s", key, self._bucket, e)
            raise

    def exists(self, key: str) -> bool:
        """
        Report whether an object exists.

        :param key: Absolute object key.
        :return: True when an object exists at that key.
        """
        try:
            self.client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if self._error_code(e) in _MISSING_CODES:
                return False
            self._log.error("Failed to head object %s in bucket %s: %s", key, self._bucket, e)
            raise
        return True

    def list_keys(self, prefix: str = "") -> list[str]:
        """
        List every object key under a prefix, following ``NextContinuationToken`` pagination.

        Keys are returned in the order S3 pages them; ordering guarantees belong to the
        consuming store, which knows what its paths mean.

        :param prefix: Absolute key prefix; empty lists the whole bucket.
        :return: A list of raw object keys.
        """
        keys: list[str] = []
        token: Optional[str] = None
        try:
            while True:
                kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token

                response = self.client.list_objects_v2(**kwargs)
                keys.extend(item["Key"] for item in response.get("Contents", []) if "Key" in item)

                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")
                if not token:
                    break
        except ClientError as e:
            self._log.error("Failed to list keys under %r in bucket %s: %s", prefix, self._bucket, e)
            raise
        return keys
