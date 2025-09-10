import json
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class _RedisConfig(BaseModel):
    url: str = "redis://localhost:6379"
    ttl: int = 604800
    prefix: str = "ak:sessions:"


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

    @classmethod
    def load(cls, config_path: str = 'config.yaml') -> 'AKConfig':
        file_data = {}
        if config_path:
            path = Path(config_path)
            if path.suffix in [".yaml", ".yml"]:
                file_data = yaml.safe_load(path.read_text()) or {}
            elif path.suffix == ".json":
                file_data = json.loads(path.read_text())
            else:
                raise ValueError("Unsupported config format: must be YAML or JSON")
        return cls(**file_data)


load = AKConfig.load()

a = 1
