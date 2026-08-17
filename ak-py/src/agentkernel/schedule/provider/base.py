"""Abstract trigger provider and factory for the scheduling capability.

A provider owns the timers: it registers a task's occurrence rule with whatever fires it, and at
fire time delivers the frozen trigger body into the input queue. It owns nothing else — the task
record, its validation, and its ownership rules belong to the manager.
"""

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Optional

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, resolve_dotted
from ..model import ScheduledTask

# Providers shipped with the capability; anything else is treated as a dotted path (BYO).
_BUILTIN_SCHEDULE_PROVIDERS = ["local"]


class ScheduleProvider(ABC):
    """Backend that fires a task's occurrences into the input queue.

    ``body_template`` is the trigger body the manager froze for the task: a JSON document
    carrying the occurrence placeholders (``TOKEN_REQUEST_ID``, ``TOKEN_OCCURRENCE_TIME``).
    Substituting them is the provider's job, because only the provider knows what its backend
    can offer for them.
    """

    # Queue transports this provider can deliver to; None means transport-agnostic. The manager
    # fails fast at construction when the configured transport is not in the set, so an
    # undeliverable pairing surfaces at startup instead of at the first occurrence.
    supported_transports: ClassVar[Optional[frozenset[str]]] = None

    @abstractmethod
    def create(self, task: ScheduledTask, body_template: str) -> str:
        """Register a task's occurrence rule.

        :param task: The task to arm, carrying the spec, the status and the group it delivers under.
        :param body_template: The frozen trigger body, with occurrence placeholders unsubstituted.
        :return: The provider reference the task was registered under, stored on the record.
        :raises ScheduleError: If the backend rejected the registration.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, task: ScheduledTask, body_template: str) -> None:
        """Re-register an amended task, replacing its rule, its body and its enabled state.

        :param task: The amended task.
        :param body_template: The re-frozen trigger body.
        :raises ScheduleError: If the backend rejected the amendment.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, provider_ref: str) -> None:
        """Deregister a task. Idempotent: an already-gone registration is not an error.

        :param provider_ref: The reference returned by :meth:`create`.
        :raises ScheduleError: If the backend rejected the deletion for any other reason.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, provider_ref: str) -> Optional[dict]:
        """Return the backend's own view of a registration, for diagnostics.

        :param provider_ref: The reference returned by :meth:`create`.
        :return: Native details, or None when the registration no longer exists.
        """
        raise NotImplementedError

    @staticmethod
    def message_group_id(task: ScheduledTask) -> str:
        """Return the FIFO ordering group a task's triggers are delivered under.

        A reused session groups by that session, so an occurrence orders against the session's
        live traffic instead of racing it. A per-occurrence session has no such traffic, so
        occurrences group by the task and order against each other.

        :param task: The task whose triggers are being delivered.
        :return: The message group id.
        """
        return task.session_id if task.spec.session_mode == "reuse" else task.task_id


class ScheduleProviderFactory:
    """Creates the ``ScheduleProvider`` named by ``schedule.provider.type``."""

    _log = logging.getLogger("ak.schedule.provider.factory")

    @staticmethod
    def create() -> ScheduleProvider:
        """Create the configured provider, resolving its dependencies from config once.

        ``type`` is a built-in short name or a dotted path to a user-supplied
        ``ScheduleProvider`` subclass (bring-your-own). An unknown, non-dotted value raises
        ``AKConfigError``.

        :return: The configured provider.
        :raises ValueError: If the scheduling capability is not configured.
        :raises AKConfigError: If the configured type is neither a built-in nor a resolvable dotted path.
        """
        schedule_config = AKConfig.get().schedule
        if schedule_config is None:
            raise ValueError("Scheduling is not configured — add a 'schedule' block to config.yaml")

        provider_type = schedule_config.provider.type
        ScheduleProviderFactory._log.info(f"Building '{provider_type}' schedule provider")
        if provider_type.lower() == "local":
            from ...pipeline.transport.base import QueueTransportFactory
            from .local import LocalScheduleProvider

            # The transport is resolved here, not inside the provider: a provider must not read
            # AKConfig in its methods.
            return LocalScheduleProvider(transport=QueueTransportFactory.create())
        if "." not in provider_type:
            raise AKConfigError(
                f"unknown schedule provider type '{provider_type}'; expected one of {_BUILTIN_SCHEDULE_PROVIDERS} "
                "or a dotted path to a ScheduleProvider subclass"
            )
        return resolve_dotted(provider_type, base=ScheduleProvider)()
