"""The ``LLMGateway`` ABC: the one seam cost management reads usage, spend and budgets through (spec §4).

No httpx import here: a bring-your-own gateway need not be HTTP, and httpx ships with the ``cost`` extra.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote, unquote

from ..errors import UnsupportedCapabilityError, UsageTruncatedError
from ..model import (
    Attribution,
    BudgetLimit,
    GatewayCapabilities,
    ModelUsage,
    SpendCursor,
    SpendTotal,
    UsageQuery,
    UsageResult,
    UsageWindow,
)

if TYPE_CHECKING:
    from ...core.config import _CostGatewayConfig
    from ...secret import SecretManager

_ENCODED_PREFIX = "ak~"


class LLMGateway(ABC):
    """An LLM gateway that model calls go through, and that usage, spend and budgets are read from.

    Each optional operation raises ``UnsupportedCapabilityError`` unless the subclass declares its capability in
    ``capabilities`` and overrides it. Settings come from the constructor only, never from ``AKConfig``; a
    bring-your-own gateway reads its own settings from ``config.model_extra``.
    """

    name: ClassVar[str]
    # Not a ClassVar: a gateway whose capabilities depend on its config (LiteLLM's mode) sets them per instance.
    capabilities: GatewayCapabilities = GatewayCapabilities()

    def __init__(self, config: "_CostGatewayConfig", secrets: "SecretManager") -> None:
        self.config = config
        self.secrets = secrets

    @abstractmethod
    def attribution_headers(self, attribution: Attribution) -> dict[str, str]:
        """The headers that bill a model call to ``attribution``. Ids go through ``gateway_user_id``."""

    @abstractmethod
    def is_budget_refusal(self, error: BaseException) -> bool:
        """Whether ``error`` (one exception, not its chain) is this gateway refusing a call over budget.

        Decide on the error's type or code, never on an HTTP status alone: a 429 is usually a rate limit.
        """

    def model_base_url(self, model: str) -> str:
        """The base URL model calls for ``model`` are sent to."""
        return self.config.base_url

    async def probe(self) -> None:
        """Startup check that the gateway is reachable and compatible. The default checks nothing."""

    async def close(self) -> None:
        """Release the gateway's connections."""

    # Optional operations: a subclass overrides the ones whose capability it declares.

    async def fetch_usage(self, query: UsageQuery) -> UsageResult:
        """Every row matching ``query``, all pages, in gateway order. Needs ``usage_retrieval``."""
        raise UnsupportedCapabilityError(self.name, "usage_retrieval")

    async def total_spend(self, user_id: str, window: UsageWindow) -> SpendTotal:
        """The user's spend over ``window``, aggregated by the gateway. Needs ``windowed_spend``."""
        raise UnsupportedCapabilityError(self.name, "windowed_spend")

    async def fetch_usage_since(self, user_id: str, cursor: SpendCursor | None, until: datetime) -> tuple[list[ModelUsage], SpendCursor | None, bool]:
        """One batch of the user's rows with ``cursor < row <= until``: ``(rows, next_cursor, caught_up)``.

        Needs ``usage_retrieval``.
        """
        raise UnsupportedCapabilityError(self.name, "usage_retrieval")

    async def sync_budget_definitions(self, limits: Iterable[BudgetLimit]) -> None:
        """Create or update one gateway budget per distinct limit. Needs ``native_user_budget``."""
        raise UnsupportedCapabilityError(self.name, "native_user_budget")

    async def sync_budgets(self, budgets: Mapping[str, BudgetLimit | None]) -> None:
        """Attach each user to its budget; ``None`` means no budget. Needs ``native_user_budget``."""
        raise UnsupportedCapabilityError(self.name, "native_user_budget")

    # Id transform (coupling rule 5): the only place an id becomes a gateway value, and back.

    def gateway_user_id(self, value: str) -> str:
        """``value`` as the gateway stores it: unchanged when it is printable ASCII without ``,``, else encoded.

        Safe in a header (no CR or LF) and in a comma-separated list. An id that already starts with ``ak~`` is
        encoded too, so ``raw_user_id`` is an exact inverse.
        """
        if value.isascii() and value.isprintable() and "," not in value and not value.startswith(_ENCODED_PREFIX):
            return value
        return _ENCODED_PREFIX + quote(value, safe="")

    def raw_user_id(self, value: str) -> str:
        """The inverse of ``gateway_user_id``, applied when mapping gateway rows."""
        return unquote(value[len(_ENCODED_PREFIX) :]) if value.startswith(_ENCODED_PREFIX) else value

    # Helpers for adapters.

    def _require_filters(self, query: UsageQuery) -> None:
        """Raise ``UnsupportedCapabilityError`` for a dimension ``query`` filters on that the gateway cannot."""
        unsupported = query.filters() - self.capabilities.filters
        if unsupported:
            raise UnsupportedCapabilityError(self.name, f"filter {sorted(unsupported)[0].value}")

    @staticmethod
    def _next_batch(
        page: Iterable[ModelUsage], cursor: SpendCursor | None, until: datetime, *, complete: bool
    ) -> tuple[list[ModelUsage], SpendCursor | None, bool]:
        """Bound one server page exactly to ``cursor < row <= until``, for gateways whose filter is coarser.

        :param page: One page from a query covering at least the cursor's second through ``until``.
        :param cursor: Where the previous batch ended; None reads from the start.
        :param until: The last timestamp to include.
        :param complete: True when the page held every remaining row the query matches.
        :return: The kept rows in ``(timestamp, row_id)`` order, the cursor after them, and whether no rows remain.
        :raises UsageTruncatedError: If a full page holds nothing past the cursor: more rows share the cursor's
            second than a page holds, so the cursor can never advance.
        """
        page = list(page)

        def after_cursor(row: ModelUsage) -> bool:
            if cursor is None or row.timestamp > cursor.timestamp:
                return True
            return row.timestamp == cursor.timestamp and row.row_id not in cursor.ids_at_timestamp

        rows = sorted(
            (row for row in page if row.timestamp <= until and after_cursor(row)),
            key=lambda row: (row.timestamp, row.row_id),
        )
        caught_up = complete or any(row.timestamp > until for row in page)
        if not rows:
            if not caught_up:
                raise UsageTruncatedError("a full page of usage rows shares one second; the spend cursor cannot advance")
            return rows, cursor, caught_up
        last = rows[-1].timestamp
        ids = {row.row_id for row in rows if row.timestamp == last}
        if cursor is not None and cursor.timestamp == last:
            ids |= cursor.ids_at_timestamp
        return rows, SpendCursor(timestamp=last, ids_at_timestamp=frozenset(ids)), caught_up
