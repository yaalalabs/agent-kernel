"""Cost management's process-wide pieces (spec §11.4, §15). ``NativeBudgetSync`` writes budgets to a gateway that
enforces them itself; ``CostManager`` (which composes everything) joins it here."""

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from ..core.util.factory import AKConfigError
from .errors import UsageRetrievalError
from .gateway.base import LLMGateway
from .model import SYSTEM_USER_ID, BudgetLimit
from .pricing import PricingSource

if TYPE_CHECKING:
    from ..core.config import _CostBudgetsConfig

_CHUNK = 50  # user rows per background sync call
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

    def start(self) -> None:
        """The startup sync; ``CostManager`` calls it once. Blocks for the definitions, about D + 2 round trips.

        :raises AKConfigError: If the gateway refuses the admin key or the budget shape.
        """
        limits = self._native_limits()
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
