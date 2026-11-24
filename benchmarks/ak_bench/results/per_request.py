from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from agentkernel.core import TraceStage

from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.records import RequestRecord
from ak_bench.results.keyed_csv import KeyedCsv

REQUEST_PATH_STAGES = [s for s in TraceStage if s not in (TraceStage.RESPONSE_POLL_START, TraceStage.RESPONSE_FOUND)]
CLIENT_RECEIVED = "CLIENT_RECEIVED"
DURATION_STAGES = [*(s.value for s in REQUEST_PATH_STAGES), CLIENT_RECEIVED]  # the <STAGE>_s columns, in order


class PerRequestWriter:
    """Joins the client records to stage-timestamps.csv by request id and writes per-request.csv."""

    COLUMNS: ClassVar[list[str]] = [
        "request_id",
        "session_id",
        "user_id",
        "scheduled_send",
        "sent",
        "first_chunk",
        "complete",
        "latency_s",
        "status",
        *(f"{s}_ts" for s in REQUEST_PATH_STAGES),
        *(f"{s}_s" for s in DURATION_STAGES),
    ]

    def __init__(self, driver_cls: type[ClientDriver]):
        self.chain = driver_cls.trace_stages

    def write(self, step_dir: Path, records: list[RequestRecord]) -> list[dict[str, Any]]:
        """Writes per-request.csv and returns its rows (datetimes and floats, not CSV cells)."""
        stages: dict[str, dict[str, datetime]] = defaultdict(dict)
        for row in KeyedCsv(step_dir / "stage-timestamps.csv", [], []).read():
            stages[row["request_id"]][row["stage"]] = KeyedCsv.parse_ts(row["ts"])
        rows = [self._row(r, stages.get(r.request_id, {})) for r in records]
        KeyedCsv(step_dir / "per-request.csv", self.COLUMNS, ["request_id"]).upsert(rows)
        return rows

    def _row(self, r: RequestRecord, ts: dict[str, datetime]) -> dict[str, Any]:
        row = {
            "request_id": r.request_id,
            "session_id": r.session_id,
            "user_id": r.user_id,
            "scheduled_send": r.scheduled_send,
            "sent": r.sent,
            "first_chunk": r.first_chunk,
            "complete": r.complete,
            "latency_s": r.latency_s,
            "status": r.status,
            **{f"{s}_ts": ts.get(s) for s in REQUEST_PATH_STAGES},
            **{f"{s}_s": None for s in DURATION_STAGES},
        }
        # Each duration is previous point -> this point along [client sent] + the driver's stages + [client complete]
        points = [r.sent, *(ts.get(s) for s in self.chain), r.complete]
        names = [*self.chain, CLIENT_RECEIVED]
        for name, before, after in zip(names, points, points[1:], strict=False):
            if before is not None and after is not None:
                row[f"{name}_s"] = (after - before).total_seconds()
        return row
