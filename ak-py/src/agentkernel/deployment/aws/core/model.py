from typing import Optional

from pydantic import BaseModel, ConfigDict


class SQSQueueInputMessage(BaseModel):
	"""Typed FIFO SQS send_message kwargs excluding QueueUrl."""

	MessageBody: str # a stringified JSON of the message content
	MessageGroupId: Optional[str] = None
	MessageDeduplicationId: Optional[str] = None

	model_config = ConfigDict(extra="allow")
