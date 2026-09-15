"""Document stores — the storage axis of the knowledge-base tier.

``S3DocumentStore`` is deliberately absent from these exports so importing this package
never pulls in ``boto3``. Reach it through ``DocumentStore.from_uri("s3://…")`` or import
``agentkernel.knowledgebase.store.s3`` directly.
"""

from .base import DocumentStore
from .local import LocalDocumentStore

__all__ = ["DocumentStore", "LocalDocumentStore"]
