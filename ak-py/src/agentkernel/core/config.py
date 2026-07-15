import importlib.metadata
from threading import RLock
from typing import ClassVar, List, Optional

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


class _ValkeyConfig(BaseModel):
    url: str = Field(
        default="valkey://localhost:6379",
        description="Valkey connection URL. Use valkeys:// for SSL",
    )
    ttl: int = Field(default=604800, description="Valkey saved value TTL in seconds")
    prefix: str = Field(default="ak:sessions:", description="Key prefix for Valkey session storage")


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


class _FirestoreConfig(BaseModel):
    collection_name: str = Field(
        default="ak_sessions",
        description="Firestore collection name for session storage. Each document ID is a session_id.",
    )
    project_id: Optional[str] = Field(
        default=None,
        description="GCP project ID. If null, inferred from Application Default Credentials.",
    )
    database_id: Optional[str] = Field(
        default=None,
        description="Firestore database ID. If null, defaults to '(default)' database for backward compatibility.",
    )
    ttl: int = Field(
        default=604800,
        description="Session TTL in seconds (0 disables). Sets an 'expiry_time' field on each document. "
        "Requires a Firestore TTL policy configured on the collection pointing to 'expiry_time'.",
    )


class _SessionStoreConfig(BaseModel):
    type: str = Field(default="in_memory", pattern="^(in_memory|redis|valkey|dynamodb|cosmosdb|firestore)$")
    cache: Optional[_SessionCacheConfig] = None
    redis: Optional[_RedisConfig] = None
    valkey: Optional[_ValkeyConfig] = None
    dynamodb: Optional[_DynamoDBConfig] = None
    cosmosdb: Optional[_CosmosDBConfig] = None
    firestore: Optional[_FirestoreConfig] = None


class _RoutesConfig(BaseModel):
    agents: bool = Field(default=True, description="Agent interaction routes")


class _APIConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    enabled_routes: _RoutesConfig = Field(description="API route flags", default_factory=_RoutesConfig)
    custom_router_prefix: str = Field(default="/custom", description="Custom router prefix")
    max_file_size: int = Field(default=10485760, description="Maximum file size in bytes (default: 10 MB)")


class _WebSocketAPIConfig(BaseModel):
    endpoint_url: Optional[str] = Field(default=None, description="WebSocket API endpoint URL")
    chat_route: Optional[str] = Field(default=None, description="WebSocket chat route")
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
    stateless_http: bool = Field(
        default=False,
        description="Run MCP in stateless HTTP mode. Each request is independent (no Mcp-Session-Id). "
        "Useful for debugging with MCP Inspector and clients that don't support sessions. "
        "Trade-off: server-side session features (sampling, mid-call notifications) are unavailable.",
    )


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


class _ThreadRedisConfig(BaseModel):
    url: str = Field(default="redis://localhost:6379", description="Redis connection URL. Use rediss:// for SSL")
    ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
    prefix: str = Field(default="ak:thread:", description="Key prefix for Redis thread storage")


class _ThreadDynamoDBConfig(BaseModel):
    table_name: str = Field(
        default="ak-agent-threads",
        description="DynamoDB table name for thread storage. Table should have a partition key named 'session_id' (S) and a sort key named 'sk' (S)",
    )
    ttl: int = Field(default=0, description="DynamoDB item TTL in seconds (0 disables)")


class _ThreadFirestoreConfig(BaseModel):
    collection_name: str = Field(
        default="ak-agent-threads",
        description="Firestore collection name for thread storage. Each document ID is a session_id.",
    )
    project_id: Optional[str] = Field(default=None, description="GCP project ID. If null, inferred from Application Default Credentials.")
    database_id: Optional[str] = Field(default=None, description="Firestore database ID. If null, defaults to '(default)' database.")
    ttl: int = Field(default=0, description="Thread TTL in seconds (0 disables)")


class _ThreadCosmosDBConfig(BaseModel):
    connection_string: str = Field(description="Cosmos DB connection string. Can be found in Azure Portal under Keys section")
    table_name: str = Field(default="akagentthreads", description="Cosmos DB table name for thread storage")


class _ThreadNamingConfig(BaseModel):
    model: str = Field(default="gpt-4o-mini", description="LiteLLM model used to generate thread names")
    max_length: int = Field(default=80, description="Maximum length of an auto-generated thread name")


class _ThreadStoreConfig(BaseModel):
    """Configuration for Conversation Thread Support. Presence of this block enables the feature."""

    type: str = Field(default="memory", pattern="^(memory|redis|dynamodb|cosmosdb|firestore)$")
    naming: _ThreadNamingConfig = Field(default_factory=_ThreadNamingConfig, description="Auto-naming settings for the built-in naming strategies")
    redis: Optional[_ThreadRedisConfig] = None
    dynamodb: Optional[_ThreadDynamoDBConfig] = None
    firestore: Optional[_ThreadFirestoreConfig] = None
    cosmosdb: Optional[_ThreadCosmosDBConfig] = None


class _TraceConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable tracing")
    type: str = Field(default="langfuse", pattern="^(langfuse|openllmetry)$")


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


class _ResponseStoreValkeyConfig(_ValkeyConfig):
    prefix: str = Field(default="ak:responses:", description="Key prefix for Valkey response storage")


class _ResponseStoreDynamoDBConfig(_DynamoDBConfig):
    table_name: Optional[str] = Field(
        default=None,
        description="DynamoDB table name for session storage.",
    )


class _ResponseStoreConfig(BaseModel):
    type: str = Field(default=None, pattern="^(redis|valkey|dynamodb)$")
    retry_count: int = Field(default=5, description="Number of retry attempts for response store reads")
    delay: float = Field(default=5, description="Delay in seconds between response store reads retry attempts")
    redis: Optional[_ResponseStoreRedisConfig] = None
    valkey: Optional[_ResponseStoreValkeyConfig] = None
    dynamodb: Optional[_ResponseStoreDynamoDBConfig] = None


class _InputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Input SQS queue URL for async execution mode")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from input queue before being treated as permanently failed"
    )
    no_of_consumers: int = Field(
        default=5,
        description=(
            "Only used in Containerized deployments "
            "Number of independent consumer threads that each poll the input queue "
            "in a continuous loop. Only used by ECS containerized deployments, it is not used for "
            "serverless (Lambda) mode, which has no consumer threads. "
            "Override via env var AK_EXECUTION__QUEUES__INPUT__NO_OF_CONSUMERS."
        ),
    )


class _OutputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Output SQS queue URL for async execution mode")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from output queue before being treated as permanently failed"
    )
    no_of_consumers: int = Field(
        default=2,
        description=(
            "Only used in Containerized deployments "
            "Number of independent consumer threads that each poll the output queue "
            "in a continuous loop. Only used by ECS containerized deployments, it is not used for "
            "serverless (Lambda) mode, which has no consumer threads. "
            "Override via env var AK_EXECUTION__QUEUES__OUTPUT__NO_OF_CONSUMERS."
        ),
    )


class _QueuesConfig(BaseModel):
    input: _InputQueueConfig = Field(default_factory=_InputQueueConfig, description="Input SQS queue configuration for async execution mode")
    output: _OutputQueueConfig = Field(default_factory=_OutputQueueConfig, description="Output SQS queue configuration for async execution mode")
    batch_size: Optional[int] = Field(
        default=None,
        description=(
            "NOT used in serverless deployments"
            "Max number of messages fetched per SQS receive call, common to input and output queues. "
            "Only used by ECS containerized deployments — never set for serverless (Lambda) mode, which "
            "controls batch size via the Event Source Mapping instead. "
            "Controlled by the Terraform deployment via env var AK_EXECUTION__QUEUES__BATCH_SIZE — do not set in config.yaml."
        ),
    )


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
        description="Execution mode: rest_sync for synchronous REST, rest_async for asynchronous REST, stream for token streaming (WebSocket serverless or containerized direct streaming)",
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
    thread: Optional[_ThreadStoreConfig] = Field(
        default=None,
        description="Conversation Thread Support configurations. Feature is enabled only when this block is present.",
    )

    trace: _TraceConfig = Field(description="Tracing related configurations", default_factory=_TraceConfig)
    guardrail: _GuardrailConfig = Field(description="Guardrail related configurations", default_factory=_GuardrailConfig)
    execution: _ExecutionConfig = Field(description="Execution mode and queue related configurations", default_factory=_ExecutionConfig)
    logging: _LoggingConfig = Field(description="Logging related configurations", default_factory=_LoggingConfig)
    library_version: str = Field(default=_get_ak_version(), description="Library version")

    _instance: ClassVar[Optional["AKConfig"]] = None
    # Reentrant because configure_from_config() calls AKConfig.get() again
    _instance_lock: ClassVar[RLock] = RLock()

    @classmethod
    def get(cls) -> "AKConfig":
        """Return the AKConfig singleton, creating it on first access.

        Loading lazily keeps `import agentkernel` free of config.yaml reads, so
        processes that never touch the configuration (e.g. the CLI test harness)
        never load it. Logging is configured together with the first load since
        its settings come from this config.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    # Set before configuring logging: configure_from_config()
                    # re-enters get() and must see the instance
                    cls._instance = AKConfig()
                    try:
                        from .logger import AKLogger

                        AKLogger.configure_from_config()
                    except Exception:
                        cls._instance = None
                        raise
        return cls._instance

    @classmethod
    def _reset(cls):
        """Clear the cached singleton so the next get() reloads the config.

        Logging is not reconfigured on reload: AKLogger keeps its _initialized
        guard, matching the previous configure-once-at-import behavior.
        """
        cls._instance = None
