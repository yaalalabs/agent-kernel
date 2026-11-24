import fcntl
import json
import os
import socket
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ak_bench.errors import BenchConfigError, StepRefused
from ak_bench.hosts import HostRegistry
from ak_bench.platforms.base import Deployment, RunInfo
from ak_bench.results.keyed_csv import KeyedCsv
from ak_bench.results.layout import ResultsLayout
from ak_bench.run.run_log import RunLog


class DeploymentState:
    """state.json in the deployment directory. Mode 0600: it holds the auth secret until finish."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def locate(cls, results_root: Path, deployment_id: str) -> "DeploymentState":
        """Run ids, host, mode and message type contain no '-', so the id splits into exactly four parts."""
        parts = deployment_id.split("-")
        if len(parts) != 4:
            raise BenchConfigError(f"deployment id '{deployment_id}' is not <run-id>-<host>-<mode>-<message-type>")
        run_id, host, mode, message_type = parts
        platform = HostRegistry.get(host).platform
        path = ResultsLayout(results_root, run_id).deployment_dir(platform, host, mode, message_type) / "state.json"
        if not path.exists():
            raise BenchConfigError(f"no deployment '{deployment_id}': {path} not found")
        return cls(path)

    @classmethod
    def create(cls, path: Path, data: dict[str, Any]) -> "DeploymentState":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as e:
            raise BenchConfigError(f"{path} already exists") from e
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        return cls(path)

    @contextmanager
    def update(self) -> Iterator[dict[str, Any]]:
        """Read-modify-write under an exclusive flock on state.json.lock; nothing is written if the body raises."""
        with self.path.with_name("state.json.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # released when the file closes
            data = self.read()
            yield data
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state.", suffix=".tmp")  # created 0600
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def deployment(self) -> Deployment:
        return Deployment.from_json(self.read()["deployment"])

    def run_info(self) -> RunInfo:
        data = self.read()
        return RunInfo(data["run_id"], data["deployment_id"], data["host"], data["platform"], data["mode"], data["message_type"])


class StepLock:
    """The one-step-at-a-time lock in state.json: process id + machine."""

    def __init__(self, state: DeploymentState, run_log: RunLog, command: str):
        self.state = state
        self.run_log = run_log
        self.command = command

    def acquire(self) -> None:
        """StepRefused while a live process (or another machine) holds it; a dead local holder is taken over."""
        with self.state.update() as data:
            held = data.get("lock")
            if held:
                if held["host"] != socket.gethostname() or self._alive(held["pid"]):
                    raise StepRefused(self._describe(held))
                self.run_log.warning(f"took over stale step lock of pid {held['pid']} since {held['since']}")
            data["lock"] = {"pid": os.getpid(), "host": socket.gethostname(), "command": self.command, "since": KeyedCsv.cell(datetime.now(UTC))}

    def release(self) -> None:
        """Clears the lock only if this process holds it."""
        with self.state.update() as data:
            held = data.get("lock")
            if held and held["pid"] == os.getpid() and held["host"] == socket.gethostname():
                data["lock"] = None

    def force_unlock(self, confirm: Callable[[str], bool]) -> None:
        """Clears a lock this machine can't check (another machine's, or a dead local process) after confirm()."""
        held = self.state.read().get("lock")
        if not held:
            print("no step lock held")
            return
        if held["host"] == socket.gethostname() and self._alive(held["pid"]):
            raise StepRefused(f"{self._describe(held)}; that process is running on this machine, stop it instead")
        print(self._describe(held))
        # Asked outside the file lock, so a prompt left open doesn't block other commands.
        if not confirm("clear this step lock? [y/N] "):
            print("step lock kept")
            return
        with self.state.update() as data:
            if data.get("lock") != held:
                raise StepRefused("step lock changed while confirming; run --force-unlock again")
            data["lock"] = None
        self.run_log.warning(f"force-unlocked {self._describe(held)}")

    @staticmethod
    def _describe(held: dict[str, Any]) -> str:
        return f"step lock held by pid {held['pid']} on {held['host']} since {held['since']} ({held['command']})"

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, owned by another user
        return True
