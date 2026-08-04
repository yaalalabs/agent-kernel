from __future__ import annotations

import json
import logging

from ....core.chat_service import ChatService
from ....core.config import AKConfig, ExecutionMode
from ....core.model import BaseRunRequest, StreamChunk
from ..core.sqs_handler import SQSHandler
from .core import ECSSQSConsumer


class ECSAgentRunner(ECSSQSConsumer):
    """
    ECS Agent Runner — polls the Input Queue, runs the agent, and puts
    the result on the Output Queue.

    The ECS equivalent of ServerlessAgentRunner. Instead of being triggered
    by a Lambda Event Source Mapping, it inherits run() from ECSSQSConsumer,
    which drives a blocking long-poll loop — meant to be the container's
    main process.

    ``run()`` dispatches to ``ECSStreamAgentRunner`` when ``execution.mode`` is
    ``STREAM``, re-reading config each call (mirroring ``ECSIOHandler.run``) rather
    than freezing the choice at import time. Users who want the STREAM behavior
    explicitly (or a custom subclass of it) can call ``ECSStreamAgentRunner.run()``
    directly instead.

    Usage::

        if __name__ == "__main__":
            ECSAgentRunner.run()
    """

    _log = logging.getLogger("ak.ecs.agentrunner")
    _chat_service: ChatService | None = None
    _config = AKConfig.get()
    max_receive_count = _config.execution.queues.input.max_receive_count
    num_consumers = _config.execution.queues.input.no_of_consumers

    @classmethod
    def get_queue_url(cls) -> str:
        return cls._config.execution.queues.input.url

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service

    @classmethod
    def _get_record_attributes(cls, raw_queue_message: dict) -> dict:
        """
        Extract routing attributes from a raw SQS message.

        Works with both boto3 receive_message records (PascalCase keys)
        and Lambda event records (camelCase keys).

        :param raw_queue_message: boto3 SQS message dict
        :return: Extracted attributes dict
        :raises ValueError: If request_id is missing
        """
        attributes = SQSHandler.get_message_system_attributes(raw_queue_message)
        message_attributes = SQSHandler.get_message_custom_attributes(raw_queue_message)

        request_id = message_attributes.get("request_id")
        if not request_id:
            raise ValueError("request_id is required in SQS message attributes")

        return {
            # boto3: "MessageGroupId" under Attributes; Lambda: "MessageGroupId" under attributes
            "message_group_id": attributes.get("MessageGroupId"),
            "message_deduplication_id": attributes.get("MessageDeduplicationId"),
            "request_id": request_id,
            "user_id": message_attributes.get("user_id"),
            # Present in WebSocket (ASYNC) mode — the API Gateway endpoint to push the reply back to.
            "endpoint_url": message_attributes.get("endpoint_url"),
        }

    @classmethod
    def _send_to_output_queue(cls, message_body: dict, record_attributes: dict) -> None:
        # Forward endpoint_url (ASYNC mode) so the output consumer can push the reply over WebSocket.
        custom_attributes = []
        if record_attributes.get("endpoint_url"):
            custom_attributes.append(
                SQSHandler.CustomAttribute(name="endpoint_url", value=record_attributes["endpoint_url"], datatype=SQSHandler.AttributeDataType.STRING)
            )

        SQSHandler.send_message_to_output_queue(
            message_body=message_body,
            attributes={
                "message_group_id": record_attributes["message_group_id"],
                "message_deduplication_id": record_attributes["message_deduplication_id"],
            },
            request_id=record_attributes["request_id"],
            user_id=record_attributes["user_id"],
            custom_message_attributes=custom_attributes,
        )

    @classmethod
    def process_message(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.process_message."""
        message_id = record.get("MessageId")
        cls._log.info(f"[AGENT START] Processing message {message_id}")

        body = BaseRunRequest.model_validate(json.loads(record["Body"]))
        record_attributes = cls._get_record_attributes(raw_queue_message=record)

        cls._log.info(
            f"[AGENT PROCESSING] request_id={record_attributes['request_id']}, "
            f"session_id={body.session_id}, agent={body.agent}, prompt={body.prompt[:50] if body.prompt else 'N/A'}"
        )

        _, agent_response = cls._get_chat_service().process_chat_request(req=body)

        cls._log.info(
            f"[AGENT RESPONSE] request_id={record_attributes['request_id']}, "
            f"response_keys={list(agent_response.keys()) if isinstance(agent_response, dict) else 'N/A'}"
        )

        cls._send_to_output_queue(message_body=agent_response, record_attributes=record_attributes)

        cls._log.info(f"[AGENT DONE] Sent to output queue: {SQSHandler.get_output_queue_url()}, " f"request_id={record_attributes['request_id']}")

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.on_permanent_failure. Catches own exceptions."""
        cls._log.error(f"Permanent failure for message {record.get('MessageId')}")
        try:
            record_attributes = cls._get_record_attributes(raw_queue_message=record)
            error_body = {"error": f"Failed to process message after " f"{cls._config.execution.queues.input.max_receive_count} retries"}
            cls._send_to_output_queue(message_body=error_body, record_attributes=record_attributes)
        except Exception:
            cls._log.exception("Failed to send permanent-failure error to output queue")

    @classmethod
    def run(cls) -> None:
        """Dispatch to ECSStreamAgentRunner when execution.mode is STREAM, re-reading config on
        every call (unlike the import-time selection this used to require) so it mirrors
        ECSIOHandler.run's dispatch. Only takes effect when called as ECSAgentRunner.run() itself —
        a subclass's own run() (e.g. ECSStreamAgentRunner's, inherited from here) runs as that
        subclass, never redirected."""
        if cls is ECSAgentRunner and cls._config.execution.mode == ExecutionMode.STREAM:
            return ECSStreamAgentRunner.run()
        return super().run()


class ECSStreamAgentRunner(ECSAgentRunner):
    """
    ECS Agent Runner for STREAM execution mode — polls the Input Queue, runs the agent, and
    fans out each streamed chunk as its own message on the Output Queue.

    The ECS equivalent of ServerlessStreamAgentRunner. Each chunk is sent as a separate SQS
    message so ECSOutputConsumer can push them to the client one at a time as they arrive,
    instead of waiting for the full response like ECSAgentRunner. Subclasses ECSAgentRunner to
    reuse get_queue_url/_get_chat_service/_send_to_output_queue attribute plumbing; only
    endpoint_url validation and the chunk fan-out (process_message/on_permanent_failure) differ.

    Note: unlike Lambda's ESM (which supports partial-batch failure reporting), ECSSQSConsumer
    leaves the whole message in the queue for a full redelivery if process_message raises
    mid-stream — a pre-existing characteristic of ECSSQSConsumer, not specific to streaming.
    """

    _log = logging.getLogger("ak.ecs.streamagentrunner")

    @classmethod
    def _get_record_attributes(cls, raw_queue_message: dict) -> dict:
        """
        Same as ECSAgentRunner's, except endpoint_url is required — STREAM mode only makes
        sense pushed over a WebSocket.

        :param raw_queue_message: boto3 SQS message dict
        :return: Extracted attributes dict
        :raises ValueError: If request_id or endpoint_url is missing
        """
        attributes = super()._get_record_attributes(raw_queue_message)
        if not attributes.get("endpoint_url"):
            raise ValueError("endpoint_url is required in SQS message attributes for STREAM mode")
        return attributes

    @classmethod
    def _send_chunk_to_output_queue(cls, chunk_body: dict, record_attributes: dict, chunk_dedup_suffix: str) -> None:
        """
        Send a single stream chunk to the output SQS queue.

        :param chunk_body: StreamChunk payload (``dict``) to send
        :param record_attributes: Extracted attributes (``dict``) from the original record
        :param chunk_dedup_suffix: Suffix to make deduplication ID unique per chunk
        """
        dedup_id = record_attributes.get("message_deduplication_id")
        chunk_dedup_id = f"{dedup_id}-{chunk_dedup_suffix}" if dedup_id else None

        custom_attributes = [
            SQSHandler.CustomAttribute(name="endpoint_url", value=record_attributes["endpoint_url"], datatype=SQSHandler.AttributeDataType.STRING)
        ]

        SQSHandler.send_message_to_output_queue(
            message_body=chunk_body,
            attributes={
                "message_group_id": record_attributes["message_group_id"],
                "message_deduplication_id": chunk_dedup_id,
            },
            request_id=record_attributes["request_id"],
            user_id=record_attributes["user_id"],
            custom_message_attributes=custom_attributes,
        )

    @classmethod
    def process_message(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.process_message for STREAM mode."""
        message_id = record.get("MessageId")
        # Redelivery attempt marker: a mid-stream failure re-runs this method from chunk 0, and
        # without this, the retry's chunk-0..k dedup IDs would collide with the prior attempt's
        # (already sent within the 5-minute SQS FIFO dedup window) and get silently dropped —
        # stitching the first attempt's prefix to the retry's suffix with no error in between.
        receive_count = record.get("Attributes", {}).get("ApproximateReceiveCount", "1")
        cls._log.info(f"[STREAM AGENT START] Processing message {message_id} (receive_count={receive_count})")

        body = BaseRunRequest.model_validate(json.loads(record["Body"]))
        record_attributes = cls._get_record_attributes(raw_queue_message=record)

        chunk_count = 0
        for raw_chunk in cls._get_chat_service().process_stream_chat_sync(req=body):
            chunk_dict = json.loads(raw_chunk)
            cls._send_chunk_to_output_queue(
                chunk_body=chunk_dict,
                record_attributes=record_attributes,
                chunk_dedup_suffix=f"{receive_count}-{chunk_count}",
            )
            chunk_count += 1

        cls._log.info(
            f"[STREAM AGENT DONE] Streamed {chunk_count} chunks to output queue: "
            f"{SQSHandler.get_output_queue_url()}, request_id={record_attributes['request_id']}"
        )

    @classmethod
    def on_permanent_failure(cls, record: dict) -> None:
        """Implements ECSSQSConsumer.on_permanent_failure. Catches own exceptions."""
        cls._log.error(f"Permanent failure for message {record.get('MessageId')}")
        try:
            record_attributes = cls._get_record_attributes(raw_queue_message=record)
            receive_count = record.get("Attributes", {}).get("ApproximateReceiveCount", "1")
            error_chunk = StreamChunk(
                error=f"Failed to process message after {cls._config.execution.queues.input.max_receive_count} retries",
                done=True,
            )
            error_chunk_body = error_chunk.model_dump(exclude_none=True)
            error_chunk_body["session_id"] = record_attributes["message_group_id"]
            cls._send_chunk_to_output_queue(
                chunk_body=error_chunk_body,
                record_attributes=record_attributes,
                chunk_dedup_suffix=f"{receive_count}-error",
            )
        except Exception:
            cls._log.exception("Failed to send permanent-failure stream chunk to output queue")
