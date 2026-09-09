"""A lightweight Kafka harness for this example: bring up a broker, provision topics, and look
inside them.

Agent Kernel never creates topics (a production cluster manages them through Strimzi or a
platform team), so something has to provision them before the pipeline can run. This module is
that something, plus the few inspection commands you actually want while developing against a
queue: what is in a topic, what landed in a dead-letter topic, and what happens to a record the
runner cannot process.

Command line:

    python kafka_tester.py up [--partitions 4]   # compose up, wait for the broker, create topics
    python kafka_tester.py topics                # partition counts and current end offsets
    python kafka_tester.py tail agent-output     # print records currently in a topic
    python kafka_tester.py produce agent-input --key s1 --value '{"prompt":"hi"}'
    python kafka_tester.py reset                 # delete and recreate the topics (clean slate)
    python kafka_tester.py down                  # compose down, removing all state

It is also importable: ``app_test.py`` uses :class:`KafkaTester` to run the same steps.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP_SERVERS = "localhost:9092"
INPUT_TOPIC = "agent-input"
OUTPUT_TOPIC = "agent-output"
DLQ_SUFFIX = ".dlq"
DEFAULT_PARTITIONS = 4

# Every topic the pipeline touches. The dead-letter topics matter as much as the queues: with
# auto-creation disabled, a permanently failed record can only be preserved if its DLQ exists.
TOPICS = [INPUT_TOPIC, OUTPUT_TOPIC, f"{INPUT_TOPIC}{DLQ_SUFFIX}", f"{OUTPUT_TOPIC}{DLQ_SUFFIX}"]

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yaml"


class KafkaTester:
    """Owns the local broker's lifecycle and the topics the pipeline expects."""

    def __init__(self, bootstrap_servers: str = BOOTSTRAP_SERVERS, partitions: int = DEFAULT_PARTITIONS):
        self.bootstrap_servers = bootstrap_servers
        self.partitions = partitions
        self._admin: Optional[AdminClient] = None

    # -- infrastructure ------------------------------------------------------------------

    def compose(self, *args: str) -> None:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True)

    def up(self) -> None:
        """Start the stack, wait for the broker to answer, and provision the topics."""
        self.compose("up", "-d", "--wait")
        self.wait_for_broker()
        self.ensure_topics()

    def down(self) -> None:
        """Stop the stack and delete its volumes: nothing survives to confuse the next run."""
        self.compose("down", "-v")

    def wait_for_broker(self, timeout: float = 90.0) -> None:
        """Block until the broker serves metadata, so callers never race a half-started Kafka."""
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                self.admin().list_topics(timeout=5)
                return
            except Exception as e:  # broker not accepting connections yet
                last_error = e
                time.sleep(1)
        raise TimeoutError(f"Kafka at {self.bootstrap_servers} was not ready within {timeout} s: {last_error}")

    def admin(self) -> AdminClient:
        if self._admin is None:
            self._admin = AdminClient({"bootstrap.servers": self.bootstrap_servers})
        return self._admin

    # -- topics --------------------------------------------------------------------------

    def ensure_topics(self, topics: Optional[List[str]] = None) -> None:
        """Create any missing topic. Existing topics are left exactly as they are."""
        wanted = topics or TOPICS
        existing = set(self.admin().list_topics(timeout=10).topics)
        missing = [name for name in wanted if name not in existing]
        if not missing:
            print(f"topics already provisioned: {', '.join(wanted)}")
            return

        new_topics = [NewTopic(name, num_partitions=self.partitions, replication_factor=1) for name in missing]
        for name, future in self.admin().create_topics(new_topics).items():
            future.result()  # raises if creation failed
            print(f"created topic {name} with {self.partitions} partition(s)")

    def delete_topics(self, topics: Optional[List[str]] = None) -> None:
        wanted = topics or TOPICS
        existing = [name for name in wanted if name in self.admin().list_topics(timeout=10).topics]
        if not existing:
            return
        for name, future in self.admin().delete_topics(existing, operation_timeout=30).items():
            future.result()
            print(f"deleted topic {name}")
        # Deletion is asynchronous inside the broker; recreating too soon can be rejected.
        time.sleep(2)

    def reset(self) -> None:
        """Delete and recreate the topics: the fastest way back to a known-empty pipeline."""
        self.delete_topics()
        self.ensure_topics()

    def describe(self) -> Dict[str, Dict[str, object]]:
        """Partition count and total records currently retained, per topic."""
        metadata = self.admin().list_topics(timeout=10)
        described: Dict[str, Dict[str, object]] = {}
        for name in TOPICS:
            topic_metadata = metadata.topics.get(name)
            if topic_metadata is None:
                described[name] = {"exists": False}
                continue
            described[name] = {
                "exists": True,
                "partitions": len(topic_metadata.partitions),
                "records": self._record_count(name, list(topic_metadata.partitions)),
            }
        return described

    def _record_count(self, topic: str, partitions: List[int]) -> int:
        """Sum of (high watermark - low watermark) across partitions: what a tail would print."""
        consumer = Consumer({"bootstrap.servers": self.bootstrap_servers, "group.id": f"tester-{uuid.uuid4()}"})
        try:
            total = 0
            for partition in partitions:
                low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=5)
                total += max(high - low, 0)
            return total
        finally:
            consumer.close()

    # -- records -------------------------------------------------------------------------

    def tail(self, topic: str, timeout: float = 5.0, limit: int = 50) -> List[dict]:
        """Read a topic from its start without joining the pipeline's consumer groups.

        Uses a throwaway group id and never commits, so inspecting a queue cannot steal work
        from, or shift the offsets of, the running pipeline.
        """
        consumer = Consumer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": f"tester-{uuid.uuid4()}",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        try:
            consumer.subscribe([topic])
            records: List[dict] = []
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and len(records) < limit:
                message = consumer.poll(0.5)
                if message is None or message.error() is not None:
                    continue
                records.append(
                    {
                        "partition": message.partition(),
                        "offset": message.offset(),
                        "key": message.key().decode() if message.key() else None,
                        "headers": {name: value.decode() for name, value in (message.headers() or [])},
                        "value": message.value().decode() if message.value() else None,
                    }
                )
            return records
        finally:
            consumer.close()

    def produce(
        self, topic: str, value: str, key: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> None:
        """Put a record on a topic directly: how to feed the runner a message it cannot process."""
        producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        producer.produce(
            topic=topic,
            value=value.encode(),
            key=key.encode() if key else None,
            headers=[(name, str(header_value).encode()) for name, header_value in (headers or {}).items()],
        )
        producer.flush(10)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "down", "topics", "tail", "produce", "reset"])
    parser.add_argument("topic", nargs="?", help="topic name, for tail and produce")
    parser.add_argument("--partitions", type=int, default=DEFAULT_PARTITIONS, help="partitions for created topics")
    parser.add_argument("--key", help="record key (the pipeline uses the session id)")
    parser.add_argument("--value", default="{}", help="record value")
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds to read for, when tailing")
    args = parser.parse_args(argv)

    tester = KafkaTester(partitions=args.partitions)

    if args.command == "up":
        tester.up()
        print(f"\nKafka on {BOOTSTRAP_SERVERS}, Valkey on localhost:6379. Next:\n")
        print("  python app.py runner      # in one terminal")
        print("  python app.py io          # in another")
        return 0

    if args.command == "down":
        tester.down()
        return 0

    if args.command == "reset":
        tester.reset()
        return 0

    if args.command == "topics":
        for name, details in tester.describe().items():
            if not details["exists"]:
                print(f"{name}: missing (run `python kafka_tester.py up`)")
            else:
                print(f"{name}: {details['partitions']} partition(s), {details['records']} record(s) retained")
        return 0

    if not args.topic:
        parser.error(f"{args.command} needs a topic name")

    if args.command == "tail":
        records = tester.tail(args.topic, timeout=args.timeout)
        if not records:
            print(f"no records in {args.topic}")
        for record in records:
            print(json.dumps(record, indent=2))
        return 0

    tester.produce(args.topic, value=args.value, key=args.key)
    print(f"produced 1 record to {args.topic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
