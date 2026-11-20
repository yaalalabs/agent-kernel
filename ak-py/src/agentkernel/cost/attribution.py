"""Attribution: which user, agent, session and request a model call is billed to (spec §9).

Every user id Agent Kernel derives (the budget check, usage reads, thread naming) goes through the configured
``Attributor``, never straight from ``principal.subject``, so a bring-your-own attributor keys everything the same way.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.model import Principal
from ..core.util.factory import AKConfigError, resolve_dotted
from .model import Attribution

if TYPE_CHECKING:
    from ..core.config import _CostAttributionConfig


@dataclass(frozen=True)
class AttributionContext:
    """What a run knows about a model call: the published principal and the run's agent, session and request."""

    principal: Principal | None
    agent_name: str | None
    session_id: str | None
    request_id: str | None


class Attributor(ABC):
    """Maps a run's context to the ``Attribution`` its model calls are billed to.

    The user id must come from the principal alone, never from the acting agent (``principal.actor``) or other session
    data: the principal is published by Agent Kernel and application code cannot write it. A bring-your-own attributor
    reads its own settings from ``config.model_extra``.
    """

    def __init__(self, config: "_CostAttributionConfig") -> None:
        self.config = config

    @abstractmethod
    def resolve(self, ctx: AttributionContext) -> Attribution:
        """The attribution for ``ctx``; must not modify it."""


class DefaultAttributor(Attributor):
    """Bills the principal's subject: an identity-provider subject, a messaging sender id, or ``anonymous``.

    A messaging sender id that equals an identity-provider subject is the same user here; an attributor that
    prefixes ``principal.provider`` keeps them apart.
    """

    def resolve(self, ctx: AttributionContext) -> Attribution:
        principal = ctx.principal or Principal.anonymous()
        return Attribution(user_id=principal.subject, agent_id=ctx.agent_name, session_id=ctx.session_id, request_id=ctx.request_id)


class AttributorFactory:
    """Creates the configured attributor. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.attribution")

    @staticmethod
    def create(config: "_CostAttributionConfig") -> Attributor:
        """Build the attributor the ``cost.attribution`` block names.

        :raises AKConfigError: If the type is neither ``default`` nor a dotted path to an Attributor subclass.
        """
        AttributorFactory._log.info(f"Building '{config.type}' attributor")
        if config.type.lower() == "default":
            return DefaultAttributor(config)
        if "." not in config.type:
            raise AKConfigError(f"unknown cost.attribution.type '{config.type}'; expected default or a dotted path to an Attributor subclass")
        return resolve_dotted(config.type, base=Attributor)(config)
