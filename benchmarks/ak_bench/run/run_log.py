import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from ak_bench.results.common.keyed_csv import KeyedCsv

_logger = logging.getLogger("ak_bench")


class RunLog:
    """results/<run-id>/run.log: one appended line per entry, also echoed through the ak_bench logger."""

    def __init__(self, path: Path, command: str):
        self.path = Path(path)
        self.command = command
        self._lock = threading.Lock()

    def info(self, message: str) -> None:
        self._write(logging.INFO, message)

    def warning(self, message: str) -> None:
        self._write(logging.WARNING, message)

    def error(self, message: str) -> None:
        self._write(logging.ERROR, message)

    def _write(self, level: int, message: str) -> None:
        line = f"{KeyedCsv.cell(datetime.now(UTC))} {logging.getLevelName(level)} {self.command} {message}\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(line)
        _logger.log(level, "%s %s", self.command, message)
