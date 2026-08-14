"""Moved to :mod:`agentkernel.pipeline.ws.base` (#495). This import path is preserved for backwards compatibility."""

from ...pipeline.ws.base import WebSocketConnectionStoreABC, WebSocketHandlerABC

__all__ = ["WebSocketConnectionStoreABC", "WebSocketHandlerABC"]
