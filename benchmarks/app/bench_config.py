"""BenchAppConfig: the benchmarked app's own settings, kept separate from AKConfig (same pattern as AKTestConfig)."""

from threading import RLock
from typing import ClassVar, Optional

from agentkernel.core.util.config_yaml_util import YamlBaseSettingsModified
from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict


class BenchAppConfig(YamlBaseSettingsModified):
    """Loaded from bench-config.yaml in the current working directory (override the path with
    AK_BENCH_CONFIG_PATH_OVERRIDE) and `AK_BENCH_`-prefixed environment variables; the deployment folders set
    the environment variables, so a missing file is the normal case.
    """

    yaml_file_env_var: ClassVar[str] = "AK_BENCH_CONFIG_PATH_OVERRIDE"
    yaml_file_default: ClassVar[str] = "bench-config.yaml"
    warn_if_missing: ClassVar[bool] = False

    _instance: ClassVar[Optional["BenchAppConfig"]] = None
    _instance_lock: ClassVar[RLock] = RLock()

    mock_agent_min_delay_s: float | None = Field(default=None, ge=0, description="Mock agent minimum delay; env AK_BENCH_MOCK_AGENT_MIN_DELAY_S")
    mock_agent_max_delay_s: float | None = Field(default=None, ge=0, description="Mock agent maximum delay; env AK_BENCH_MOCK_AGENT_MAX_DELAY_S")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AK_BENCH_",
        extra="ignore",
        env_ignore_empty=True,
    )

    @model_validator(mode="after")
    def _check_mock_delays(self) -> "BenchAppConfig":
        low, high = self.mock_agent_min_delay_s, self.mock_agent_max_delay_s
        # A half-configured mock is a broken deployment, never a silent fall-back to the real (billed) agent.
        if (low is None) != (high is None):
            raise ValueError("set both mock_agent_min_delay_s and mock_agent_max_delay_s for the mock agent, or neither for the real agent")
        if low is not None and low > high:
            raise ValueError(f"mock_agent_min_delay_s ({low}) is greater than mock_agent_max_delay_s ({high})")
        return self

    @property
    def mock_delays(self) -> tuple[float, float] | None:
        """(min, max) seconds when the mock agent is configured, else None (the real agent runs)."""
        return None if self.mock_agent_min_delay_s is None else (self.mock_agent_min_delay_s, self.mock_agent_max_delay_s)

    @classmethod
    def get(cls) -> "BenchAppConfig":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = BenchAppConfig()
        return cls._instance

    @classmethod
    def _reset(cls):
        """Clear the cached singleton so the next get() reloads the config."""
        cls._instance = None
