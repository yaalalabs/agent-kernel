from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ak_bench.errors import ScriptFailed

if TYPE_CHECKING:
    from ak_bench.fetchers.core.stage_fetchers import StageFetchers  # runtime import would be circular via InfoFetcher


@dataclass(frozen=True)
class RunInfo:
    """The `run` argument of fetch(): who is running, never results."""

    run_id: str
    deployment_id: str  # "<run-id>-<host>-<mode>-<message-type>", also the cloud tag value
    host: str
    platform: str
    mode: str
    message_type: str


@dataclass
class Deployment:
    """Read from deployment.json, saved in state.json unchanged."""

    endpoint: str
    resources: dict[str, dict[str, Any]]
    queues: dict[str, dict[str, Any]]
    logs: dict[str, str]
    settings: dict[str, Any]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Deployment":
        if not isinstance(data, dict):
            raise ScriptFailed(f"deployment.json must be a JSON object, got {type(data).__name__}")
        missing = [key for key in ("endpoint", "resources", "queues", "logs", "settings") if key not in data]
        if missing:
            raise ScriptFailed(f"deployment.json is missing {', '.join(missing)}")
        return cls(data["endpoint"], data["resources"], data["queues"], data["logs"], data["settings"])

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Host:
    platform: str
    fetchers: "StageFetchers"
