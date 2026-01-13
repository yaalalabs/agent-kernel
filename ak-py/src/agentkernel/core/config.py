import importlib.metadata
from typing import List, Optional

from pydantic import BaseModel, Field

from .util.config_yaml_util import YamlBaseSettingsModified


def _get_ak_version() -> str:
    try:
        return importlib.metadata.version("agentkernel")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


class _SessionCacheConfig(BaseModel):
    size: int = Field(default=256, description="Maximum number of sessions to cache in memory")


class _RedisConfig(BaseModel):
    url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL. Use rediss:// for SSL",
    )
    ttl: int = Field(default=604800, description="Redis saved value TTL in seconds")
    prefix: str = Field(default="ak:sessions:", description="Key prefix for Redis session storage")


class _DynamoDBConfig(BaseModel):
    table_name: str = Field(
        description="DynamoDB table name for session storage. Table should have a partition key named 'session_id' and a sort key named 'key'"
    )
    ttl: int = Field(
        default=604800,
        description="DynamoDB item TTL in seconds (0 disables). Used to compute UNIX epoch 'expiry_time' attribute written per item.",
    )


class _SessionStoreConfig(BaseModel):
    type: str = Field(default="in_memory", pattern="^(in_memory|redis|dynamodb)$")
    cache: Optional[_SessionCacheConfig] = None
    redis: Optional[_RedisConfig] = None
    dynamodb: Optional[_DynamoDBConfig] = None


class _RoutesConfig(BaseModel):
    agents: bool = Field(default=True, description="Agent interaction routes")


class _APIConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    enabled_routes: _RoutesConfig = Field(description="API route flags", default_factory=_RoutesConfig)
    custom_router_prefix: str = Field(default="/custom", description="Custom router prefix")
    max_file_size: int = Field(default=2097152, description="Maximum file size in bytes (default: 2 MB)")


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


class _WhatsAppConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for WhatsApp interactions")
    agent_acknowledgement: str = Field(
        default="",
        description="The message to send as an acknowledgement when a WhatsApp message is received",
    )
    verify_token: str = Field(default="", description="WhatsApp webhook verify token")
    access_token: str = Field(default="", description="WhatsApp Business API access token")
    app_secret: str = Field(default="", description="WhatsApp app secret for signature verification")
    phone_number_id: str = Field(default="", description="WhatsApp Business phone number ID")
    api_version: str = Field(default="v24.0", description="WhatsApp API version")


class _MessengerConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Facebook Messenger interactions")
    verify_token: str = Field(default="", description="Facebook Messenger webhook verify token")
    access_token: str = Field(default="", description="Facebook Page access token")
    app_secret: str = Field(default="", description="Facebook app secret for signature verification")
    api_version: str = Field(default="v24.0", description="Facebook Graph API version")


class _InstagramConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Instagram interactions")
    verify_token: str = Field(default="", description="Instagram webhook verify token")
    access_token: str = Field(default="", description="Instagram Business access token")
    app_secret: str = Field(default="", description="Instagram app secret for signature verification")
    instagram_account_id: str = Field(default="", description="Instagram Business Account ID (IGSID)")
    api_version: str = Field(default="v21.0", description="Instagram Graph API version")


class _TelegramConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Telegram")
    bot_token: str = Field(default="", description="Telegram bot token from BotFather")
    webhook_secret: str = Field(default="", description="Optional secret token for webhook security")
    api_version: str = Field(default="bot", description="Telegram Bot API version prefix")


class _GmailConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Gmail")
    token_file: str = Field(default="token.pickle", description="Path to store OAuth2 token")
    poll_interval: int = Field(default=30, description="Email polling interval in seconds")
    label_filter: str = Field(default="INBOX", description="Gmail label to monitor (e.g., INBOX, UNREAD)")


class _TraceConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable tracing")
    type: str = Field(default="langfuse", pattern="^(langfuse|openllmetry)$")


class _JudgeConfig(BaseModel):
    model: str = Field(default="gpt-4o-mini", description="LLM Model name")
    provider: str = Field(default="openai", description="LLM Provider name")
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding Model name")


class _TestConfig(BaseModel):
    mode: str = Field(default="fallback", pattern="^(fallback|judge|fuzzy)$")
    judge: _JudgeConfig = Field(description="Judge configuration", default_factory=_JudgeConfig)


class _GuardrailParamConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable Guardrail")
    type: str = Field(default="openai", pattern="^(openai|bedrock)$")
    config_path: Optional[str] = Field(default=None, description="Path to guardrail configuration file (OpenAI only)")
    model: Optional[str] = Field(default="gpt-4o-mini", description="LLM model name to use for guardrail (OpenAI only)")
    id: Optional[str] = Field(default=None, description="AWS Bedrock guardrail ID (Bedrock only)")
    version: Optional[str] = Field(default="DRAFT", description="AWS Bedrock guardrail version (Bedrock only)")


class _GuardrailConfig(BaseModel):
    input: _GuardrailParamConfig = Field(description="Input Guardrail configuration", default_factory=_GuardrailParamConfig)
    output: _GuardrailParamConfig = Field(description="Output Guardrail configuration", default_factory=_GuardrailParamConfig)


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
    whatsapp: _WhatsAppConfig = Field(description="WhatsApp related configurations", default_factory=_WhatsAppConfig)
    messenger: _MessengerConfig = Field(description="Facebook Messenger related configurations", default_factory=_MessengerConfig)
    instagram: _InstagramConfig = Field(description="Instagram Business API related configurations", default_factory=_InstagramConfig)
    telegram: _TelegramConfig = Field(description="Telegram Bot related configurations", default_factory=_TelegramConfig)
    gmail: _GmailConfig = Field(description="Gmail related configurations", default_factory=_GmailConfig)

    trace: _TraceConfig = Field(description="Tracing related configurations", default_factory=_TraceConfig)
    test: _TestConfig = Field(description="Test related configurations", default_factory=_TestConfig)
    guardrail: _GuardrailConfig = Field(description="Guardrail related configurations", default_factory=_GuardrailConfig)
    library_version: str = Field(default=_get_ak_version(), description="Library version")

    @classmethod
    def get(cls) -> "AKConfig":
        return globals()["ak_config"]

    @classmethod
    def _set(cls):
        globals()["ak_config"] = AKConfig()


AKConfig._set()
