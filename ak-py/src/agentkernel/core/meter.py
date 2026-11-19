"""The seam between core and cost management.

Runtime asks a ``RunMeter`` before every turn whether the run may go ahead, and the error classifier asks it whether
a failure was a gateway budget refusal. Core never imports ``agentkernel.cost``: ``RunMeterFactory`` is the only way
in, and ``BudgetDecision`` lives here because ``RunMeter.check`` returns it (``agentkernel.cost.model`` re-exports it).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from .base import Agent, Session


class BudgetDecision(BaseModel):
    """Whether a run may go ahead: allow it, allow it with a logged warning, or deny it with a message for the user."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["allow", "warn", "deny"]
    message: str | None = None

    @classmethod
    def allow(cls) -> BudgetDecision:
        return cls(kind="allow")

    @classmethod
    def warn(cls, message: str) -> BudgetDecision:
        return cls(kind="warn", message=message)

    @classmethod
    def deny(cls, message: str) -> BudgetDecision:
        return cls(kind="deny", message=message)


class RunMeter(ABC):
    """Meters runs against budgets. Not a pluggable backend: the one implementation is cost management's."""

    @abstractmethod
    async def check(self, session: Session, agent: Agent) -> BudgetDecision:
        """Decide whether the run may start. Called by Runtime before the pre-hooks, after the run's principal and
        request id are published on the session (``Session.get_principal()``, ``Session.get_request_id()``)."""

    @abstractmethod
    def is_budget_refusal(self, error: BaseException) -> bool:
        """Whether ``error`` (or an exception in its ``__cause__`` / ``__context__`` chain) is a gateway budget refusal."""


class NoOpRunMeter(RunMeter):
    """The meter without cost management: allows every run and recognises no refusal."""

    async def check(self, session: Session, agent: Agent) -> BudgetDecision:
        return BudgetDecision.allow()

    def is_budget_refusal(self, error: BaseException) -> bool:
        return False


class RunMeterFactory:
    """The process-wide RunMeter."""

    _instance: ClassVar[RunMeter | None] = None
    _lock: ClassVar[RLock] = RLock()

    @classmethod
    def get(cls) -> RunMeter:
        """The meter, built on first use."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    # shortcut: always the no-op meter, so a configured `cost` block enforces nothing yet;
                    # #972/#973 build CostManager here (lazy import) when AKConfig.get().cost is set.
                    cls._instance = NoOpRunMeter()
        return cls._instance

    @classmethod
    def peek(cls) -> RunMeter:
        """The meter ``get()`` already built, else a no-op. Never builds one, so classifying an error has no side effects."""
        return cls._instance or NoOpRunMeter()

    @classmethod
    def reset(cls) -> None:
        """Forget the meter, so the next ``get()`` builds a new one. For tests."""
        with cls._lock:
            cls._instance = None
