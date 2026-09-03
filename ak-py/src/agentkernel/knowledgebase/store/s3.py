"""S3-backed document store. Requires the existing ``aws`` extra; no new extra."""

import logging
from typing import Any, Optional

from ...core.util.driver.s3 import S3Driver
from ..errors import KnowledgePathError
from .base import DocumentStore

log = logging.getLogger("ak.knowledgebase.store.s3")


class S3DocumentStore(DocumentStore):
    """
    Documents held under a key prefix in an S3 bucket.

    The connection layer — client creation, retry, ranged GETs, pagination, and the
    not-found translation — belongs to the shared :class:`S3Driver`. What stays here is
    what a document store means by a path: the prefix key schema, containment, namespace
    listing, and ordering.

    ``writable`` is declared, never probed: an object store cannot report whether a write
    would be permitted without attempting one, so an application serving a read-only
    prefix says so at construction.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: Optional[str] = None,
        client: Optional[Any] = None,
        writable: bool = True,
    ) -> None:
        """
        Open an S3 prefix as a document store.

        :param bucket: Bucket holding the documents.
        :param prefix: Key prefix the store is rooted at.
        :param region: AWS region for the default client.
        :param client: Pre-built S3 client; the injection seam used by tests.
        :param writable: Whether writes are allowed.
        :return: None.
        """
        self._prefix = self.normalise_relative(prefix)
        self._writable = bool(writable)
        self._driver = S3Driver(bucket, region=region, client=client)

    @property
    def writable(self) -> bool:
        """
        Report whether this store accepts writes.

        :return: True when writes are allowed.
        """
        return self._writable

    def _key(self, path: str) -> str:
        """
        Map a store-relative path to an absolute object key.

        :param path: Store-relative path.
        :return: Object key including the store prefix.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        relative = self.normalise_relative(path)
        if not self._prefix:
            return relative
        return f"{self._prefix}/{relative}" if relative else self._prefix

    def _relative(self, key: str) -> Optional[str]:
        """
        Map an object key back to a store-relative path.

        :param key: Object key as S3 returned it.
        :return: Store-relative path, or None when the key is outside the store prefix.
        """
        if not self._prefix:
            return self.normalise_relative(key)

        marker = f"{self._prefix}/"
        if not key.startswith(marker):
            return None
        return self.normalise_relative(key[len(marker) :])

    def read_bytes(self, path: str) -> bytes:
        """
        Return the full contents of one document.

        :param path: Store-relative path.
        :return: Document bytes.
        :raises FileNotFoundError: If no object exists at that key.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        return self._driver.get_bytes(self._key(path))

    def read_prefix_bytes(self, path: str, max_bytes: int) -> bytes:
        """
        Return at most the first ``max_bytes`` of a document, using a ranged GET.

        This is the reason the method exists on the base: a caller that only needs a
        document header must not pay to transfer whole documents out of S3.

        :param path: Store-relative path.
        :param max_bytes: Maximum number of bytes to return; ``0`` or less returns ``b""``.
        :return: Leading bytes of the document.
        :raises FileNotFoundError: If no object exists at that key.
        """
        if max_bytes <= 0:
            return b""
        return self._driver.get_range_bytes(self._key(path), 0, max_bytes - 1)

    def exists(self, path: str) -> bool:
        """
        Report whether a document exists.

        :param path: Store-relative path.
        :return: True when an object exists at that key.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        return self._driver.exists(self._key(path))

    def list(self, prefix: str = "") -> list[str]:
        """
        List every document under a namespace, in global lexicographic order.

        :param prefix: Namespace to list; empty lists the whole store.
        :return: Sorted store-relative paths.
        :raises KnowledgePathError: If the prefix escapes the store namespace.
        """
        namespace = self.normalise_relative(prefix)
        # A namespace match is a directory match, matching LocalDocumentStore: listing
        # "tables" must not also return "tables_extra/x.md".
        key_prefix = self._key(namespace)
        if key_prefix:
            key_prefix = f"{key_prefix}/"

        matches: list[str] = []
        for key in self._driver.list_keys(key_prefix):
            # A key ending in "/" is a console-created folder marker, not a document.
            if key.endswith("/"):
                continue
            try:
                relative = self._relative(key)
            except KnowledgePathError:
                log.warning("[s3.list] skipping key that does not normalise to a store path: %r", key)
                continue
            if relative:
                matches.append(relative)

        # The driver returns keys in S3's paging order; the global sort is what makes a
        # truncated listing identical everywhere.
        return sorted(matches)

    def write_bytes(self, path: str, data: bytes) -> None:
        """
        Write one document, replacing any existing object.

        :param path: Store-relative path.
        :param data: Bytes to store.
        :return: None.
        :raises KnowledgeCapabilityError: If the store is not writable.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        self._check_writable()
        self._driver.put_bytes(self._key(path), data)
