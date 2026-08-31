"""Scheduling capability: deferred and recurring chat execution.

A chat request carrying a ``schedule`` block is not run — it is registered as a scheduled task
and acknowledged with HTTP 202. When an occurrence is due, the configured provider delivers a
plain chat request (the frozen trigger body) into the input queue, where the normal execution
path picks it up. The capability is enabled by a ``schedule`` block in config.yaml.

This module is the capability's public surface. The provider/store factories, the trigger bodies
and the agent tools stay internal, reached through ``ScheduleManager``.

``ScheduleRESTRequestHandler`` is exported lazily (the ``agentkernel.pipeline`` pattern): it is
the one module here that imports FastAPI, and the ChatService reaches this package by importing
``schedule.manager``, which would otherwise drag the API dependency into every runner process.
"""

import importlib
from typing import TYPE_CHECKING, Any

from ..core.model import ScheduleSpec
from . import errors
from .errors import ScheduleError
from .manager import ScheduleManager
from .model import ScheduledTask, ScheduledTaskPage, ScheduleStatus
from .provider.base import ScheduleProvider
from .store.base import ScheduleStore

_LAZY_EXPORTS = {
    "ScheduleAmendment": ".handler",
    "ScheduleRESTRequestHandler": ".handler",
}

__all__ = [
    "errors",
    "ScheduleAmendment",
    "ScheduleError",
    "ScheduleManager",
    "ScheduleProvider",
    "ScheduleRESTRequestHandler",
    "ScheduleSpec",
    "ScheduleStore",
    "ScheduleStatus",
    "ScheduledTask",
    "ScheduledTaskPage",
]

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .handler import ScheduleAmendment, ScheduleRESTRequestHandler


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
