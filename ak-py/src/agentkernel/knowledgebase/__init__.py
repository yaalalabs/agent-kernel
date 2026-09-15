"""Knowledge base backends for Agent Kernel.

Only the capability model, the record typing and the error hierarchy are re-exported
here. The backends themselves stay behind their own modules on purpose: each pulls an
optional SDK (``chromadb``, ``neo4j``, ``trino``), so importing this package must not
require any of them.
"""

from .base import KnowledgeBase, Record
from .errors import KnowledgeCapabilityError, KnowledgeError, KnowledgePathError
from .knowledgebuilder import KnowledgeBuilder
from .model import KnowledgeCapabilities, KnowledgeMetadata, KnowledgeRecord

__all__ = [
    "KnowledgeBase",
    "KnowledgeBuilder",
    "KnowledgeCapabilities",
    "KnowledgeCapabilityError",
    "KnowledgeError",
    "KnowledgeMetadata",
    "KnowledgePathError",
    "KnowledgeRecord",
    "Record",
]
