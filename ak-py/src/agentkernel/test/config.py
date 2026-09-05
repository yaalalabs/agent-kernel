from threading import RLock
from typing import ClassVar, Optional

from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from agentkernel.core.util.config_yaml_util import YamlBaseSettingsModified


class _LlmConfig(BaseModel):
    model: str = Field(default="gpt-4o-mini", description="LLM Model name")
    provider: str = Field(default="openai", description="LLM Provider name")
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding Model name")


class AKTestConfig(YamlBaseSettingsModified):
    """Test harness configuration, kept separate from the application AKConfig.

    Loaded from test-config.yaml in the current working directory (override the
    path with AK_TEST_CONFIG_PATH_OVERRIDE). A missing file is the normal case
    and applies the defaults silently. Environment variables use the same names
    as before the split (AK_TEST__MODE, AK_TEST__LLM__MODEL, ...).
    """

    yaml_file_env_var: ClassVar[str] = "AK_TEST_CONFIG_PATH_OVERRIDE"
    yaml_file_default: ClassVar[str] = "test-config.yaml"
    warn_if_missing: ClassVar[bool] = False

    _instance: ClassVar[Optional["AKTestConfig"]] = None
    _instance_lock: ClassVar[RLock] = RLock()

    mode: str = Field(default="fallback", pattern="^(fallback|llm|score)$")
    evaluator: str = Field(
        default="deepeval",
        description="Built-in evaluator short name ('deepeval' or 'opik') or a dotted path to an AKEvaluator subclass",
    )
    llm: _LlmConfig = Field(description="LLM configuration for the llm evaluation mode", default_factory=_LlmConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="AK_TEST__",
        extra="ignore",
        env_ignore_empty=True,
    )

    @classmethod
    def get(cls) -> "AKTestConfig":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = AKTestConfig()
        return cls._instance

    @classmethod
    def _reset(cls):
        """Clear the cached singleton so the next get() reloads the config."""
        cls._instance = None
