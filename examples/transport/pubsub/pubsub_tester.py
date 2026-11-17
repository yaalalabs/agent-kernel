"""A lightweight Pub/Sub emulator harness for this example: bring the stack up, look at the topics,
inject messages, and measure delivery latency.

Command line:

    python pubsub_tester.py up                         # compose up, wait for the emulator to answer
    python pubsub_tester.py topics                     # topics, their subscriptions, ordering, DLQ policy
    python pubsub_tester.py tail agent-input-dlq       # print what a subscription holds (peek, no ack)
    python pubsub_tester.py publish --session s1 --data '{"prompt":"hi"}'
    python pubsub_tester.py provision                  # create the topics/subscriptions explicitly
    python pubsub_tester.py purge                      # drain every subscription
    python pubsub_tester.py latency --messages 200     # delivery latency to idle consumers
    python pubsub_tester.py down                       # compose down, removing all state

It is also importable: ``app_test.py`` uses :class:`PubSubTester` to run the same steps.
"""

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Set before the client libraries are imported anywhere: they read it when a client is built.
os.environ.setdefault("PUBSUB_EMULATOR_HOST", "localhost:8085")

from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.transport.bookkeeping import InMemoryBookkeepingStore
from agentkernel.pipeline.transport.pubsub import PubSubEnvelopeCodec, PubSubTransport
from google.api_core import exceptions as google_exceptions
from google.cloud import pubsub_v1

PROJECT = "ak-local"
EMULATOR_URL = f"http://{os.environ['PUBSUB_EMULATOR_HOST']}"
INPUT_TOPIC = "agent-input"
OUTPUT_TOPIC = "agent-output"
DLQ_SUFFIX = "-dlq"
TOPICS = [INPUT_TOPIC, OUTPUT_TOPIC, f"{INPUT_TOPIC}{DLQ_SUFFIX}", f"{OUTPUT_TOPIC}{DLQ_SUFFIX}"]

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yaml"


def _transport() -> PubSubTransport:
    """The transport the example itself is configured with, built from config.yaml by the factory."""
    from agentkernel.pipeline.transport.base import QueueTransportFactory

    return QueueTransportFactory.create()


class PubSubTester:
    """Owns the local stack's lifecycle and the inspection commands."""

    def __init__(self, project: str = PROJECT):
        self.project = project
        self._request_timeout = 10.0

    # -- infrastructure ------------------------------------------------------------------

    def compose(self, *args: str) -> None:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True)

    def up(self) -> None:
        """Start the stack and wait until the emulator answers."""
        self.compose("up", "-d")
        self.wait_for_emulator()

    def down(self) -> None:
        """Stop the stack and delete its volumes: nothing survives to confuse the next run."""
        self.compose("down", "-v")

    def wait_for_emulator(self, timeout: float = 120.0) -> None:
        """Block until the emulator answers on its root path (it replies "Ok" once ready)."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(EMULATOR_URL, timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError) as e:
                last_error = e
            time.sleep(1)
        raise TimeoutError(f"the Pub/Sub emulator at {EMULATOR_URL} was not ready within {timeout} s: {last_error}")

    # -- topics --------------------------------------------------------------------------

    def provision(self) -> None:
        """Create the topics, dead-letter topics and subscriptions explicitly.

        The example runs with ``auto_provision: true``, so this is not needed for the happy path.
        It rehearses the production posture: provision with this, set ``auto_provision: false`` in
        config.yaml, and the pipeline verifies the objects at startup instead of creating them.
        """
        transport = _transport()
        transport._auto_provision = True
        for queue in (QueueName.INPUT, QueueName.OUTPUT):
            transport._ensure_topic(queue)
            transport._ensure_subscription(queue)
        print(f"provisioned {', '.join(TOPICS)} and their subscriptions")

    def describe(self) -> dict[str, dict[str, Any]]:
        """Each topic and its subscriptions, with ordering and dead-letter settings."""
        publisher = pubsub_v1.PublisherClient()
        described: dict[str, dict[str, Any]] = {}
        with pubsub_v1.SubscriberClient() as subscriber:
            for name in TOPICS:
                topic = f"projects/{self.project}/topics/{name}"
                try:
                    publisher.get_topic(request={"topic": topic}, timeout=self._request_timeout)
                except google_exceptions.NotFound:
                    described[name] = {"exists": False, "subscriptions": {}}
                    continue
                subscriptions = {}
                for path in publisher.list_topic_subscriptions(request={"topic": topic}, timeout=self._request_timeout):
                    details = subscriber.get_subscription(request={"subscription": path}, timeout=self._request_timeout)
                    policy = details.dead_letter_policy
                    subscriptions[path.rsplit("/", 1)[-1]] = {
                        "ordering": details.enable_message_ordering,
                        "ack_deadline_seconds": details.ack_deadline_seconds,
                        "dead_letter_topic": (
                            policy.dead_letter_topic.rsplit("/", 1)[-1] if policy.dead_letter_topic else None
                        ),
                        "max_delivery_attempts": policy.max_delivery_attempts or None,
                    }
                described[name] = {"exists": True, "subscriptions": subscriptions}
        return described

    def purge(self) -> None:
        """Pull and acknowledge everything on every subscription. Stop the pipeline first."""
        with pubsub_v1.SubscriberClient() as subscriber:
            for name in TOPICS:
                subscription = f"projects/{self.project}/subscriptions/{name}"
                drained = 0
                while True:
                    try:
                        response = subscriber.pull(
                            request={"subscription": subscription, "max_messages": 100}, timeout=2.0, retry=None
                        )
                    except (google_exceptions.DeadlineExceeded, google_exceptions.NotFound):
                        break
                    if not response.received_messages:
                        break
                    ack_ids = [message.ack_id for message in response.received_messages]
                    subscriber.acknowledge(request={"subscription": subscription, "ack_ids": ack_ids})
                    drained += len(ack_ids)
                print(f"purged {drained} message(s) from {name}")

    # -- messages ------------------------------------------------------------------------

    def tail(self, subscription: str, limit: int = 50, wait: float = 2.0) -> list[dict]:
        """Peek at what a subscription holds: pull, then release at once without acknowledging.

        Meant for the dead-letter subscriptions, which nothing consumes. Peeking at a pipeline
        subscription works too, but briefly holds messages away from the running consumers.
        """
        path = f"projects/{self.project}/subscriptions/{subscription}"
        with pubsub_v1.SubscriberClient() as subscriber:
            try:
                response = subscriber.pull(
                    request={"subscription": path, "max_messages": limit}, timeout=wait, retry=None
                )
            except (google_exceptions.DeadlineExceeded, google_exceptions.NotFound):
                return []
            received = list(response.received_messages)
            if received:
                subscriber.modify_ack_deadline(
                    request={
                        "subscription": path,
                        "ack_ids": [message.ack_id for message in received],
                        "ack_deadline_seconds": 0,
                    }
                )
        return [self._describe_message(message.message) for message in received]

    def publish(
        self, session: str, data: str, attributes: dict[str, str] | None = None, queue: QueueName = QueueName.INPUT
    ) -> str:
        """Send a message onto a queue through the transport, exactly as the pipeline would.

        This is how to feed the runner something it cannot process.
        """
        result = _transport().send(queue, QueueMessage(body=data, group_id=session, attributes=attributes or {}))
        return result["MessageId"]

    def latency(
        self, messages: int = 200, consumers: int = 2, max_gap: float = 1.5, sessions: int = 8
    ) -> dict[str, float]:
        """Delivery latency to idle consumers that poll the way the pipeline does.

        Each consumer thread fetches with the 1 s wait the pipeline's consumer loop uses, so idle
        consumers cancel one pull per second. Messages are sent at random gaps, so they reach the
        server at every point of that cycle. A message the server hands to a pull just as it is
        cancelled comes back only when the subscription's ack deadline (10 s) passes: this
        measures how often that happens. Uses its own topic, so it never touches the pipeline.
        """
        name = f"latency-{uuid.uuid4().hex[:8]}"
        transport = PubSubTransport(
            project_id=self.project,
            input_topic=name,
            input_subscription=name,
            output_topic=f"{name}-out",
            output_subscription=f"{name}-out",
            auto_provision=True,
            bookkeeping=InMemoryBookkeepingStore(),
        )
        workers = [transport.create_consumer(QueueName.INPUT) for _ in range(consumers)]
        delays: list[float] = []
        lock = threading.Lock()
        stop = threading.Event()

        def consume(consumer) -> None:
            while not stop.is_set():
                for message in consumer.fetch(10, 1.0):
                    with lock:
                        delays.append(time.monotonic() - json.loads(message.body)["sent"])
                    consumer.ack(message)

        threads = [threading.Thread(target=consume, args=(worker,), daemon=True) for worker in workers]
        for thread in threads:
            thread.start()
        time.sleep(2.0)  # let every consumer settle into its idle pull cycle

        for i in range(messages):
            time.sleep(random.uniform(0, max_gap))
            body = json.dumps({"sent": time.monotonic(), "i": i})
            transport.send(QueueName.INPUT, QueueMessage(body=body, group_id=f"s{i % sessions}"))

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and len(delays) < messages:
            time.sleep(0.5)
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
        for worker in workers:
            worker.close()

        ordered = sorted(delays)
        return {
            "sent": messages,
            "received": len(delays),
            "p50_s": statistics.median(ordered) if ordered else float("nan"),
            "p95_s": ordered[int(0.95 * (len(ordered) - 1))] if ordered else float("nan"),
            "max_s": ordered[-1] if ordered else float("nan"),
            "stalled_over_2s": sum(1 for delay in ordered if delay > 2.0),
        }

    @staticmethod
    def _describe_message(message: Any) -> dict:
        attributes = dict(message.attributes)
        described: dict[str, Any] = {
            "message_id": message.message_id,
            "ordering_key": message.ordering_key,
            "attributes": attributes,
        }
        try:
            envelope = PubSubEnvelopeCodec.decode(message.data, attributes, message.ordering_key, message.message_id)
            described["envelope"] = {
                "body": envelope.body,
                "attributes": envelope.attributes,
                "dedup_id": envelope.dedup_id,
            }
        except ValueError:
            described["data"] = bytes(message.data).decode(errors="replace")
        return described


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "down", "topics", "tail", "publish", "provision", "purge", "latency"])
    parser.add_argument("subscription", nargs="?", help="subscription name, for tail")
    parser.add_argument("--session", default="tester-session", help="session id (the ordering key)")
    parser.add_argument("--data", default="{}", help="message body to publish")
    parser.add_argument("--limit", type=int, default=50, help="messages to print when tailing")
    parser.add_argument("--messages", type=int, default=200, help="messages to send for latency")
    args = parser.parse_args(argv)

    tester = PubSubTester()

    if args.command == "up":
        tester.up()
        print(f"\nPub/Sub emulator on {EMULATOR_URL}, Valkey on localhost:6379. Next:\n")
        print("  python app.py runner      # in one terminal")
        print("  python app.py io          # in another")
        return 0

    if args.command == "down":
        tester.down()
        return 0

    if args.command == "provision":
        tester.provision()
        return 0

    if args.command == "purge":
        tester.purge()
        return 0

    if args.command == "topics":
        for name, details in tester.describe().items():
            if not details["exists"]:
                print(f"{name}: missing (start the pipeline with auto_provision, or run `provision`)")
                continue
            print(f"{name}:")
            for subscription, settings in details["subscriptions"].items():
                print(f"  {subscription}: {json.dumps(settings)}")
        return 0

    if args.command == "tail":
        if not args.subscription:
            parser.error("tail needs a subscription name")
        held = tester.tail(args.subscription, limit=args.limit)
        if not held:
            print(f"no messages held in {args.subscription}")
        for message in held:
            print(json.dumps(message, indent=2))
        return 0

    if args.command == "latency":
        print(json.dumps(tester.latency(messages=args.messages), indent=2))
        return 0

    message_id = tester.publish(args.session, args.data)
    print(f"published message {message_id} to {INPUT_TOPIC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
