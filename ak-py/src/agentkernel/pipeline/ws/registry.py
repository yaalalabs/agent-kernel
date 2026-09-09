"""In-process WebSocket connection registry for the pipeline's pod-direct delivery (spec #495 §9).

The raw sockets are process-local: only the gateway pod that accepted a connection can write to
it. This registry holds those sockets (no TTL: connections die with the pod), while the shared
session-backed :class:`WSConnectionStore` holds the cluster-wide mapping of connections to pods. It is
shared by the ``/ws`` route (which registers connections), the gateway push endpoint (which
delivers frames pushed by Response Handlers), and the in-process short-circuit on the
``in_memory`` transport.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from .base import WebSocketConnectionStoreABC


class LocalConnectionRegistry(WebSocketConnectionStoreABC):
    """Thread-safe map of this pod's live WebSocket connections.

    Implements ``WebSocketConnectionStoreABC`` (with ``add_connection`` extended to carry the
    socket object and its event loop, which the ABC's cloud-backed stores have no use for) over
    two in-process dicts: ``user_id -> {connection_id: (websocket, loop)}`` and
    ``connection_id -> user_id``.

    ``deliver_to_connection`` is the write path for worker threads (the push endpoint's
    threadpool, the in-process short-circuit on the Response Handler's consumer threads): frames
    are written on the socket's own event loop via ``asyncio.run_coroutine_threadsafe``. Never
    call it from a coroutine running on that same loop: blocking on the future there would
    deadlock.
    """

    _log = logging.getLogger("ak.pipeline.ws.registry")

    _SEND_TIMEOUT_SECONDS = 10.0

    _instance: Optional["LocalConnectionRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._user_connections: Dict[str, Dict[str, Tuple[Any, Optional[asyncio.AbstractEventLoop]]]] = {}
        self._connection_users: Dict[str, str] = {}

    @classmethod
    def instance(cls) -> "LocalConnectionRegistry":
        """The process-wide registry every pipeline component shares."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance (tests)."""
        with cls._instance_lock:
            cls._instance = None

    # -- WebSocketConnectionStoreABC surface -----------------------------------------------

    def add_connection(
        self,
        user_id: str,
        connection_id: str,
        websocket: Any = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Register a connection, keeping the socket and the loop it must be written on."""
        with self._lock:
            self._user_connections.setdefault(user_id, {})[connection_id] = (websocket, loop)
            self._connection_users[connection_id] = user_id

    def get_connections(self, user_id: str) -> List[str]:
        with self._lock:
            return list(self._user_connections.get(user_id, {}))

    def get_user_id(self, connection_id: str) -> Optional[str]:
        with self._lock:
            return self._connection_users.get(connection_id)

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        with self._lock:
            connections = self._user_connections.get(user_id)
            if connections is not None:
                connections.pop(connection_id, None)
                if not connections:
                    del self._user_connections[user_id]
            self._connection_users.pop(connection_id, None)

    def delete_by_connection_id(self, connection_id: str) -> None:
        user_id = self.get_user_id(connection_id)
        if user_id is not None:
            self.delete_connection(user_id, connection_id)

    # -- delivery ---------------------------------------------------------------------------

    def socket(self, connection_id: str) -> Tuple[Any, Optional[asyncio.AbstractEventLoop]]:
        """The socket and loop registered for ``connection_id`` (``(None, None)`` when absent)."""
        with self._lock:
            user_id = self._connection_users.get(connection_id)
            if user_id is None:
                return None, None
            return self._user_connections.get(user_id, {}).get(connection_id, (None, None))

    def deliver_to_connection(self, connection_id: str, message: dict) -> bool:
        """Write one frame to one local connection from a worker thread.

        A connection whose send fails is dropped from the registry (the in-process analogue of
        the AWS handler cleaning up on ``GoneException``): a socket that cannot take a frame
        within the timeout is dead to the pipeline either way.

        :return: True when the frame reached the socket; False when the connection is unknown,
            unwritable, or dead (and now dropped).
        """
        websocket, loop = self.socket(connection_id)
        if websocket is None or loop is None or loop.is_closed():
            if websocket is not None or loop is not None:
                self._log.info(f"Dropping unwritable connection: connection_id={connection_id}")
                self.delete_by_connection_id(connection_id)
            return False
        try:
            asyncio.run_coroutine_threadsafe(websocket.send_json(message), loop).result(self._SEND_TIMEOUT_SECONDS)
            return True
        except Exception as e:
            self._log.info(f"Dropping stale connection: connection_id={connection_id} ({e})")
            self.delete_by_connection_id(connection_id)
            return False
