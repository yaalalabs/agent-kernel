from __future__ import annotations

import logging
import time
from typing import Callable

import boto3

_log = logging.getLogger("ak.ecs.sqs_poller")


class SQSPoller:
    """
    Polls an SQS queue in a tight loop and delegates each message to a
    caller-supplied ``process_fn``.

    Intended to run as a background daemon thread (Thread 2 in the ECS
    REST-Service, or the main loop in the Agent Runner service).

    On success the message is deleted from the queue.
    On failure the message is left in the queue so that the visibility
    timeout returns it for a retry — exactly mirroring the Lambda ESM
    behaviour.

    :param queue_url: SQS queue URL to poll.
    :param process_fn: Callable that receives a single raw boto3 SQS
        message dict (same shape as a Lambda ``Records`` entry).
    :param max_receive_count: Messages received more than this many times
        are passed to ``on_permanent_failure_fn`` instead of
        ``process_fn`` and then deleted.
    :param on_permanent_failure_fn: Optional callback for permanently
        failed messages. Receives the raw message dict.
    :param wait_seconds: Long-poll duration (0–20 s). Defaults to 20.
    :param batch_size: Number of messages to fetch per poll (1–10).
    """

    def __init__(
        self,
        queue_url: str,
        process_fn: Callable[[dict], None],
        max_receive_count: int = 3,
        on_permanent_failure_fn: Callable[[dict], None] | None = None,
        wait_seconds: int = 20,
        batch_size: int = 10,
    ) -> None:
        self._queue_url = queue_url
        self._process_fn = process_fn
        self._max_receive_count = max_receive_count
        self._on_permanent_failure_fn = on_permanent_failure_fn
        self._wait_seconds = wait_seconds
        self._batch_size = batch_size
        self._client: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block forever, polling the queue. Call from a dedicated thread."""
        _log.info(f"SQSPoller starting — queue: {self._queue_url}")
        client = self._get_client()
        while True:
            try:
                self._poll_once(client)
            except Exception:
                _log.exception("Unexpected error in poll loop, sleeping 5 s before retry")
                time.sleep(5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client("sqs")
        return self._client

    def _poll_once(self, client) -> None:
        resp = client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._batch_size,
            WaitTimeSeconds=self._wait_seconds,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        for msg in resp.get("Messages", []):
            self._handle_message(client, msg)

    def _handle_message(self, client, msg: dict) -> None:
        message_id = msg.get("MessageId", "<unknown>")
        receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))

        try:
            if receive_count > self._max_receive_count:
                _log.warning(f"Message {message_id} exceeded max receive count " f"({receive_count} > {self._max_receive_count})")
                if self._on_permanent_failure_fn:
                    self._on_permanent_failure_fn(msg)
                # Delete so it stops cycling
                self._delete_message(client, msg)
                return

            self._process_fn(msg)
            self._delete_message(client, msg)

        except Exception:
            _log.exception(f"Failed to process message {message_id} — " "leaving in queue for visibility-timeout retry")
            # Do NOT delete — visibility timeout will return it for retry

    def _delete_message(self, client, msg: dict) -> None:
        client.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=msg["ReceiptHandle"],
        )
