import logging
from typing import Optional

from ...core.util.async_bridge import run_async_sync
from ...core.util.factory import AKConfigError
from ...pipeline.thread_runner import ThreadRunner
from ...pipeline.transport.base import QueueTransportFactory
from .base import PollingInboundAdapter, Source
from .producer import IntegrationProducer


class PollerRunner:
    """Hosts a polling :class:`PollingInboundAdapter` (spec #524 §7).

    The pull-based sibling of the webhook host, and the mirror of ``AgentRunner`` as a pipeline
    entry point: ``run()`` is the container main, ``start()`` runs the loop on an
    already-constructed instance.

    It is its own container rather than a thread inside the webhook tier because the two scale
    on unrelated signals: the webhook tier grows with inbound HTTP load, while a poller does no
    HTTP serving at all, so riding that tier's replica count would multiply the poll rate for
    no reason. Run it at one replica.
    """

    _log = logging.getLogger("ak.integration.poller_runner")

    def __init__(self, adapter: PollingInboundAdapter, producer: Optional[IntegrationProducer] = None):
        """
        :param adapter: The polling adapter to host.
        :param producer: Input-queue producer; defaults to the configured transport.
        :raises ValueError: If the adapter is not a polling adapter.
        """
        if adapter.source is not Source.POLLER:
            raise ValueError(f"{type(adapter).__name__} is a {adapter.source} adapter: host it with WebhookRESTRequestHandler, not PollerRunner")
        self._adapter = adapter
        self._producer = producer or IntegrationProducer()

    @property
    def adapter(self) -> PollingInboundAdapter:
        """The hosted adapter (IOHandler names its thread after it)."""
        return self._adapter

    def poll_once(self) -> int:
        """Run one poll iteration: fetch, parse and enqueue.

        Exceptions are contained here so a transient platform failure costs one interval rather
        than the poller process.

        :return: How many requests were enqueued.
        """
        enqueued = 0
        try:
            for raw in run_async_sync(self._adapter.poll()):
                result = run_async_sync(self._adapter.parse(raw))
                for inbound in result.requests:
                    self._producer.enqueue(self._adapter.name, inbound)
                    enqueued += 1
                # Only after a successful enqueue: a crash mid-iteration must leave the event to
                # be picked up again rather than dropping it.
                self._adapter.mark_handled(raw)
        except Exception:
            self._log.exception(f"Poll iteration failed: integration={self._adapter.name}")
        return enqueued

    def start(self, exit_on_shutdown: bool = True) -> None:
        """Run the blocking poll loop (the container main loop).

        :param exit_on_shutdown: True for a standalone container main (drain then exit the
            process); IOHandler passes False so its outer runner coordinates the exit.
        """
        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=self._loop,
                    thread_name=f"poller-{self._adapter.name}",
                    stop_all_on_failure=True,
                    graceful=True,
                )
            ],
            max_workers=1,
            exit_on_shutdown=exit_on_shutdown,
        )

    def _loop(self) -> None:
        self._log.info(f"Polling started: integration={self._adapter.name}, interval={self._adapter.poll_interval}s")
        while not ThreadRunner.shutdown_event.is_set():
            self.poll_once()
            # Waiting on the shutdown event rather than sleeping keeps a drain prompt: a 30 s
            # interval would otherwise hold the process open for up to 30 s after SIGTERM.
            ThreadRunner.shutdown_event.wait(self._adapter.poll_interval)
        self._log.info(f"Polling stopped: integration={self._adapter.name}")

    @classmethod
    def run(cls, adapter: PollingInboundAdapter) -> None:
        """Container entry point for the poller tier.

        :param adapter: The polling adapter to host.
        :raises AKConfigError: On the in_memory transport, which has no cross-process queue.
        """
        if QueueTransportFactory.resolve_type() == "in_memory":
            raise AKConfigError(
                "the in_memory transport runs in-process: start IOHandler(pollers=[...]) " "(single-process topology) instead of PollerRunner"
            )
        ThreadRunner.install_shutdown_signal_handlers(cls._log)
        cls(adapter).start()
