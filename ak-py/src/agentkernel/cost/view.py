"""``UsageView``: a user's usage report over a window, served to that user only (spec §13)."""

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from ..core.model import Principal
from ..core.util.factory import AKConfigError, resolve_dotted
from .attribution import AttributionContext, Attributor
from .errors import UnsupportedCapabilityError, UsageRetrievalError, UsageTruncatedError
from .gateway.base import LLMGateway
from .model import AgentUsage, GatewayFilter, ModelUsage, SessionUsage, UsageQuery, UsageReport, UsageWindow
from .pricing import PricingSource

if TYPE_CHECKING:
    from ..core.config import _CostViewConfig

# The query field each dimension filters on.
_FIELDS = {
    GatewayFilter.USER: "user_id",
    GatewayFilter.AGENT: "agent_id",
    GatewayFilter.SESSION: "session_id",
    GatewayFilter.MODEL: "model",
    GatewayFilter.PROVIDER: "provider",
}


class UsageView(ABC):
    """Builds a user's ``UsageReport``. A bring-your-own view receives the same constructor arguments and may add keys
    to the report; it must keep ``UsageReport.ENVELOPE_KEYS`` and refuse other users' queries."""

    def __init__(self, gateway: LLMGateway, pricing: PricingSource, attributor: Attributor, config: "_CostViewConfig") -> None:
        self.gateway = gateway
        self.pricing = pricing
        self.attributor = attributor
        self.config = config

    @abstractmethod
    async def report(self, query: UsageQuery, principal: Principal) -> UsageReport:
        """The report for ``query``.

        :raises PermissionError: If ``query.user_id`` is not the principal's own attributed id.
        """


class DefaultUsageView(UsageView):
    """Fetches the window once, splitting it into days and then hours only when the gateway truncates, and aggregates
    in memory. Filters the gateway cannot apply are applied here."""

    async def report(self, query: UsageQuery, principal: Principal) -> UsageReport:
        own_id = self.attributor.resolve(AttributionContext(principal, None, None, None)).user_id
        if query.user_id is None or query.user_id != own_id:
            raise PermissionError("usage can be read only for the caller's own user id")

        unsupported = query.filters() - self.gateway.capabilities.filters
        for required in (GatewayFilter.USER, GatewayFilter.TIME_RANGE):
            if required in unsupported:
                raise UnsupportedCapabilityError(self.gateway.name, f"filter {required.value}")
        client_side = {_FIELDS[f]: getattr(query, _FIELDS[f]) for f in unsupported if f in _FIELDS}
        gateway_query = query.model_copy(update=dict.fromkeys(client_side))

        rows = [
            row
            for row in await self._fetch(gateway_query)
            if row.user_id == query.user_id and all(getattr(row, field) == value for field, value in client_side.items())
        ]
        currency = sorted(self.gateway.capabilities.currencies)[0]
        billed = []
        for row in rows:
            if row.currency != currency:
                raise UsageRetrievalError(f"usage row {row.row_id!r} is in {row.currency}, the report in {currency}", gateway=self.gateway.name)
            billed.append(row.model_copy(update={"billed_cost": self.pricing.bill(row)}))

        totals = self._usage(billed)
        by_session = query.agent_id is not None or query.session_id is not None
        return UsageReport(
            user_id=query.user_id,
            currency=currency,
            window=UsageWindow(start=query.start, end=query.end),
            total_cost=totals.cost,
            total_provider_cost=totals.provider_cost,
            total_input_tokens=totals.input_tokens,
            total_output_tokens=totals.output_tokens,
            total_cached_input_tokens=totals.cached_input_tokens,
            unpriced_requests=totals.unpriced_requests,
            agents=[self._usage(group, agent_id=agent) for agent, group in self._group(billed, "agent_id")],
            sessions=(
                [
                    SessionUsage(**self._usage(group, agent_id=group[0].agent_id).model_dump(), session_id=key[1])
                    for key, group in self._group_pairs(billed)
                ]
                if by_session
                else None
            ),
        )

    async def _fetch(self, query: UsageQuery) -> list[ModelUsage]:
        """The whole window at once; on truncation (and only with a row cap), day by day, then hour by hour."""
        try:
            return (await self.gateway.fetch_usage(query)).rows
        except UsageTruncatedError:
            if self.gateway.capabilities.row_cap is None:
                raise
        rows: list[ModelUsage] = []
        for day_start, day_end in self._slices(query.start, query.end, timedelta(days=1)):
            day = query.model_copy(update={"start": day_start, "end": day_end})
            try:
                rows += (await self.gateway.fetch_usage(day)).rows
            except UsageTruncatedError:
                for hour_start, hour_end in self._slices(day_start, day_end, timedelta(hours=1)):
                    # An hour that still truncates re-raises: the report would be incomplete.
                    rows += (await self.gateway.fetch_usage(query.model_copy(update={"start": hour_start, "end": hour_end}))).rows
        return rows

    @staticmethod
    def _slices(start: datetime, end: datetime, step: timedelta) -> Iterator[tuple[datetime, datetime]]:
        """``[start, end)`` cut at UTC day or hour boundaries."""
        cursor = start
        while cursor < end:
            if step == timedelta(days=1):
                boundary = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + step
            else:
                boundary = cursor.replace(minute=0, second=0, microsecond=0) + step
            yield cursor, min(boundary, end)
            cursor = min(boundary, end)

    @staticmethod
    def _usage(rows: list[ModelUsage], agent_id: str | None = None) -> AgentUsage:
        return AgentUsage(
            agent_id=agent_id,
            requests=len(rows),
            cost=sum((row.billed_cost for row in rows if row.billed_cost is not None), Decimal(0)),
            provider_cost=sum((row.provider_cost for row in rows if row.provider_cost is not None), Decimal(0)),
            input_tokens=sum(row.input_tokens or 0 for row in rows),
            output_tokens=sum(row.output_tokens or 0 for row in rows),
            cached_input_tokens=sum(row.cached_input_tokens or 0 for row in rows),
            unpriced_requests=sum(1 for row in rows if row.billed_cost is None),
        )

    @staticmethod
    def _group(rows: list[ModelUsage], field: str) -> list[tuple[str | None, list[ModelUsage]]]:
        groups: dict[str | None, list[ModelUsage]] = defaultdict(list)
        for row in rows:
            groups[getattr(row, field)].append(row)
        return sorted(groups.items(), key=lambda item: (item[0] is not None, item[0] or ""))

    @staticmethod
    def _group_pairs(rows: list[ModelUsage]) -> list[tuple[tuple[str | None, str | None], list[ModelUsage]]]:
        groups: dict[tuple[str | None, str | None], list[ModelUsage]] = defaultdict(list)
        for row in rows:
            groups[(row.agent_id, row.session_id)].append(row)
        return sorted(groups.items(), key=lambda item: tuple((part is not None, part or "") for part in item[0]))


class UsageViewFactory:
    """Creates the configured view. It holds no instance: ``CostManager`` owns the one it builds."""

    _log = logging.getLogger("ak.cost.view")

    @staticmethod
    def create(config: "_CostViewConfig", gateway: LLMGateway, pricing: PricingSource, attributor: Attributor) -> UsageView:
        """Build the view ``cost.view.type`` names.

        :raises AKConfigError: If the type is neither ``default`` nor a dotted path to a UsageView subclass.
        """
        UsageViewFactory._log.info(f"Building '{config.type}' usage view")
        if config.type.lower() == "default":
            return DefaultUsageView(gateway, pricing, attributor, config)
        if "." not in config.type:
            raise AKConfigError(f"unknown cost.view.type '{config.type}'; expected default or a dotted path to a UsageView subclass")
        return resolve_dotted(config.type, base=UsageView)(gateway, pricing, attributor, config)
