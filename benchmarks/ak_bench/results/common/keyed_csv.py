import csv
import json
import os
import threading
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar


class KeyedCsv:
    """A CSV file whose rows are upserted by key; thread-safe within the process."""

    _locks: ClassVar[dict[Path, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, path: Path, columns: list[str], key: list[str]):
        self.path = Path(path)
        self.columns = columns
        self.key = key

    @staticmethod
    def cell(value: Any) -> str:
        """Datetimes as ISO 8601 UTC with milliseconds and Z, None as empty, dicts as compact JSON."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if isinstance(value, dict):
            return json.dumps(value, sort_keys=True, separators=(",", ":"))
        return str(value)

    def upsert(self, rows: Iterable[dict[str, Any]]) -> None:
        """Read, replace or append each row by key, write a temp file, then os.replace."""
        new = [{c: self.cell(row.get(c)) for c in self.columns} for row in rows]
        if not new:
            return
        with self._lock():
            merged = {self._key_of(row): row for row in self.read()}
            for row in new:
                merged[self._key_of(row)] = row  # dict keeps first-insert order on replace
            self._write(merged.values())

    def read(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open(newline="") as f:
            return list(csv.DictReader(f))

    def series(self, key: Callable[[dict[str, str]], Hashable], value: Callable[[dict[str, str]], Any]) -> dict[Any, list[tuple[datetime, Any]]]:
        """A long-form file with a `ts` column as {key(row): [(ts, value(row))]}, in file order."""
        out: dict[Any, list[tuple[datetime, Any]]] = defaultdict(list)
        for row in self.read():
            out[key(row)].append((self.parse_ts(row["ts"]), value(row)))
        return out

    @staticmethod
    def parse_ts(cell: str) -> datetime | None:
        """Reads back a datetime written by cell()."""
        return datetime.fromisoformat(cell) if cell else None

    def _write(self, rows: Iterable[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, self.path)

    def _key_of(self, row: dict[str, str]) -> tuple[str, ...]:
        return tuple(row.get(k, "") for k in self.key)

    def _lock(self) -> threading.Lock:
        path = self.path.resolve()
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())
