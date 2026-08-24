"""Abstract trigger provider and factory for the scheduling capability.

A provider owns the timers: it registers a task's occurrence rule with whatever fires it, and at
fire time delivers the frozen trigger body into the input queue. It owns nothing else — the task
record, its validation, and its ownership rules belong to the manager.
"""

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Optional

from ...core.config import AKConfig, _ScheduleProviderConfig
from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ..model import ScheduledTask

# Providers shipped with the capability; anything else is treated as a dotted path (BYO).
_BUILTIN_SCHEDULE_PROVIDERS = ["local", "eventbridge"]


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

    @classmethod
    def from_config(cls, provider_config: _ScheduleProviderConfig) -> "ScheduleProvider":
        """Build the provider from the ``schedule.provider`` block.

        The single construction seam the factory uses for every provider. A provider that needs
        settings or a collaborator resolves them here, once, which is what keeps ``create``,
        ``update``, ``delete`` and ``get`` free of configuration reads. The default needs neither
        and ignores the block, so a bring-your-own provider is constructed by it unchanged.

        :param provider_config: The ``schedule.provider`` block, including every provider's own
                                settings sub-block.
        :return: The configured provider.
        :raises AKConfigError: If the provider's own settings are missing or incomplete.
        """
        return cls()

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
        """Create the configured provider, delegating to its ``from_config`` seam.

        ``type`` is a built-in short name (local, eventbridge) or a dotted path to a user-supplied
        ``ScheduleProvider`` subclass (bring-your-own). An unknown, non-dotted value raises
        ``AKConfigError``.

        :return: The configured provider.
        :raises ValueError: If the scheduling capability is not configured.
        :raises AKConfigError: If the configured type is neither a built-in nor a resolvable dotted
                               path, or if a built-in's own configuration is incomplete.
        """
        schedule_config = AKConfig.get().schedule
        if schedule_config is None:
            raise ValueError("Scheduling is not configured — add a 'schedule' block to config.yaml")

        provider_type = schedule_config.provider.type
        ScheduleProviderFactory._log.info(f"Building '{provider_type}' schedule provider")
        key = provider_type.lower()
        if key == "local":
            from .local import LocalScheduleProvider

            return LocalScheduleProvider.from_config(schedule_config.provider)
        if key == "eventbridge":
            with require_extra("aws", "schedule.provider.type: eventbridge"):
                from .eventbridge import EventBridgeScheduleProvider

            return EventBridgeScheduleProvider.from_config(schedule_config.provider)
        if "." not in provider_type:
            raise AKConfigError(
                f"unknown schedule provider type '{provider_type}'; expected one of {_BUILTIN_SCHEDULE_PROVIDERS} "
                "or a dotted path to a ScheduleProvider subclass"
            )
        return resolve_dotted(provider_type, base=ScheduleProvider).from_config(schedule_config.provider)
