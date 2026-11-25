from datetime import datetime
from pathlib import Path
from typing import Any

from ak_bench.errors import FetcherTypeError
from ak_bench.fetchers.core.info_fetcher import InfoFetcher
from ak_bench.hosts.host import Deployment, RunInfo
from ak_bench.run.run_log import RunLog


class FetcherInvoker:
    """Calls a fetcher; a failure goes to the run log instead of stopping the run."""

    def __init__(self, run: RunInfo, deployment: Deployment, run_log: RunLog):
        self.run = run
        self.deployment = deployment
        self.run_log = run_log

    def fetch_and_store(self, f: InfoFetcher, list_name: str, start: datetime, end: datetime, results: Path) -> bool:
        try:
            f.fetch_and_store(self.run, self.deployment, start, end, results)
            return True
        except Exception as e:  # noqa: BLE001 - any fetcher failure is logged, never stops the run
            self._log_failure(f, list_name, e)
            return False

    def fetch(self, f: InfoFetcher, list_name: str, start: datetime, end: datetime) -> tuple[bool, Any]:
        try:
            result = f.fetch(self.run, self.deployment, start, end)
            # The caller reads the result (has_value / is_settled), so a wrong type is refused here, not left to crash there
            if not isinstance(result, f.result_type):
                raise FetcherTypeError(f"fetcher '{f.name}': fetch() returned {type(result).__name__}, expected {f.result_type.__name__}")
            return True, result
        except Exception as e:  # noqa: BLE001 - any fetcher failure is logged, never stops the run
            self._log_failure(f, list_name, e)
            return False, None

    def _log_failure(self, f: InfoFetcher, list_name: str, e: Exception) -> None:
        self.run_log.error(f"fetcher {f.name} in {list_name} failed: {type(e).__name__}: {e}")
