from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.util.payload import JSONText

# Standard message-attribute names carried alongside the body (spec §2). Transports map these to
# their native metadata mechanism (SQS message attributes, Kafka headers, NATS headers).
ATTR_REQUEST_ID = "request_id"
ATTR_USER_ID = "user_id"
ATTR_ENDPOINT_URL = "endpoint_url"
ATTR_STATUS_CODE = "status_code"
ATTR_INTEGRATION = "integration"
ATTR_THREAD = "thread"
# Marks an output message as a realtime stream chunk (audio/transcript/interrupt/done), so the
# Response Handler routes it to the integration adapter's deliver_chunk instead of guessing from
# the body shape.
ATTR_REALTIME = "realtime"
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

    ``body`` is JSON **text**, not an object, because that is what a broker carries. Assigning a
    dict or a list encodes it here rather than at the sender, so the rule holds for a transport
    written later: the SQS, Kafka and NATS transports all hand the body straight to the wire, while
    the in-memory one stores the envelope as an object and would have let a dict through.
    """

    body: JSONText = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    group_id: str | None = None
    dedup_id: str | None = None
    receive_count: int = 1
    message_id: str | None = None
    native: Any = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)
