"""Gateway push: how a Response Handler reaches a client's WebSocket (spec #495 §9).

The shared :class:`WSConnectionStore` (provided by the configured session store, spec §9) says
which gateway pod holds each of the user's sockets *right now*; this module delivers one frame
per connection to the owning pod's
authenticated push endpoint: the ``PostToConnection`` analogue. On the ``in_memory`` transport
everything is one process, so the recorded endpoint is the sentinel ``local`` and delivery
short-circuits through the pod-local registry, no HTTP hop.
"""

import logging
import os
import socket
import threading
from typing import Any, Dict, List, Optional

from ...core.builder import SessionStoreBuilder
from ...core.config import AKConfig
from ...core.session.base import WSConnectionStore
from ...core.util.factory import AKConfigError
from ..transport.base import QueueTransportFactory
from .base import WebSocketHandlerABC
from .registry import LocalConnectionRegistry

# Endpoint sentinel for in-process delivery (single-process topology).
LOCAL_ENDPOINT = "local"

# The gateway push endpoint's path and auth header (see ws/endpoint.py).
PUSH_PATH = "/internal/push"
PUSH_TOKEN_HEADER = "x-ak-push-token"

_log = logging.getLogger("ak.pipeline.ws.push")

# One pooled HTTP client per process: pushes are small, frequent, and pod-to-pod, so
# connection reuse matters and per-send clients would leak sockets.
_client_lock = threading.Lock()
_client: Optional[Any] = None

_REQUEST_TIMEOUT_SECONDS = 10.0


def _pooled_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            import httpx  # lazy: an optional dependency (the 'api' extra), needed only for pod-to-pod pushes

            _client = httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)
        return _client


def pod_endpoint_url() -> str:
    """This gateway pod's push endpoint URL, recorded in the connection store at connect time.

    ``local`` on the in_memory transport (in-process delivery, no HTTP). Otherwise
    ``http://{pod_ip}:{port}`` where the pod IP comes from env ``AK_POD_IP`` (chart-injected via
    the downward API), falling back to the host's resolved address, then to loopback; the port is
    ``websocket_api.push_port`` when set, else ``api.port``.
    """
    if QueueTransportFactory.resolve_type() == "in_memory":
        return LOCAL_ENDPOINT
    config = AKConfig.get()
    pod_ip = os.environ.get("AK_POD_IP") or _self_ip()
    port = config.websocket_api.push_port or config.api.port
    return f"http://{pod_ip}:{port}"


def _self_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def default_connection_store() -> WSConnectionStore:
    """The configured connection store: the session backend provides it (spec §9).

    :raises AKConfigError: On session backends without a connection store implementation.
    """
    return SessionStoreBuilder.build().get_connection_store()


class PodPushWebSocketHandler(WebSocketHandlerABC):
    """``WebSocketHandlerABC`` whose transport is the gateway pods' push endpoints.

    ``broadcast(user_id=...)`` resolves the user's current connections from the session
    backend's shared connection store and delivers per connection to whichever gateway pod
    holds each socket:
    AWS semantics (all of a user's connections, wherever they are). A push that finds the socket
    gone (404) deletes the stale mapping and moves on, the ``GoneException`` parity; reaching no
    connection at all raises, so the ``ConsumerLoop`` retry/permanent-failure semantics apply:
    bounded retries, then the error is surfaced, never a crash loop.
    """

    def __init__(self, connection_store: Optional[WSConnectionStore] = None, registry: Optional[LocalConnectionRegistry] = None):
        """
        :param connection_store: The shared connection store (defaults to the session backend's).
        :param registry: The pod-local socket registry, used only for ``local``-endpoint delivery.
        """
        self._store = connection_store if connection_store is not None else default_connection_store()
        super().__init__(connection_store=self._store)
        self._registry = registry or LocalConnectionRegistry.instance()
        self._config = AKConfig.get()
        self._log = logging.getLogger("ak.pipeline.ws.push")

    def get_client(self, endpoint_url: str) -> Any:
        return _pooled_client()

    def construct_endpoint_url(self, *args: Any, **kwargs: Any) -> str:
        return pod_endpoint_url()

    def broadcast(
        self,
        endpoint_url: Optional[str] = None,
        message: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        connection_ids: Optional[List[str]] = None,
        message_type: Optional[WebSocketHandlerABC.MessageType] = None,
    ) -> None:
        """Deliver one frame to the user's current connections (or to explicit connection ids).

        ``endpoint_url`` is accepted for ABC-signature compatibility and ignored: each
        connection's endpoint comes from the connection store.

        :raises LookupError: When the frame reached no connection at all (none registered, all
            stale): the caller's retry semantics take over.
        """
        message = message or {}
        if not user_id and not connection_ids:
            raise ValueError("Provide either user_id or connection_ids")
        if message_type is not None:
            message = {**message, "type": message_type.value}

        if user_id:
            endpoints = self._store.get_endpoints(user_id)
        else:
            endpoints = {connection_id: self._store.get_endpoint(connection_id) for connection_id in connection_ids}
        if not endpoints:
            raise LookupError(f"no WebSocket connections registered for user '{user_id}'")

        delivered = 0
        for connection_id, endpoint in endpoints.items():
            if endpoint is None:
                continue
            try:
                self.send(endpoint_url=endpoint, connection_id=connection_id, message=message)
                delivered += 1
            except LookupError:
                # The owning pod says the socket is gone (client disconnected, pod restarted):
                # clean the stale mapping and keep delivering to the rest (GoneException parity).
                self._log.info(f"Cleaning stale connection mapping: connection_id={connection_id}")
                self._store.delete_by_connection_id(connection_id)
            except AKConfigError:
                raise  # a misconfiguration (missing push token), not a delivery failure
            except Exception as e:
                # Transient transport failure (pod unreachable, timeout): keep the mapping,
                # count the connection as missed; the message-level retry covers it.
                self._log.warning(f"Push to {endpoint} failed for connection_id={connection_id}: {e}")

        if delivered == 0:
            raise LookupError(f"no reachable WebSocket connections for user '{user_id or connection_ids}'")

    def send(self, endpoint_url: str, connection_id: str, message: dict) -> None:
        """Deliver one frame to one connection on the gateway pod that owns it.

        :raises LookupError: The socket is not there (the ``GoneException`` analogue).
        """
        if endpoint_url == LOCAL_ENDPOINT:
            if not self._registry.deliver_to_connection(connection_id, message):
                raise LookupError(f"connection '{connection_id}' has no local socket")
            return

        token = self._config.websocket_api.push_auth_token
        if not token:
            raise AKConfigError("pushing WebSocket deliveries to a gateway pod requires websocket_api.push_auth_token")

        response = self.get_client(endpoint_url).post(
            f"{endpoint_url}{PUSH_PATH}",
            json={"connection_id": connection_id, "message": message},
            headers={PUSH_TOKEN_HEADER: token},
        )
        if response.status_code == 404:
            raise LookupError(f"connection '{connection_id}' is gone from {endpoint_url}")
        response.raise_for_status()
