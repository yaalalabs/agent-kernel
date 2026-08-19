"""A lightweight NATS JetStream harness for this example: bring up a server, look inside the
streams, and inject messages.

The inspection commands exist because a work-queue stream cannot be browsed the way a Kafka topic
can. Consumers on a work-queue stream must have non-overlapping filter subjects, so attaching
another consumer to peek would either be rejected by the server or steal work from the running
pipeline. Everything here reads by sequence with a JetStream direct get instead, which delivers
nothing and disturbs no consumer.

Command line:

    python nats_tester.py up                     # compose up, wait for JetStream to answer
    python nats_tester.py streams                # streams, message counts, and their consumers
    python nats_tester.py tail AGENT_REPLIES     # print the messages a stream is holding
    python nats_tester.py publish --session s1 --data '{"prompt":"hi"}'
    python nats_tester.py provision              # create the streams/consumers explicitly
    python nats_tester.py purge                  # empty the streams, keeping their configuration
    python nats_tester.py down                   # compose down, removing all state

It is also importable: ``app_test.py`` uses :class:`NatsTester` to run the same steps.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.transport.nats import _NatsLoop

from nats.js.errors import NotFoundError

URL = "nats://localhost:4222"
INPUT_STREAM = "AGENT_REQUESTS"
OUTPUT_STREAM = "AGENT_REPLIES"
STREAMS = [INPUT_STREAM, OUTPUT_STREAM]

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yaml"


def _transport():
    """The transport the example itself is configured with.

    Built from config.yaml through the normal factory, so the tester partitions subjects with
    exactly the same hash the pipeline uses and cannot drift from it.
    """
    from agentkernel.pipeline.transport.base import QueueTransportFactory

    return QueueTransportFactory.create()


class NatsTester:
    """Owns the local server's lifecycle and the inspection commands."""

    def __init__(self, url: str = URL):
        self.url = url
        self._request_timeout = 10.0
        self._client: Optional[Any] = None

    # -- infrastructure ------------------------------------------------------------------

    def compose(self, *args: str) -> None:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True)

    def up(self) -> None:
        """Start the stack and wait until JetStream answers."""
        self.compose("up", "-d")
        self.wait_for_jetstream()

    def down(self) -> None:
        """Stop the stack and delete its volumes: nothing survives to confuse the next run."""
        self.close()  # release the connection before the server it points at disappears
        self.compose("down", "-v")

    def wait_for_jetstream(self, timeout: float = 90.0) -> None:
        """Block until JetStream is enabled and reachable.

        Waits on an actual JetStream account lookup rather than a TCP port or the container's
        health status, because the server accepts connections slightly before JetStream is ready.
        """
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                _NatsLoop.run(self._jetstream().account_info(), self._request_timeout)
                return
            except Exception as e:
                last_error = e
                time.sleep(1)
        raise TimeoutError(f"JetStream at {self.url} was not ready within {timeout} s: {last_error}")

    # -- streams -------------------------------------------------------------------------

    def provision(self) -> None:
        """Create the streams and partition consumers explicitly.

        The example runs with ``auto_provision: true``, so this is not needed for the happy path.
        It is here to rehearse the production posture: provision with this, set
        ``auto_provision: false`` in config.yaml, and the pipeline will verify the objects at
        startup instead of creating them (and fail loudly, naming the object, if any are missing).
        """
        transport = _transport()
        for queue in (QueueName.INPUT, QueueName.OUTPUT):
            transport._auto_provision = True
            transport._ensure_provisioned(queue)
        print(f"provisioned {', '.join(STREAMS)}")

    def describe(self) -> Dict[str, Dict[str, Any]]:
        """Message counts and consumer names per stream."""
        jetstream = self._jetstream()
        described: Dict[str, Dict[str, Any]] = {}
        for name in STREAMS:
            try:
                info = _NatsLoop.run(jetstream.stream_info(name), self._request_timeout)
            except NotFoundError:
                described[name] = {"exists": False}
                continue
            consumers = _NatsLoop.run(jetstream.consumers_info(name), self._request_timeout)
            described[name] = {
                "exists": True,
                "messages": info.state.messages,
                "first_seq": info.state.first_seq,
                "last_seq": info.state.last_seq,
                "consumers": len(consumers),
                "pending_per_consumer": {consumer.name: consumer.num_pending for consumer in consumers},
            }
        return described

    def purge(self) -> None:
        """Empty the streams but keep their configuration and consumers."""
        for name in STREAMS:
            try:
                _NatsLoop.run(self._jetstream().purge_stream(name), self._request_timeout)
                print(f"purged {name}")
            except NotFoundError:
                pass

    # -- messages ------------------------------------------------------------------------

    def tail(self, stream: str, limit: int = 50) -> List[dict]:
        """Read what a stream is holding, by sequence, without consuming anything.

        A direct get delivers nothing to any consumer, which is the only safe way to look inside a
        work-queue stream while the pipeline is running.
        """
        jetstream = self._jetstream()
        try:
            info = _NatsLoop.run(jetstream.stream_info(stream), self._request_timeout)
        except NotFoundError:
            return []

        messages: List[dict] = []
        sequence = info.state.first_seq
        while sequence <= info.state.last_seq and len(messages) < limit:
            try:
                raw = _NatsLoop.run(jetstream.get_msg(stream, seq=sequence), self._request_timeout)
                messages.append(
                    {
                        "seq": sequence,
                        "subject": raw.subject,
                        "headers": dict(raw.headers or {}),
                        "data": raw.data.decode() if raw.data else None,
                    }
                )
            except Exception:
                pass  # a gap: the message was acked and removed, which is normal on a work queue
            sequence += 1
        return messages

    def publish(
        self, session: str, data: str, headers: Optional[Dict[str, str]] = None, queue: QueueName = QueueName.INPUT
    ) -> str:
        """Publish a raw message onto a queue's partition subject.

        Uses the transport's own subject builder, so a message injected here lands exactly where
        the pipeline would have put it. This is how to feed the runner something it cannot process.
        """
        transport = _transport()
        subject = transport.subject_for(queue, session)
        combined = {"Ak-Group-Id": session, **(headers or {})}
        _NatsLoop.run(
            self._jetstream().publish(subject, data.encode(), headers=combined),
            self._request_timeout,
        )
        return subject

    # -- internals -----------------------------------------------------------------------

    def _jetstream(self) -> Any:
        """One connection for the life of the tester, reconnecting only when it has dropped.

        Reconnecting per call would leak a socket and its background tasks on every one: the
        readiness loop alone can call this dozens of times, and `tail` calls it once per invocation.
        """
        import nats

        if self._client is None or not self._client.is_connected:
            self._client = _NatsLoop.run(nats.connect(servers=[self.url]), self._request_timeout)
        return self._client.jetstream()

    def close(self) -> None:
        """Drop the connection. Safe to call more than once."""
        if self._client is not None:
            try:
                _NatsLoop.run(self._client.close(), self._request_timeout)
            except Exception:
                pass  # the server may already be gone, e.g. straight after `down`
            self._client = None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "down", "streams", "tail", "publish", "provision", "purge"])
    parser.add_argument("stream", nargs="?", help="stream name, for tail")
    parser.add_argument("--session", default="tester-session", help="session id (decides the partition subject)")
    parser.add_argument("--data", default="{}", help="message body to publish")
    parser.add_argument("--limit", type=int, default=50, help="messages to print when tailing")
    args = parser.parse_args(argv)

    tester = NatsTester()

    if args.command == "up":
        tester.up()
        print(f"\nNATS on {URL} (monitoring on http://localhost:8222), Valkey on localhost:6379. Next:\n")
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

    if args.command == "streams":
        for name, details in tester.describe().items():
            if not details["exists"]:
                print(f"{name}: missing (start the pipeline with auto_provision, or run `provision`)")
            else:
                print(
                    f"{name}: {details['messages']} message(s) held, {details['consumers']} partition consumer(s), "
                    f"seq {details['first_seq']}..{details['last_seq']}"
                )
        return 0

    if args.command == "tail":
        if not args.stream:
            parser.error("tail needs a stream name")
        held = tester.tail(args.stream, limit=args.limit)
        if not held:
            print(f"no messages held in {args.stream}")
        for message in held:
            print(json.dumps(message, indent=2))
        return 0

    subject = tester.publish(args.session, args.data)
    print(f"published 1 message to {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
