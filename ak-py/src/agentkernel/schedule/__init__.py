"""Scheduling capability: deferred and recurring chat execution.

A chat request carrying a ``schedule`` block is not run — it is registered as a scheduled task
and acknowledged with HTTP 202. When an occurrence is due, the configured provider delivers a
plain chat request (the frozen trigger body) into the input queue, where the normal execution
path picks it up. The capability is enabled by a ``schedule`` block in config.yaml.

This module is the capability's public surface. The provider/store factories, the trigger bodies
and the agent tools stay internal, reached through ``ScheduleManager``.
"""

from ..core.model import ScheduleSpec
from . import errors
from .errors import ScheduleError
from .manager import ScheduleManager
from .model import ScheduledTask, ScheduledTaskPage, ScheduleStatus
from .provider.base import ScheduleProvider
from .store.base import ScheduleStore

__all__ = [
    "errors",
    "ScheduleError",
    "ScheduleManager",
    "ScheduleProvider",
    "ScheduleSpec",
    "ScheduleStore",
    "ScheduleStatus",
    "ScheduledTask",
    "ScheduledTaskPage",
]
