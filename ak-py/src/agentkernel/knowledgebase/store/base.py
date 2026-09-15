"""The storage axis: bytes at store-relative paths, and the containment rule around them.

A ``DocumentStore`` answers "where do the bytes live", and knows nothing about how they are
structured. That separation is what lets one document backend serve a bundle from a local
directory in development and from S3 in production without the backend changing.

Containment is implemented here, once, rather than in each store. Paths reaching a store are
not all agent-supplied — a manifest walk emits them, and a link read out of a document becomes
one — so every entrypoint and every path a store *emits* goes through
:meth:`normalise_relative`.
"""

import posixpath
import re
from abc import ABC, abstractmethod

from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ..errors import KnowledgeCapabilityError, KnowledgePathError

# A bare path (./bundle, /srv/kb) or a dotted path must never look like a scheme, so the
# match is anchored and requires "://" rather than a bare colon.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

_PYTHON_PREFIX = "python:"
_FILE_PREFIX = "file://"
_S3_PREFIX = "s3://"


class DocumentStore(ABC):
    """
    Byte storage addressed by store-relative paths.

    Implementations must call :meth:`normalise_relative` on every path they accept and on
    every path :meth:`list` emits, and must call :meth:`_check_writable` before any write.
    """

    @staticmethod
    def normalise_relative(path: str) -> str:
        """
        Reduce a path to a store-relative POSIX path, refusing anything that escapes the store.

        Static so a caller can normalise a path without owning a store, and so every
        implementation shares one definition of what containment means.

        :param path: Caller-supplied path, in either separator style.
        :return: Normalised store-relative path; the empty string means the store root.
        :raises KnowledgePathError: If the path is absolute or resolves outside the store.
        """
        candidate = (path or "").strip().replace("\\", "/")
        if candidate.startswith("/"):
            raise KnowledgePathError(f"absolute path is not addressable in a document store: {path!r}")

        normalised = posixpath.normpath(candidate)
        if normalised in (".", ""):
            return ""
        if normalised == ".." or normalised.startswith("../"):
            raise KnowledgePathError(f"path escapes the store namespace: {path!r}")
        return normalised

    @property
    @abstractmethod
    def writable(self) -> bool:
        """
        Report whether this store accepts writes.

        :return: True when :meth:`write_bytes` is usable.
        """

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """
        Return the full contents of one document.

        :param path: Store-relative path.
        :return: Document bytes.
        :raises FileNotFoundError: If no document exists at that path.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Report whether a document exists.

        :param path: Store-relative path.
        :return: True when a document exists at that path.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """

    @abstractmethod
    def list(self, prefix: str = "") -> list[str]:
        """
        List every document under a namespace.

        Ordering is globally lexicographic over the returned paths, not per-directory, so
        callers that truncate a listing truncate it identically everywhere.

        :param prefix: Namespace to list; empty lists the whole store.
        :return: Sorted store-relative paths.
        :raises KnowledgePathError: If the prefix escapes the store namespace.
        """

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """
        Write one document, replacing any existing contents.

        :param path: Store-relative path.
        :param data: Bytes to store.
        :return: None.
        :raises KnowledgeCapabilityError: If the store is not writable.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """

    def read_prefix_bytes(self, path: str, max_bytes: int) -> bytes:
        """
        Return at most the first ``max_bytes`` of a document.

        The default reads the whole document and slices it. A store whose transport can
        serve a partial read should override this: a caller that only needs a header must
        not have to pay for every document in full. Any override owes the same answer for a
        non-positive ``max_bytes`` — no bytes, rather than a slice counted from the end.

        :param path: Store-relative path.
        :param max_bytes: Maximum number of bytes to return; ``0`` or less returns ``b""``.
        :return: Leading bytes of the document.
        :raises FileNotFoundError: If no document exists at that path.
        """
        if max_bytes <= 0:
            return b""
        return self.read_bytes(path)[:max_bytes]

    def close(self) -> None:
        """
        Release any resources the store holds.

        :return: None.
        """

    def _check_writable(self) -> None:
        """
        Refuse a write on a read-only store before any I/O is attempted.

        :return: None.
        :raises KnowledgeCapabilityError: If the store is not writable.
        """
        if not self.writable:
            raise KnowledgeCapabilityError(type(self).__name__, "write_bytes")

    @staticmethod
    def from_uri(uri: str, **kwargs) -> "DocumentStore":
        """
        Resolve a configuration string to a store instance.

        Accepts ``s3://bucket/prefix``, ``file:///abs/path``, ``python:pkg.mod.ClassName``
        for a bring-your-own store, or a bare filesystem path.

        The ``python:`` discriminator is mandatory rather than inferred, because a dotted
        path is itself a valid bare filesystem path: without it, ``mypkg.stores.GitStore``
        would silently become a local store rooted at a directory that does not exist.

        :param uri: Store location or dotted path.
        :param kwargs: Constructor arguments forwarded to the resolved store.
        :return: The resolved store.
        :raises AKConfigError: If the scheme is unknown or a dotted path does not resolve.
        """
        value = (uri or "").strip()

        if value.startswith(_PYTHON_PREFIX):
            dotted = value[len(_PYTHON_PREFIX) :].strip()
            return resolve_dotted(dotted, base=DocumentStore, error=AKConfigError)(**kwargs)

        if value.startswith(_S3_PREFIX):
            with require_extra("aws", "s3:// document store"):
                from .s3 import S3DocumentStore

            bucket, _, prefix = value[len(_S3_PREFIX) :].partition("/")
            if not bucket:
                raise AKConfigError(f"s3:// document store needs a bucket: {uri!r}")
            return S3DocumentStore(bucket, prefix, **kwargs)

        if value.startswith(_FILE_PREFIX):
            from .local import LocalDocumentStore

            return LocalDocumentStore(value[len(_FILE_PREFIX) :], **kwargs)

        if _SCHEME.match(value):
            raise AKConfigError(f"unsupported document store scheme: {uri!r}; expected s3://, file://, python:, or a filesystem path")

        from .local import LocalDocumentStore

        return LocalDocumentStore(value, **kwargs)
