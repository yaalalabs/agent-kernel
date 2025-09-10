import json
import os
from pathlib import Path
from typing import Optional, List, Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class _RedisConfig(BaseModel):
    url: str = Field(default="redis://localhost:6379", description="Redis connection URL. Use rediss:// for SSL")
    ttl: int = Field(default=604800, description="Redis saved value TTL in seconds")
    prefix: str = Field(default="ak:sessions:", description="Key prefix for Redis session storage")


class _SessionStoreConfig(BaseModel):
    type: str = Field("in_memory", pattern="^(in_memory|redis)$")
    redis: Optional[_RedisConfig] = _RedisConfig()


class AKConfig(BaseSettings):
    debug: bool = Field(default=False, description="Enable debug mode")
    session: _SessionStoreConfig = Field(default_factory=_SessionStoreConfig)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "_"
        env_prefix = "AK_"
        extra = "ignore"  # ignore extra fields

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "AKConfig":
        """
        Load configuration from an optional file and environment variables.
        Precedence (highest to lowest):
        1) Environment variables (including .env)
        2) File values (YAML/JSON)
        3) Defaults defined in the model
        :param config_path: Path to the configuration file.
        """
        file_data = {}
        if config_path:
            path = Path(config_path)
            if path.exists():
                if path.suffix in (".yaml", ".yml"):
                    file_data = yaml.safe_load(path.read_text()) or {}
                elif path.suffix == ".json":
                    file_data = json.loads(path.read_text())
                else:
                    raise ValueError("Unsupported config format: must be YAML or JSON")

        file_instance = cls.model_validate(file_data or {})  # applies defaults
        file_dict = file_instance.model_dump()

        # build environment configs
        prefix = getattr(cls.Config, "env_prefix", "") or ""
        nested_delim = getattr(cls.Config, "env_nested_delimiter", "_") or "_"

        def set_deep(d: dict, keys: List[Any], value: Any):
            """
            Sets a value deeply in a nested dictionary, creating nested dictionaries as
            necessary based on the provided keys.
            :param d: The dictionary to modify.
            :param keys: A list of keys that define the hierarchical structure within
                the dictionary where the value should be set.
            :param value: The value to set at the specified location in the nested dictionary.
            """
            cur = d
            for k1 in keys[:-1]:
                if k1 not in cur or not isinstance(cur[k1], dict):
                    cur[k1] = {}
                cur = cur[k1]
            cur[keys[-1]] = value

        env_dict = {}  # dict of env defined variables. This required because there's no other way to get the environment variables into the structure
        prefix_length = len(prefix)
        for k, v in os.environ.items():
            if prefix and not k.startswith(prefix):
                continue
            if prefix:
                key = k[prefix_length:]
            else:
                key = k
            # Skip the empty key
            if not key:
                continue
            # Split by nested delimiter to create a nested structure
            parts = [p.lower() for p in key.split(nested_delim) if p]
            if not parts:
                continue
            set_deep(env_dict, parts, v)

        # Merge with env overriding file values (env > file > defaults)
        def deep_merge(base, overlay) -> dict:
            """
            Recursively merges two dictionaries or values
            preferring the overlay value when present.
            :param base: The base dictionary or value to merge.
            :param overlay: The overlay dictionary or value to merge, which takes precedence.
            :return: The deeply merged dictionary or value, prioritizing the overlay input.
            """
            if isinstance(base, dict) and isinstance(overlay, dict):
                result = dict(base)
                for k1, v1 in overlay.items():
                    if k1 in result:
                        result[k1] = deep_merge(result[k1], v1)
                    else:
                        result[k1] = v1
                return result
            # Prefer overlay (env) when provided, otherwise keep base (file)
            return overlay if overlay is not None else base

        merged = deep_merge(file_dict, env_dict)
        return cls.model_validate(obj=merged)
