import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mocks.host import mock_host

from ak_bench.config import BenchConfig
from ak_bench.fetchers.core.cost import CostInfo, CostItem
from ak_bench.hosts.host import Host
from ak_bench.hosts.registry import HostRegistry
from ak_bench.results.common.layout import ResultsLayout

DEPLOY_ROOT = Path(__file__).parent.parent / "mocks" / "deploy"
SECRET = "ab" * 32
RUN_ID = "20261124T100000Z"
DEPLOYMENT_ID = f"{RUN_ID}-mock-async-complete"


@dataclass
class Bench:
    """The mock host registered, the mock deployment folder, results under tmp_path."""

    config: BenchConfig
    results: Path
    host: Host

    def __call__(self, command: type, deploy_root: Path = DEPLOY_ROOT):
        return command(self.config, self.results, deploy_root)

    def deployment_dirs(self) -> list[Path]:
        return sorted(p.parent for p in self.results.glob("*/mock/mock/async/complete/state.json"))

    def deployment_dir(self, run_id: str = RUN_ID) -> Path:
        return ResultsLayout(self.results, run_id).deployment_dir("mock", "mock", "async", "complete")

    def state(self, run_id: str = RUN_ID) -> dict:
        return json.loads((self.deployment_dir(run_id) / "state.json").read_text())

    def run_log(self, run_id: str = RUN_ID) -> str:
        return ResultsLayout(self.results, run_id).run_log().read_text()


@pytest.fixture
def bench(fast_config, tmp_path, monkeypatch) -> Bench:
    host = mock_host()
    now = datetime.now(UTC)
    host.fetchers.after_teardown[0].script.append(CostInfo([CostItem(now, now, "ecs", 1.25, "unblended")]))
    monkeypatch.setitem(HostRegistry._BUILTINS, "mock", host)
    monkeypatch.setattr("ak_bench.run.commands.secrets.token_hex", lambda _: SECRET)  # MockWsServer checks tokens against it
    fast_config.step_run.max_cooldown_s = 0.3  # the mock cool-down checks never settle
    fast_config.hosts = ["mock"]
    return Bench(fast_config, tmp_path / "results", host)
