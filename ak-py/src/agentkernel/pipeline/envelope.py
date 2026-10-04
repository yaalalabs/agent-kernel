from enum import StrEnum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

# Standard message-attribute names carried alongside the body (spec §2). Transports map these to
# their native metadata mechanism (SQS message attributes, Kafka headers, NATS headers).
ATTR_REQUEST_ID = "request_id"
ATTR_USER_ID = "user_id"
ATTR_ENDPOINT_URL = "endpoint_url"
ATTR_STATUS_CODE = "status_code"
ATTR_INTEGRATION = "integration"
ATTR_THREAD = "thread"
ATTR_AGUI = "agui"
REPLY_CONTEXT_PREFIX = "reply_"


class QueueName(StrEnum):
    """The two pipeline queues."""

    INPUT = "input"
    OUTPUT = "output"


class QueueMessage(BaseModel):
    """Normalized queue message envelope: the only message shape pipeline components speak.

    ``native`` carries the transport-native handle (e.g. a raw boto3 record) for the transport's
    own ack/nack bookkeeping and for legacy consumers that still expect raw records; it is
    excluded from serialization.
    """

    body: str = ""
    attributes: Dict[str, str] = Field(default_factory=dict)
    group_id: Optional[str] = None
    dedup_id: Optional[str] = None
    receive_count: int = 1
    message_id: Optional[str] = None
    native: Any = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)
