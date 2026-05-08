import importlib.metadata
from typing import List, Optional

from pydantic import BaseModel, Field

from .model import ExecutionMode
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


class _CosmosDBConfig(BaseModel):
    connection_string: str = Field(description="Cosmos DB connection string. Can be found in Azure Portal under Keys section")
    table_name: str = Field(description="Cosmos DB table name for session storage. Table uses PartitionKey (session_id) and RowKey (key)")
    ttl: int = Field(
        default=604800,
        description="Session TTL in seconds (0 disables). Used for manual TTL management in Cosmos DB Table API.",
    )


class _SessionStoreConfig(BaseModel):
    type: str = Field(default="in_memory", pattern="^(in_memory|redis|dynamodb|cosmosdb)$")
    cache: Optional[_SessionCacheConfig] = None
    redis: Optional[_RedisConfig] = None
    dynamodb: Optional[_DynamoDBConfig] = None
    cosmosdb: Optional[_CosmosDBConfig] = None


class _RoutesConfig(BaseModel):
    agents: bool = Field(default=True, description="Agent interaction routes")


class _APIConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    enabled_routes: _RoutesConfig = Field(description="API route flags", default_factory=_RoutesConfig)
    custom_router_prefix: str = Field(default="/custom", description="Custom router prefix")
    max_file_size: int = Field(default=20971520, description="Maximum file size in bytes (default: 20 MB)")


class _WebSocketAPIConfig(BaseModel):
    endpoint_url: str = Field(default=None, description="WebSocket API endpoint URL")
    chat_route: str = Field(description="WebSocket chat route")
    connection_table: Optional[_DynamoDBConfig] = Field(default=None, description="DynamoDB configuration for storing WebSocket connections")


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


class _MultimodalStorageRedisConfig(BaseModel):
    url: str = Field(default="redis://localhost:6379", description="Redis connection URL")
    ttl: int = Field(default=604800, description="Attachment TTL in seconds")
    prefix: str = Field(default="ak:attachments:", description="Key prefix for attachment keys")


class _MultimodalStorageDynamoDBConfig(BaseModel):
    table_name: str = Field(default="ak-attachments", description="DynamoDB table name for attachment storage")
    ttl: int = Field(default=604800, description="Attachment TTL in seconds (0 disables)")


class _MultimodalConfig(BaseModel):
    """Configuration for multimodal attachment memory."""

    enabled: bool = Field(
        default=False,
        description="Enable multimodal memory for images and files.",
    )
    storage_type: str = Field(
        default="in_memory",
        pattern="^(session_cache|in_memory|redis|dynamodb)$",
        description="Storage backend for multimodal attachments. Options: session_cache, in_memory, redis, dynamodb",
    )
    max_attachments: int = Field(default=20, description="Maximum number of attachments to keep per session")
    description_max_length: int = Field(default=200, description="Maximum length of attachment description text")
    description_model: str = Field(
        default="gpt-4o",
        description="LiteLLM model used to generate brief descriptions when an attachment is first received (called by the pre-hook)",
    )
    analysis_model: str = Field(
        default="gpt-4o",
        description="LiteLLM model used by the analyze_attachments tool when the agent requests a full analysis of an attachment",
    )
    redis: Optional[_MultimodalStorageRedisConfig] = None
    dynamodb: Optional[_MultimodalStorageDynamoDBConfig] = None


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
    type: str = Field(default="openai", pattern="^(openai|bedrock|walledai)$")
    pii: bool = Field(default=True, description="Enable PII redaction/unmasking (WalledAI only)")
    config_path: Optional[str] = Field(default=None, description="Path to guardrail configuration file (OpenAI only)")
    model: Optional[str] = Field(default="gpt-4o-mini", description="LLM model name to use for guardrail (OpenAI only)")
    id: Optional[str] = Field(default=None, description="AWS Bedrock guardrail ID (Bedrock only)")
    version: Optional[str] = Field(default="DRAFT", description="AWS Bedrock guardrail version (Bedrock only)")


class _GuardrailConfig(BaseModel):
    input: _GuardrailParamConfig = Field(description="Input Guardrail configuration", default_factory=_GuardrailParamConfig)
    output: _GuardrailParamConfig = Field(description="Output Guardrail configuration", default_factory=_GuardrailParamConfig)


class _ResponseStoreRedisConfig(_RedisConfig):
    prefix: str = Field(default="ak:responses:", description="Key prefix for Redis response storage")


class _ResponseStoreDynamoDBConfig(_DynamoDBConfig):
    table_name: Optional[str] = Field(
        default=None,
        description="DynamoDB table name for session storage.",
    )


class _ResponseStoreConfig(BaseModel):
    type: str = Field(default=None, pattern="^(redis|dynamodb)$")
    retry_count: int = Field(default=5, description="Number of retry attempts for response store reads")
    delay: float = Field(default=5, description="Delay in seconds between response store reads retry attempts")
    redis: Optional[_ResponseStoreRedisConfig] = None
    dynamodb: Optional[_ResponseStoreDynamoDBConfig] = None


class _InputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Input SQS queue URL for async execution mode")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from input queue before being treated as permanently failed"
    )


class _OutputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Output SQS queue URL for async execution mode")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from output queue before being treated as permanently failed"
    )


class _QueuesConfig(BaseModel):
    input: _InputQueueConfig = Field(default_factory=_InputQueueConfig, description="Input SQS queue configuration for async execution mode")
    output: _OutputQueueConfig = Field(default_factory=_OutputQueueConfig, description="Output SQS queue configuration for async execution mode")


class _LogLevelConfig(BaseModel):
    level: Optional[str] = Field(
        default=None,
        pattern="^(INFO|DEBUG|ERROR|WARNING|CRITICAL)$",
        description="Log level. Options: INFO, DEBUG, ERROR, WARNING, CRITICAL",
    )


class _LoggingConfig(BaseModel):
    ak: _LogLevelConfig = Field(description="Agent Kernel logging configuration", default_factory=_LogLevelConfig)
    system: _LogLevelConfig = Field(description="System logging configuration", default_factory=_LogLevelConfig)


class _ExecutionConfig(BaseModel):
    mode: Optional[ExecutionMode] = Field(
        default=None,
        description="Execution mode: rest_sync for synchronous REST, rest_async for asynchronous REST",
    )
    queues: Optional[_QueuesConfig] = Field(default_factory=_QueuesConfig, description="Queue URLs for async execution mode")
    response_store: Optional[_ResponseStoreConfig] = Field(
        default=None,
        description="Response storage configuration for async execution mode",
    )


class AKConfig(YamlBaseSettingsModified):
    session: _SessionStoreConfig = Field(
        description="Agent session / memory related configurations",
        default_factory=_SessionStoreConfig,
    )
    api: _APIConfig = Field(description="REST API related configurations", default_factory=_APIConfig)
    websocket_api: _WebSocketAPIConfig = Field(description="WebSocket API related configurations", default_factory=_WebSocketAPIConfig)
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
    multimodal: _MultimodalConfig = Field(description="Multimodal attachment memory configurations", default_factory=_MultimodalConfig)

    trace: _TraceConfig = Field(description="Tracing related configurations", default_factory=_TraceConfig)
    test: _TestConfig = Field(description="Test related configurations", default_factory=_TestConfig)
    guardrail: _GuardrailConfig = Field(description="Guardrail related configurations", default_factory=_GuardrailConfig)
    execution: _ExecutionConfig = Field(description="Execution mode and queue related configurations", default_factory=_ExecutionConfig)
    logging: _LoggingConfig = Field(description="Logging related configurations", default_factory=_LoggingConfig)
    library_version: str = Field(default=_get_ak_version(), description="Library version")

    @classmethod
    def get(cls) -> "AKConfig":
        return globals()["ak_config"]

    @classmethod
    def _set(cls):
        globals()["ak_config"] = AKConfig()


AKConfig._set()
