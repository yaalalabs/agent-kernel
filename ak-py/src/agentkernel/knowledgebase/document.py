"""The intermediate base for knowledge bases addressed by document path.

``DocumentKnowledgeBase`` sits between :class:`~agentkernel.knowledgebase.base.KnowledgeBase`
and any backend whose records are documents at paths. It exists because three behaviours are
identical for every such backend and worth writing once: holding the
:class:`~agentkernel.knowledgebase.store.base.DocumentStore`, folding the store's writability
into the capability declaration, and mapping "no such document" to an empty result rather than
an exception.

It adds no capability of its own, so it stays abstract — ``backend_name``, ``connect`` and
``get_description`` are still the subclass's to implement.

Containment is *not* implemented here. The store is the only place an escaping path is
detected, and each operation decides for itself what to do about the refusal, because dropping
one path out of a ``fetch`` list and refusing a whole ``write`` record are different answers.
"""

import logging
from abc import ABC

from .base import KnowledgeBase
from .model import KnowledgeCapabilities
from .store.base import DocumentStore

log = logging.getLogger("ak.knowledgebase.document")


class DocumentKnowledgeBase(KnowledgeBase, ABC):
    """
    Knowledge held as documents at paths in a :class:`DocumentStore`.

    Subclasses supply the representation — how a document's bytes become records — while the
    store supplies the bytes. That split is what lets one backend serve the same collection
    from a local directory in development and from an object store in production.
    """

    def __init__(self, store: DocumentStore, capabilities: KnowledgeCapabilities, name: str | None = None) -> None:
        """
        Compose a store with a capability declaration.

        :param store: Where the documents live.
        :param capabilities: What the backend supports, before the store is taken into account.
        :param name: Backend name used in validation errors. Defaults to the class name.
        :return: None.
        :raises ValueError: If the resulting declaration is unreachable or query-incoherent.
        """
        self._store = store
        # Folded with `and` so the more restrictive side always wins: a read-only store beats a
        # backend declaring writable=True, and a backend that chooses not to write beats a
        # writable store. This is why capabilities are per instance rather than per class.
        capabilities = capabilities.model_copy(update={"writable": capabilities.writable and store.writable})
        super().__init__(capabilities=capabilities, name=name)

    @property
    def store(self) -> DocumentStore:
        """
        Return the store this backend reads from.

        :return: The composed document store.
        """
        return self._store

    def _read_document(self, path: str) -> bytes | None:
        """
        Read one document, treating absence as an empty answer rather than a failure.

        Finding nothing is not an error in this tier, so a missing document degrades to
        ``None`` and a logged warning. ``KnowledgePathError`` is deliberately left to
        propagate: an escaping path is a different situation, and each operation handles it at
        its own boundary.

        "Nothing here" covers more than absence. A ``browse`` hands the agent directory
        records, and feeding one back to ``fetch`` reaches ``open()`` on a directory — an
        ``OSError`` that is not a ``FileNotFoundError``, and one that would otherwise abort a
        whole batch over a single unusable id.

        :param path: Store-relative path.
        :return: The document bytes, or ``None`` when no document can be read there.
        :raises KnowledgePathError: If the path escapes the store namespace.
        """
        try:
            return self._store.read_bytes(path)
        except FileNotFoundError:
            log.warning("[%s] document not found: %s", self.backend_name, path)
            return None
        except OSError as error:
            log.warning("[%s] document not readable: %s (%s)", self.backend_name, path, error)
            return None

    def close(self) -> None:
        """
        Release the store's resources.

        :return: None.
        """
        self._store.close()
