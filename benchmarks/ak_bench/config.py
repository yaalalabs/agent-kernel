import os
from pathlib import Path
from threading import RLock
from typing import ClassVar, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from ak_bench.errors import BenchConfigError


class StepRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before_window_s: float = 60
    max_cooldown_s: float = 2700
    after_step_wait_s: float = 60
    client_timeout_s: float = 300
    time_window_s: float
    cooldown_poll_interval_s: float = 10
    cooldown_lookback_s: float = 180


class SteadyTrafficConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_send_interval_s: float = 1
    max_send_interval_s: float = 5
    load_time_s: float = Field(default=300, gt=0)

    @model_validator(mode="after")
    def _check_intervals(self) -> "SteadyTrafficConfig":
        if not 0 < self.min_send_interval_s <= self.max_send_interval_s:
            raise ValueError("need 0 < min_send_interval_s <= max_send_interval_s")
        return self


class FetcherSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poll_interval_s: float = Field(gt=0)


class FetchersConfig(RootModel[dict[str, FetcherSettings]]):
    @field_validator("root")
    @classmethod
    def _require_default(cls, value: dict[str, FetcherSettings]) -> dict[str, FetcherSettings]:
        if "default" not in value:
            raise ValueError("fetchers.default.poll_interval_s is required")
        return value

    def poll_interval_for(self, name: str) -> float:
        return self.root.get(name, self.root["default"]).poll_interval_s

    def check_names(self, known: set[str]) -> None:
        for name in self.root:
            if name != "default" and name not in known:
                raise BenchConfigError(f"fetchers.{name}: no fetcher of the selected hosts has this name; known: {', '.join(sorted(known))}")


class HostSettings(BaseModel):
    # Host-specific keys (e.g. lambda_insights) are passed to deploy.sh as JSON.
    model_config = ConfigDict(extra="allow")

    max_cooldown_s: float | None = None


class MockAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_delay: float | None = None
    max_delay: float | None = None

    def delays(self) -> tuple[float, float] | None:
        """(min, max) for the mock agent, None for the real agent. Checked here, not by Pydantic, because it is a deploy refusal."""
        if self.min_delay is None and self.max_delay is None:
            return None
        for key in ("min_delay", "max_delay"):
            value = getattr(self, key)
            if value is None:
                raise BenchConfigError(f"mock_agent.{key} is missing; set both min_delay and max_delay, or neither for the real agent")
            if value < 0:
                raise BenchConfigError(f"mock_agent.{key} must not be negative (got {value})")
        if self.min_delay > self.max_delay:
            raise BenchConfigError(f"mock_agent.min_delay ({self.min_delay}) is greater than mock_agent.max_delay ({self.max_delay})")
        return self.min_delay, self.max_delay


class BenchConfig(BaseSettings):
    """Loaded like AKConfig (without AK's internal loader): ak-bench.yaml in the working directory (path override
    AK_BENCH_CONFIG_PATH_OVERRIDE, which `--config` sets) and `AK_BENCH_`-prefixed environment variables, nested keys joined with `__`
    (e.g. AK_BENCH_STEP_RUN__TIME_WINDOW_S). Read it with BenchConfig.get().
    """

    yaml_file_env_var: ClassVar[str] = "AK_BENCH_CONFIG_PATH_OVERRIDE"
    yaml_file_default: ClassVar[str] = "ak-bench.yaml"

    _instance: ClassVar[Optional["BenchConfig"]] = None
    _instance_lock: ClassVar[RLock] = RLock()

    model_config = SettingsConfigDict(
        yaml_file_encoding="utf-8", env_prefix="AK_BENCH_", env_nested_delimiter="__", extra="forbid", env_ignore_empty=True
    )

    hosts: list[str] | None = None
    modes: list[str] | None = None
    message_types: list[str] | None = None
    test_types: list[Literal["steady", "burst"]] = Field(default_factory=lambda: ["steady", "burst"])
    load_steps: list[int] = Field(default=[1, 10, 100, 1000], min_length=1)
    step_run: StepRunConfig
    steady_traffic: SteadyTrafficConfig = SteadyTrafficConfig()
    fetchers: FetchersConfig
    host_settings: dict[str, HostSettings] = Field(default_factory=dict)
    mock_agent: MockAgentConfig | None = None

    @classmethod
    def _path(cls) -> Path:
        return Path(os.environ.get(cls.yaml_file_env_var, cls.yaml_file_default))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Environment variables override the file, as in AKConfig.
        return init_settings, env_settings, YamlConfigSettingsSource(settings_cls, yaml_file=cls._path())

    @field_validator("load_steps")
    @classmethod
    def _check_load_steps(cls, value: list[int]) -> list[int]:
        if any(step < 1 for step in value):
            raise ValueError("every load step must be >= 1")
        if len(set(value)) != len(value):
            raise ValueError("load steps must not repeat")
        return value

    def max_cooldown_for(self, host: str) -> float:
        settings = self.host_settings.get(host)
        if settings is not None and settings.max_cooldown_s is not None:
            return settings.max_cooldown_s
        return self.step_run.max_cooldown_s

    @classmethod
    def get(cls) -> "BenchConfig":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls._load()
        return cls._instance

    @classmethod
    def _reset(cls):
        """Clear the cached singleton so the next get() reloads the config."""
        cls._instance = None

    @classmethod
    def _load(cls) -> "BenchConfig":
        path = cls._path()
        if path.exists() and not path.is_file():  # pydantic's YAML source would silently read it as empty
            raise BenchConfigError(f"can't read config file {path}: not a file")
        try:
            # Named up front so the message says "unknown key" rather than pydantic's "extra inputs".
            unknown = sorted(set(YamlConfigSettingsSource(cls, yaml_file=path)()) - set(cls.model_fields))
            if unknown:
                raise BenchConfigError(f"{path}: unknown key(s): {', '.join(unknown)}")
            return cls()
        except ValidationError as e:
            if not path.exists():
                raise BenchConfigError(f"config file not found: {path}") from None
            raise BenchConfigError(f"{path}: {e}") from None
        except yaml.YAMLError as e:
            raise BenchConfigError(f"{path}: invalid YAML: {e}") from None
        except (OSError, ValueError) as e:  # ValueError: the top level isn't a mapping
            raise BenchConfigError(f"can't read config file {path}: {e}") from None
