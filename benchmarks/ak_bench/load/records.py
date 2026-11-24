from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class RequestStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class RequestRecord:
    """One request's timestamps: wall clock for windows, monotonic for durations."""

    request_id: str
    session_id: str
    user_id: str
    scheduled_send: datetime
    sent: datetime | None = None
    first_chunk: datetime | None = None
    complete: datetime | None = None
    status: RequestStatus | None = None  # None while pending
    sent_mono: float | None = None
    first_chunk_mono: float | None = None
    complete_mono: float | None = None
    settled_mono: float | None = None  # when status was set
    settled: datetime | None = None  # wall time of settled_mono (error / timeout time for the windows)
    error: str | None = None

    @property
    def latency_s(self) -> float | None:
        if self.status != RequestStatus.OK or self.sent_mono is None or self.complete_mono is None:
            return None
        return self.complete_mono - self.sent_mono


@dataclass(frozen=True)
class ResponseEvent:
    request_id: str
    kind: Literal["first_chunk", "complete", "error"]
    wall: datetime
    mono: float
    detail: str | None = None
