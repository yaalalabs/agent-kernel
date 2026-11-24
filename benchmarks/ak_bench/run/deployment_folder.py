import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ak_bench.errors import BenchConfigError, ScriptFailed
from ak_bench.platforms.base import Deployment


@dataclass(frozen=True)
class ScriptEnv:
    """The inputs deploy.sh / destroy.sh get (benchmarks/app/deploy/README.md)."""

    deployment_id: str
    auth_secret: str
    mock_delays: tuple[float, float] | None
    host_settings: dict[str, Any]
    output_dir: Path

    def as_env(self) -> dict[str, str]:
        env = {
            "AK_BENCH_DEPLOYMENT_ID": self.deployment_id,
            "AK_BENCH_AUTH_SECRET": self.auth_secret,
            "AK_BENCH_HOST_SETTINGS": json.dumps(self.host_settings),
            "AK_BENCH_OUTPUT": str(self.output_dir),
        }
        if self.mock_delays is not None:
            env["AK_BENCH_MOCK_AGENT_MIN_DELAY_S"] = str(self.mock_delays[0])
            env["AK_BENCH_MOCK_AGENT_MAX_DELAY_S"] = str(self.mock_delays[1])
        return env


class DeploymentFolder:
    """<root>/<host>-<mode>-<message-type>/ with its deploy.sh and destroy.sh."""

    def __init__(self, root: Path, host: str, mode: str, message_type: str):
        self.path = Path(root) / f"{host}-{mode}-{message_type}"

    def check(self) -> None:
        for path in (self.path, self.path / "deploy.sh", self.path / "destroy.sh"):
            if not path.exists():
                raise BenchConfigError(f"deployment folder incomplete: {path} not found")

    def deploy(self, env: ScriptEnv) -> Deployment:
        """Runs deploy.sh and reads the deployment.json it wrote into AK_BENCH_OUTPUT."""
        env.output_dir.mkdir(parents=True, exist_ok=True)
        self._run("deploy.sh", env)
        output = env.output_dir / "deployment.json"
        try:
            data = json.loads(output.read_text())
        except (OSError, ValueError) as e:
            raise ScriptFailed(f"deploy.sh in {self.path} wrote no readable {output}: {e}") from e
        return Deployment.from_json(data)

    def destroy(self, env: ScriptEnv) -> None:
        self._run("destroy.sh", env)

    def _run(self, script: str, env: ScriptEnv) -> None:
        # AK_BENCH_* from the caller's shell are dropped, so a stale mock-delay variable can't switch the agent.
        base = {key: value for key, value in os.environ.items() if not key.startswith("AK_BENCH_")}
        code = subprocess.run(["bash", script], cwd=self.path, env=base | env.as_env(), check=False).returncode
        if code != 0:
            raise ScriptFailed(f"{script} in {self.path} failed (exit {code})")
