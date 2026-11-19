"""Typed errors of the cost management capability.

Budget checks map every one of these to ``cost.budgets.on_error``; the usage route maps them to HTTP statuses.
None of them carries credentials, headers or query strings.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .model import SpendCursor


class CostError(Exception):
    """Base class of every cost management error."""


class UnsupportedCapabilityError(CostError):
    """The gateway does not declare the capability (or filter) an operation needs."""

    def __init__(self, gateway: str, capability: str) -> None:
        super().__init__(f"gateway {gateway!r} does not support {capability!r}")
        self.gateway = gateway
        self.capability = capability


class UsageRetrievalError(CostError):
    """Usage or spend could not be read: unreachable gateway, 5xx, 401/403 (``auth``), malformed response, or a
    record in another currency. A failed read never becomes a zero total."""

    def __init__(
        self,
        message: str,
        *,
        gateway: str | None = None,
        path: str | None = None,
        status: int | None = None,
        auth: bool = False,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.gateway = gateway
        self.path = path
        self.status = status
        self.auth = auth
        # The response text, for a caller that must tell rejections apart; never part of the message or the logs.
        self.detail = detail


class UsageTruncatedError(CostError):
    """A usage query hit the gateway's row cap, so its rows are incomplete."""


class LedgerError(CostError):
    """A spend-ledger backend operation failed."""


class LedgerConflictError(LedgerError):
    """Another writer kept committing ledger batches ahead of this one."""


class LedgerBehindError(LedgerError):
    """The ledger has not caught up with the gateway within the check's time budget; progress so far is kept."""

    def __init__(self, user_id: str, cursor: "SpendCursor") -> None:
        super().__init__(f"spend ledger for user {user_id!r} is still catching up (at {cursor.timestamp.isoformat()})")
        self.user_id = user_id
        self.cursor = cursor
