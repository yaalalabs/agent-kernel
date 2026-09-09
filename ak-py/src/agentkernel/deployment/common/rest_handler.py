"""Moved to :mod:`agentkernel.pipeline.request_handler` (#495). This import path is preserved for backwards compatibility."""

# Kept so existing patch targets like "…common.rest_handler.AKConfig.get" still resolve:
# AKConfig is a single class object shared with the relocated implementation.
from ...core.config import AKConfig  # noqa: F401
from ...pipeline.request_handler import RestHandler

__all__ = ["RestHandler"]
