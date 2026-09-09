"""Local-filesystem document store. Stdlib only; no optional extra."""

import logging
import os
from typing import Optional

from ..errors import KnowledgePathError
from .base import DocumentStore

log = logging.getLogger("ak.knowledgebase.store.local")


class LocalDocumentStore(DocumentStore):
    """
    Documents held in a directory tree on the local filesystem.

    Containment is enforced twice: on every path the caller supplies, and again on every
    file the walk finds. The second check is what stops a symlink planted inside the root
    from serving a file outside it.
    """

    def __init__(self, root: str, writable: Optional[bool] = None) -> None:
        """
        Open a directory as a document store.

        :param root: Directory holding the documents.
        :param writable: Whether writes are allowed; ``None`` probes the directory.
        :return: None.
        :raises ValueError: If the root is not an existing directory.
        """
        self._root = os.path.realpath(root)
        if not os.path.isdir(self._root):
            raise ValueError(f"LocalDocumentStore root is not an existing directory: {root!r}")

        # Probing is right for a filesystem and wrong for object storage, where a
        # permission cannot be read without attempting a write.
        self._writable = os.access(self._root, os.W_OK) if writable is None else bool(writable)

    @property
    def writable(self) -> bool:
        """
        Report whether this store accepts writes.

        :return: True when writes are allowed.
        """
        return self._writable

    def _contained_path(self, path: str) -> str:
        """
        Resolve a store-relative path to an absolute path proven to stay inside the root.

        :param path: Store-relative path.
        :return: Absolute filesystem path.
        :raises KnowledgePathError: If the path, once symlinks are resolved, leaves the root.
        """
        relative = self.normalise_relative(path)
        full_path = os.path.join(self._root, relative) if relative else self._root
        if not self._is_contained(full_path):
            raise KnowledgePathError(f"path resolves outside the store namespace: {path!r}")
        return full_path

    def _is_contained(self, full_path: str) -> bool:
        """
        Report whether a filesystem path stays inside the root once symlinks are resolved.

        :param full_path: Absolute filesystem path to check.
        :return: True when the resolved path is the root or lies beneath it.
        """
        resolved = os.path.realpath(full_path)
        try:
            return os.path.commonpath([self._root, resolved]) == self._root
        except ValueError:
            # Different drives on Windows, which cannot share a common path.
            return False

    def read_bytes(self, path: str) -> bytes:
        """
        Return the full contents of one document.

        :param path: Store-relative path.
        :return: Document bytes.
        :raises FileNotFoundError: If no document exists at that path.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        with open(self._contained_path(path), "rb") as handle:
            return handle.read()

    def read_prefix_bytes(self, path: str, max_bytes: int) -> bytes:
        """
        Return at most the first ``max_bytes`` of a document, reading no further.

        :param path: Store-relative path.
        :param max_bytes: Maximum number of bytes to return; ``0`` or less returns ``b""``.
        :return: Leading bytes of the document.
        :raises FileNotFoundError: If no document exists at that path.
        """
        if max_bytes <= 0:
            # read() takes a negative size as "the whole file", which is the opposite of the
            # bound this method promises.
            return b""
        with open(self._contained_path(path), "rb") as handle:
            return handle.read(max_bytes)

    def exists(self, path: str) -> bool:
        """
        Report whether a document exists.

        :param path: Store-relative path.
        :return: True when a regular file exists at that path.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        return os.path.isfile(self._contained_path(path))

    def list(self, prefix: str = "") -> list[str]:
        """
        List every document under a namespace, in global lexicographic order.

        The walk is rooted at the namespace, so listing one directory costs that directory
        rather than the whole tree. That rooting is also what makes a namespace match a directory
        match, as both stores must: listing "tables" cannot reach "tables_extra/x.md".

        A file whose real path leaves the root — reached through a symlink planted inside
        it — is skipped with a warning rather than listed.

        :param prefix: Namespace to list; empty lists the whole store.
        :return: Sorted store-relative paths.
        :raises KnowledgePathError: If the prefix escapes the store namespace.
        """
        top = self._contained_path(prefix)

        matches: list[str] = []
        for directory, _, filenames in os.walk(top, followlinks=False):
            for filename in filenames:
                full_path = os.path.join(directory, filename)
                if not self._is_contained(full_path):
                    log.warning("[local.list] skipping entry resolving outside the store root: %r", full_path)
                    continue

                matches.append(self.normalise_relative(os.path.relpath(full_path, self._root)))

        # os.walk orders per directory, which is not globally lexicographic ("a/z.md" sorts
        # after "ab/b.md" within the walk but before it globally). Callers truncate this
        # list, so the global order is the one that has to be stable.
        return sorted(matches)

    def write_bytes(self, path: str, data: bytes) -> None:
        """
        Write one document, creating parent directories as needed.

        :param path: Store-relative path.
        :param data: Bytes to store.
        :return: None.
        :raises KnowledgeCapabilityError: If the store is not writable.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        self._check_writable()
        full_path = self._contained_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as handle:
            handle.write(data)
