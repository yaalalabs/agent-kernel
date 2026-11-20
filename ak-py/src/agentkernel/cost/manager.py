"""Cost management's process-wide pieces (spec §11.4, §15). ``NativeBudgetSync`` writes budgets to a gateway that
enforces them itself; ``CostManager`` (which composes everything) joins it here."""

import asyncio
import concurrent.futures
import logging
import threading
from collections import deque
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, ClassVar

from ..core.base import Agent, Session
from ..core.config import AKConfig
from ..core.meter import BudgetDecision, RunMeter
from ..core.model import Principal
from ..core.util.factory import AKConfigError
from .attribution import AttributionContext, Attributor, AttributorFactory
from .budget import BudgetPolicy, BudgetPolicyFactory, SpendReader
from .errors import UsageRetrievalError
from .gateway.base import LLMGateway
from .gateway.factory import LLMGatewayFactory
from .ledger.factory import SpendLedgerFactory
from .ledger.flow import LedgerSpendFlow
from .model import SYSTEM_USER_ID, Attribution, BudgetLimit
from .pricing import PricingSource, PricingSourceFactory, StaticPricingSource
from .view import UsageView, UsageViewFactory

if TYPE_CHECKING:
    from ..core.config import _CostBudgetsConfig, _CostConfig

_CHUNK = 50  # user rows per background sync call
_REFUSAL_WALK_LIMIT = 16  # exception links is_budget_refusal visits
_THREAD_NAME = "ak-cost-budget-sync"


class NativeBudgetSync:
    """Puts budgets on a gateway that can refuse calls over budget itself, so those users skip the fallback check.

    A budget is native when the gateway declares ``native_user_budget``, the budget blocks rather than warns, and
    pricing bills at cost (the gateway counts provider cost). A gateway that declares ``native_user_budget`` must
    represent every budget period exactly; LiteLLM does (spec deviation 8).

    Startup writes the budget definitions and the ``ak-system`` row synchronously, so a bad admin key or a rejected
    shape fails startup. Per-user rows go to the ``ak-cost-budget-sync`` thread, and a user is ``covers()`` only once
    theirs is written. Users on the default budget are written lazily, on their first run in the process.
    """

    _log = logging.getLogger("ak.cost.native_budget")

    def __init__(
        self,
        gateway: LLMGateway,
        pricing: PricingSource,
        config: "_CostBudgetsConfig | None",
        *,
        base_delay: float = 1.0,
        max_delay: float = 300.0,
    ) -> None:
        """
        :param base_delay: Seconds before the background thread's first retry; doubles per failure.
        :param max_delay: The retry delay's cap.
        """
        self._gateway = gateway
        self._pricing = pricing
        self._config = config
        self._base_delay = base_delay
        self._max_delay = max_delay
        # shortcut: one string per user seen, never evicted; cap it with an LRU if memory becomes a concern.
        self._synced: set[str] = set()
        self._lock = threading.Lock()
        self._ready = threading.Event()  # the budget definitions and ak-system are on the gateway
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def eligible(self, limit: BudgetLimit) -> bool:
        return self._gateway.capabilities.native_user_budget and limit.action == "block" and self._pricing.bills_at_cost

    def start(self, *, after: Callable[[], Coroutine[Any, Any, None]] | None = None) -> None:
        """The startup sync; ``CostManager`` calls it once. Blocks for the definitions, about D + 2 round trips.

        :param after: Work that must succeed first, on the background thread: the startup probe, when it found the
            gateway unavailable. The whole sync then runs in the background after it.
        :raises AKConfigError: If the gateway refuses the admin key or the budget shape.
        """
        limits = self._native_limits()
        if after is not None:

            async def deferred() -> None:
                await after()
                if limits:
                    await self._sync_all(limits)

            self._start_thread(deferred)
            return
        if not limits:
            return
        try:
            _run_on_own_loop(lambda: self._sync_definitions(limits))
        except UsageRetrievalError as exc:
            if exc.auth:
                raise AKConfigError(f"the gateway refused the admin key while syncing budgets ({exc.status})") from exc
            self._log.error(f"Syncing budgets to the gateway failed ({type(exc).__name__}); retrying in the background")
            self._start_thread(lambda: self._sync_all(limits))
            return
        self._start_thread(self._sync_users)

    async def ensure(self, user_id: str, default: BudgetLimit) -> bool:
        """Put the default budget on a user the first time this process sees them.

        :return: True when the gateway enforces the user's budget; False sends the run to the fallback check.
        """
        if not self.eligible(default) or not self._ready.is_set():
            return False  # before the definitions are written, the default budget row may not exist yet
        if self.covers(user_id):
            return True
        try:
            await self._gateway.sync_budgets({user_id: default})
        except (UsageRetrievalError, AKConfigError) as exc:
            self._log.warning(f"Putting the default budget on user '{user_id}' failed ({type(exc).__name__}); using the fallback check")
            return False
        with self._lock:
            self._synced.add(user_id)
        return True

    def covers(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._synced

    def close(self) -> None:
        """Stop the background thread at its next wait."""
        self._stop.set()

    def _native_limits(self) -> list[BudgetLimit]:
        if self._config is None:
            return []
        candidates = [self._config.default, *self._config.users.values()]
        return [limit for limit in candidates if limit is not None and self.eligible(limit)]

    def _native_users(self) -> dict[str, BudgetLimit]:
        users = self._config.users if self._config else {}
        return {user_id: limit for user_id, limit in users.items() if self.eligible(limit)}

    async def _sync_definitions(self, limits: list[BudgetLimit]) -> None:
        await self._gateway.sync_budget_definitions(limits)
        await self._gateway.sync_budgets({SYSTEM_USER_ID: None})  # Agent Kernel's own calls: billed, never capped
        self._ready.set()

    async def _sync_all(self, limits: list[BudgetLimit]) -> None:
        if not self._ready.is_set():
            await self._sync_definitions(limits)
        await self._sync_users()

    async def _sync_users(self) -> None:
        """Write the users not yet written, a chunk at a time; a retry resumes after the last written chunk."""
        pending = [user_id for user_id in self._native_users() if not self.covers(user_id)]
        users = self._native_users()
        for start in range(0, len(pending), _CHUNK):
            chunk = pending[start : start + _CHUNK]
            await self._gateway.sync_budgets({user_id: users[user_id] for user_id in chunk})
            with self._lock:
                self._synced.update(chunk)

    def _start_thread(self, work: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self._thread = threading.Thread(target=self._run_with_backoff, args=(work,), name=_THREAD_NAME, daemon=True)
        self._thread.start()

    def _run_with_backoff(self, work: Callable[[], Coroutine[Any, Any, None]]) -> None:
        delay = self._base_delay
        while not self._stop.is_set():
            try:
                asyncio.run(work())
                return
            except UsageRetrievalError as exc:
                if exc.auth:
                    self._log.error(f"Budget sync stopped: the gateway refused the admin key ({exc.status})")
                    return
                self._log.warning(f"Budget sync failed ({type(exc).__name__}); retrying in {delay:g}s")
            except AKConfigError as exc:
                self._log.error(f"Budget sync stopped: {exc}")
                return
            if self._stop.wait(delay):
                return
            delay = min(delay * 2, self._max_delay)


def _run_on_own_loop(work: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Run a coroutine to completion on a loop of its own, from any thread, inside a running loop or not.

    ``run_async_sync`` cannot: it calls ``run_until_complete`` on the caller's loop, which raises while that loop runs,
    and the first ``CostManager.get()`` can come from a run inside the serving loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(work())).result()


class CostManager(RunMeter):
    """Cost management for the process: the gateway and every part built on it, from the ``cost`` block.

    Construction checks the configuration against what the gateway can do, probes the gateway and starts the native
    budget sync, so a bad configuration fails when the manager is built. Only ``get()`` reads ``AKConfig``.
    """

    _instance: ClassVar["CostManager | None"] = None
    _lock: ClassVar[threading.RLock] = threading.RLock()
    _log = logging.getLogger("ak.cost.manager")

    gateway: LLMGateway
    attributor: Attributor
    pricing: PricingSource
    policy: BudgetPolicy
    view: UsageView

    def __init__(self, config: "_CostConfig") -> None:
        """
        :raises AKConfigError: If the configuration asks for something the gateway cannot do, or the gateway refuses
            the configuration at startup.
        """
        self.gateway = LLMGatewayFactory.create(config.gateway)
        try:
            self._build(config)
        except BaseException:
            _run_on_own_loop(self.gateway.close)
            raise

    def _build(self, config: "_CostConfig") -> None:
        self.attributor = AttributorFactory.create(config.attribution)
        self.pricing = PricingSourceFactory.create(config.pricing)
        budgets = config.budgets
        self.native = NativeBudgetSync(self.gateway, self.pricing, budgets)
        self._check_capabilities(budgets)

        capabilities = self.gateway.capabilities
        ledger_flow = None
        if budgets is not None and not capabilities.windowed_spend and capabilities.usage_retrieval:
            periods = {limit.period for limit in self._limits(budgets)}
            if periods:
                ledger = SpendLedgerFactory.create(budgets.ledger, periods)
                ledger_flow = LedgerSpendFlow(self.gateway, ledger, periods)
        elif budgets is not None and budgets.ledger is not None:
            self._log.warning(f"cost.budgets.ledger is ignored: gateway '{self.gateway.name}' reports windowed spend itself")

        self._probe_ok = False
        reader = SpendReader(self.gateway, ledger_flow=ledger_flow, ready=lambda: self._probe_ok)
        self.policy = BudgetPolicyFactory.create(budgets, reader, self.pricing, native=self.native)
        self.view = UsageViewFactory.create(config.view, self.gateway, self.pricing, self.attributor)
        self._start()

    def _check_capabilities(self, budgets: "_CostBudgetsConfig | None") -> None:
        """What the budgets need from the gateway and pricing (spec, Config changes)."""
        if budgets is None:
            return
        capabilities = self.gateway.capabilities
        gateway = self.gateway.name
        if not (capabilities.native_user_budget or capabilities.windowed_spend or capabilities.usage_retrieval):
            raise AKConfigError(f"cost.budgets needs a gateway that can enforce or report spend; gateway '{gateway}' can do neither")
        for limit in self._limits(budgets):
            if limit.currency not in capabilities.currencies:
                raise AKConfigError(
                    f"a {limit.currency} budget cannot be checked: gateway '{gateway}' reports {', '.join(sorted(capabilities.currencies))}"
                )
            if isinstance(self.pricing, StaticPricingSource) and limit.currency != "USD":
                raise AKConfigError(f"a {limit.currency} budget cannot use static pricing, whose rates are USD")
            if not self.native.eligible(limit) and not (capabilities.windowed_spend or capabilities.usage_retrieval):
                raise AKConfigError(
                    f"a budget gateway '{gateway}' cannot enforce itself (action warn, or pricing not at cost) needs spend reads, "
                    "which this gateway does not offer"
                )

    @staticmethod
    def _limits(budgets: "_CostBudgetsConfig") -> list[BudgetLimit]:
        return [limit for limit in (budgets.default, *budgets.users.values()) if limit is not None]

    def _start(self) -> None:
        """Probe the gateway, then start the native budget sync (§11.4, §11.5)."""
        try:
            _run_on_own_loop(self.gateway.probe)
        except UsageRetrievalError as exc:
            if exc.auth:
                raise AKConfigError(f"gateway '{self.gateway.name}' refused the configured key at startup ({exc.status})") from exc
            self._log.error(f"Gateway '{self.gateway.name}' did not answer its startup probe ({type(exc).__name__}); retrying in the background")

            async def probe() -> None:
                await self.gateway.probe()
                self._probe_ok = True

            self.native.start(after=probe)
            return
        self._probe_ok = True
        self.native.start()

    # Lifecycle

    @classmethod
    def get(cls) -> "CostManager | None":
        """The process-wide manager, built on first use; None without a ``cost`` block.

        :raises AKConfigError: If the ``cost`` block cannot be served.
        """
        config = AKConfig.get().cost
        if config is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance

    @classmethod
    def require(cls) -> "CostManager":
        manager = cls.get()
        if manager is None:
            raise AKConfigError("cost management requires a cost block in config.yaml")
        return manager

    @classmethod
    def validate_configuration(cls) -> None:
        """Build the manager now, so a bad configuration fails at startup rather than on the first run."""
        cls.get()

    @classmethod
    def reset(cls) -> None:
        """Drop the manager, stopping its background thread and closing the gateway. For tests."""
        with cls._lock:
            manager, cls._instance = cls._instance, None
        if manager is not None:
            manager.native.close()
            _run_on_own_loop(manager.gateway.close)

    # Attribution

    def user_id_for(self, principal: Principal | None) -> str | None:
        """The user id a principal is billed as, through the attributor; None without a principal."""
        attribution = self.attribution_for(principal, None, None)
        return attribution.user_id if attribution else None

    def attribution_for(self, principal: Principal | None, session_id: str | None, request_id: str | None) -> Attribution | None:
        if principal is None:
            return None
        return self.attributor.resolve(AttributionContext(principal, None, session_id, request_id))

    def current_attribution(self) -> Attribution | None:
        """The running call's attribution, from the current session and agent; None outside a run."""
        session = Session.current()
        if session is None:
            return None
        agent = Agent.current()
        context = AttributionContext(session.get_principal(), agent.name if agent else None, session.id, session.get_request_id())
        return self.attributor.resolve(context)

    def attribution_headers(self) -> dict[str, str]:
        """The gateway headers that bill the running call.

        :raises RuntimeError: Outside a run, where there is nothing to bill the call to.
        """
        attribution = self.current_attribution()
        if attribution is None:
            raise RuntimeError("attribution_headers() needs a running session")
        return self.gateway.attribution_headers(attribution)

    # RunMeter

    async def check(self, session: Session, agent: Agent) -> BudgetDecision:
        context = AttributionContext(session.get_principal(), agent.name, session.id, session.get_request_id())
        return await self.policy.check(self.attributor.resolve(context))

    def is_budget_refusal(self, error: BaseException) -> bool:
        """Whether the gateway refused a call over budget anywhere in the error's cause and context chain (§11.6)."""
        queue: deque[BaseException] = deque([error])
        seen: set[int] = set()
        checked = 0
        while queue and checked < _REFUSAL_WALK_LIMIT:  # a count of its own, so the walk ends whatever the chain holds
            link = queue.popleft()
            if id(link) in seen:
                continue
            seen.add(id(link))
            checked += 1
            if self.gateway.is_budget_refusal(link):
                return True
            queue.extend(cause for cause in (link.__cause__, link.__context__) if cause is not None)
        return False
