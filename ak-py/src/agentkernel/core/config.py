import importlib.metadata
from typing import List, Optional

from pydantic import BaseModel, Field

from .util.config_yaml_util import YamlBaseSettingsModified


def _get_ak_version() -> str:
    try:
        return importlib.metadata.version("agentkernel")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


class _RedisConfig(BaseModel):
    url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL. Use rediss:// for SSL",
    )
    ttl: int = Field(default=604800, description="Redis saved value TTL in seconds")
    prefix: str = Field(default="ak:sessions:", description="Key prefix for Redis session storage")


class _SessionStoreConfig(BaseModel):
    type: str = Field(default="in_memory", pattern="^(in_memory|redis)$")
    redis: Optional[_RedisConfig] = None


class _RoutesConfig(BaseModel):
    agents: bool = Field(default=True, description="Agent interaction routes")


class _APIConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    enabled_routes: _RoutesConfig = Field(description="API route flags", default_factory=_RoutesConfig)
    custom_router_prefix: str = Field(default="/custom", description="Custom router prefix")


class _A2AConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable A2A")
    agents: List[str] = Field(default=["*"], description="List of agent names to enable A2A")
    url: str = Field(default="http://localhost:8000/a2a", description="A2A URL")
    task_store_type: str = Field(default="in_memory", pattern="^(in_memory|redis)$")


class _MCPConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable MCP")
    expose_agents: bool = Field(default=False, description="Expose agents as MCP tools")
    agents: List[str] = Field(default=["*"], description="List of agent names to expose as MCP tool")
    url: str = Field(default="http://localhost:8000/mcp", description="MCP URL")


class _SlackConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Slack interactions")
    agent_acknowledgement: str = Field(
        default="",
        description="The message to send as an acknowledgement when a Slack message is received",
    )


class AKConfig(YamlBaseSettingsModified):
    debug: bool = Field(default=False, description="Enable debug mode")
    session: _SessionStoreConfig = Field(
        description="Agent session / memory related configurations",
        default_factory=_SessionStoreConfig,
    )
    api: _APIConfig = Field(description="REST API related configurations", default_factory=_APIConfig)
    a2a: _A2AConfig = Field(description="Agent to Agent related configurations", default_factory=_A2AConfig)
    mcp: _MCPConfig = Field(
        description="Model Context Protocol related configurations",
        default_factory=_MCPConfig,
    )
    slack: _SlackConfig = Field(description="Slack related configurations", default_factory=_SlackConfig)
    library_version: str = Field(default=_get_ak_version(), description="Library version")

    @classmethod
    def get(cls) -> "AKConfig":
        return globals()["ak_config"]

    @classmethod
    def _set(cls):
        globals()["ak_config"] = AKConfig()


AKConfig._set()
