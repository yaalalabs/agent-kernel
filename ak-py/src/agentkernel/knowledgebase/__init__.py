"""Knowledge base backends for Agent Kernel.

Names resolve lazily through the PEP 562 ``__getattr__`` below, the same pattern
``agentkernel.deployment.aws`` uses, so that ``import agentkernel.knowledgebase`` costs one
module import and pulls no optional SDK. That matters most for ``S3DocumentStore``: it is
exported here, but ``boto3`` is only imported when the name is actually touched.

``ChromaManager``, ``Neo4jManager`` and ``StarburstManager`` are deliberately **not** exported.
Each imports its SDK at module import, so a lazy export would still make ``chromadb`` /
``neo4j`` / ``trino`` a hard requirement the moment an agent touched the name — and the
applications that use them already import them from their concrete modules.
"""

import importlib
from typing import TYPE_CHECKING, Any

# name -> submodule providing it. Resolved lazily by __getattr__ so importing this package
# never pulls boto3 (via .store.s3) for an application that only reads a local bundle.
_LAZY_EXPORTS = {
    # core abstractions
    "KnowledgeBase": ".base",
    "Record": ".base",
    "KnowledgeBuilder": ".knowledgebuilder",
    # capability model and record typing
    "KnowledgeCapabilities": ".model",
    "KnowledgeMetadata": ".model",
    "KnowledgeRecord": ".model",
    # errors
    "KnowledgeError": ".errors",
    "KnowledgeCapabilityError": ".errors",
    "KnowledgePathError": ".errors",
    # document-shaped backends: the storage axis
    "DocumentKnowledgeBase": ".document",
    "DocumentStore": ".store.base",
    "LocalDocumentStore": ".store.local",
    "S3DocumentStore": ".store.s3",
    # Open Knowledge Format: the representation axis
    "OKFManager": ".okf.manager",
    "OKFBundle": ".okf.model",
    "OKFConcept": ".okf.model",
    "OKFDiagnostic": ".okf.model",
    "TrustTier": ".okf.model",
}

__all__ = sorted(_LAZY_EXPORTS)

# Not executed at runtime (preserves laziness) — lets mypy/IDEs resolve these names statically.
if TYPE_CHECKING:
    from .base import KnowledgeBase, Record
    from .document import DocumentKnowledgeBase
    from .errors import KnowledgeCapabilityError, KnowledgeError, KnowledgePathError
    from .knowledgebuilder import KnowledgeBuilder
    from .model import KnowledgeCapabilities, KnowledgeMetadata, KnowledgeRecord
    from .okf.manager import OKFManager
    from .okf.model import OKFBundle, OKFConcept, OKFDiagnostic, TrustTier
    from .store.base import DocumentStore
    from .store.local import LocalDocumentStore
    from .store.s3 import S3DocumentStore


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
