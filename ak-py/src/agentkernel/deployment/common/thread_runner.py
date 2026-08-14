"""Moved to :mod:`agentkernel.pipeline.thread_runner` (#495). This import path is preserved for backwards compatibility."""

# Kept so existing patch targets like "agentkernel.deployment.common.thread_runner.os._exit"
# still resolve: os is a single module object shared with the relocated implementation.
import os  # noqa: F401

from ...pipeline.thread_runner import ThreadRunner

__all__ = ["ThreadRunner"]
