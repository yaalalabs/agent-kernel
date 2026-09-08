import importlib.metadata
from threading import RLock
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

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


class _SessionConnectionStoreConfig(BaseModel):
    table_name: Optional[str] = Field(
        default=None,
        description="DynamoDB only: name of the EXISTING WebSocket connections table (partition key 'user_id', "
        "sort key 'connection_id', GSI 'connection_id-index' on connection_id, TTL attribute 'expiry_time'); "
        "the store never creates it. Required for WebSocket modes on dynamodb sessions; unused by other backends.",
    )
    ttl: float = Field(
        default=86400.0,
        description="Seconds after which a connection mapping expires following its last write: the safety net "
        "for gateway pods that die without cleaning up (normal cleanup happens on disconnect and stale pushes).",
    )


class _SessionStoreConfig(BaseModel):
    type: str = Field(
        default="in_memory",
        description="Session store backend: a built-in short name (in_memory, redis, valkey, dynamodb, cosmosdb, firestore) or a dotted path to a SessionStore subclass",
    )
    cache: Optional[_SessionCacheConfig] = None
    redis: Optional[_RedisConfig] = None
    valkey: Optional[_ValkeyConfig] = None
    dynamodb: Optional[_DynamoDBConfig] = None
    cosmosdb: Optional[_CosmosDBConfig] = None
    firestore: Optional[_FirestoreConfig] = None
    connection_store: _SessionConnectionStoreConfig = Field(
        description="The WebSocket gateway's connection store, provided on this session backend (spec #495 §9)",
        default_factory=_SessionConnectionStoreConfig,
    )


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
    push_auth_token: Optional[str] = Field(
        default=None,
        description="Shared secret authenticating pod-to-pod pushes to the pipeline's internal push endpoint "
        "(required for WebSocket modes on a broker transport; unused by API-Gateway-based deployments)",
    )
    push_port: Optional[int] = Field(
        default=None,
        description="Port other pods push WebSocket deliveries to (defaults to api.port). Only for custom "
        "gateways that mount PushEndpointHandler on their own separate listener; the built-in WebSocketGateway "
        "serves everything on api.port and rejects a differing value at startup",
    )


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


class _TeamsConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Microsoft Teams interactions")
    agent_acknowledgement: str = Field(
        default="",
        description="The message to send as an acknowledgement when a Teams message is received",
    )
    app_id: str = Field(default="", description="Azure Bot / Entra ID application (client) ID")
    app_password: str = Field(default="", description="Azure Bot / Entra ID application client secret")
    tenant_id: str = Field(
        default="",
        description="Entra ID tenant that owns the bot's app registration. Required only for a single-tenant registration, whose channel tokens must be issued by its own tenant; leave empty for a multi-tenant bot. Also the fallback tenant for the app-only token used to download attachments whose URL is not pre-authenticated, when the incoming activity carries none",
    )


class _GmailConfig(BaseModel):
    agent: str = Field(default="", description="Default agent to use for Gmail")
    token_file: str = Field(default="token.pickle", description="Path to store OAuth2 token")
    poll_interval: int = Field(default=30, description="Email polling interval in seconds")
    label_filter: str = Field(default="INBOX", description="Gmail label to monitor (e.g., INBOX, UNREAD)")


class _MultimodalStorageRedisConfig(_RedisConfig):
    ttl: int = Field(default=604800, description="Attachment TTL in seconds")
    prefix: str = Field(default="ak:attachments:", description="Key prefix for attachment keys")


class _MultimodalStorageDynamoDBConfig(_DynamoDBConfig):
    table_name: str = Field(default="ak-attachments", description="DynamoDB table name for attachment storage")
    ttl: int = Field(default=604800, description="Attachment TTL in seconds (0 disables)")


class _MultimodalConfig(BaseModel):
    """Configuration for multimodal attachment memory."""

    enabled: bool = Field(
        default=False,
        description="Enable multimodal memory for images and files.",
    )
    agents: Optional[list[str]] = Field(
        default=None,
        description="Agent names the multimodal tools and system-prompt guidance attach to; omitted = all agents",
    )
    storage_type: str = Field(
        default="in_memory",
        description="Storage backend for multimodal attachments: a built-in short name (session_cache, in_memory, redis, dynamodb) or a dotted path to an AttachmentStore subclass",
    )
    max_attachments: int = Field(default=20, description="Maximum number of attachments to keep per session")
    description_max_length: int = Field(default=200, description="Maximum length of attachment description text")
    description_model: str = Field(
        default="gpt-4o",
        description="LiteLLM model used to generate brief descriptions when an attachment is first received (called by the pre-hook)",
    )
    analysis_model: str = Field(
        default="gpt-4o",
        description=(
            "LiteLLM model used by the analyze_attachments tool when the agent requests a full analysis of an attachment; "
            "a remote image is handed to it as a fetchable image URL, so the model must be able to fetch that address, "
            "while other remote attachment types are only named by their address"
        ),
    )
    redis: Optional[_MultimodalStorageRedisConfig] = None
    dynamodb: Optional[_MultimodalStorageDynamoDBConfig] = None


class _ThreadRedisConfig(_RedisConfig):
    ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
    prefix: str = Field(default="ak:thread:", description="Key prefix for Redis thread storage")


class _ThreadValkeyConfig(_ValkeyConfig):
    ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
    prefix: str = Field(default="ak:thread:", description="Key prefix for Valkey thread storage")


class _ThreadDynamoDBConfig(_DynamoDBConfig):
    table_name: str = Field(
        default="ak-agent-threads",
        description="DynamoDB table name for thread storage. Table should have a partition key named 'session_id' (S) and a sort key named 'sk' (S)",
    )
    ttl: int = Field(default=0, description="DynamoDB item TTL in seconds (0 disables)")


class _ThreadFirestoreConfig(_FirestoreConfig):
    collection_name: str = Field(
        default="ak-agent-threads",
        description="Firestore collection name for thread storage. Each document ID is a session_id.",
    )
    ttl: int = Field(default=0, description="Thread TTL in seconds (0 disables)")


class _ThreadCosmosDBConfig(BaseModel):
    connection_string: str = Field(description="Cosmos DB connection string. Can be found in Azure Portal under Keys section")
    table_name: str = Field(default="akagentthreads", description="Cosmos DB table name for thread storage")


class _ThreadNamingConfig(BaseModel):
    model: str = Field(default="gpt-4o-mini", description="LiteLLM model used to generate thread names")
    max_length: int = Field(default=80, description="Maximum length of an auto-generated thread name")


class _ThreadStoreConfig(BaseModel):
    """Configuration for Conversation Thread Support (store backend, naming). The feature is
    enabled by mounting AgentThreadRequestHandler; this block only parameterizes it."""

    type: str = Field(
        default="in_memory",
        description="Thread store backend: a built-in short name (in_memory, redis, valkey, dynamodb, cosmosdb, firestore) or a dotted path to a ThreadStore subclass",
    )
    naming: _ThreadNamingConfig = Field(default_factory=_ThreadNamingConfig, description="Auto-naming settings for the built-in naming strategies")
    redis: Optional[_ThreadRedisConfig] = None
    valkey: Optional[_ThreadValkeyConfig] = None
    dynamodb: Optional[_ThreadDynamoDBConfig] = None
    firestore: Optional[_ThreadFirestoreConfig] = None
    cosmosdb: Optional[_ThreadCosmosDBConfig] = None


# Connection details only, and Terraform-provisioned: the eventbridge provider requires all three.
class _ScheduleEventBridgeConfig(BaseModel):
    group_name: Optional[str] = Field(default=None, description="EventBridge Scheduler schedule-group name the schedules are created in")
    role_arn: Optional[str] = Field(
        default=None, description="Execution role ARN EventBridge Scheduler assumes to deliver triggers to the input queue"
    )
    queue_arn: Optional[str] = Field(default=None, description="Input queue ARN used as the schedule target")


class _ScheduleProviderConfig(BaseModel):
    type: str = Field(
        default="local",
        description="Schedule provider: a built-in short name (local, eventbridge) or a dotted path to a ScheduleProvider subclass",
    )
    eventbridge: Optional[_ScheduleEventBridgeConfig] = None


class _ScheduleStoreRedisConfig(_RedisConfig):
    # Unlike threads, schedules carry no default expiry: a task that silently disappeared
    # would stop firing with no audit trail.
    ttl: int = Field(default=0, description="Scheduled task TTL in seconds (0 disables)")
    prefix: str = Field(default="ak:schedule:", description="Key prefix for Redis scheduled-task storage")


class _ScheduleStoreValkeyConfig(_ValkeyConfig):
    ttl: int = Field(default=0, description="Scheduled task TTL in seconds (0 disables)")
    prefix: str = Field(default="ak:schedule:", description="Key prefix for Valkey scheduled-task storage")


class _ScheduleStoreDynamoDBConfig(_DynamoDBConfig):
    table_name: str = Field(
        default="ak-agent-schedules",
        description="DynamoDB table name for scheduled-task storage. Table should have a partition key named 'task_id' (S) and no sort key",
    )
    ttl: int = Field(default=0, description="DynamoDB item TTL in seconds (0 disables)")


class _ScheduleStoreConfig(BaseModel):
    type: str = Field(
        default="in_memory",
        description="Scheduled task store backend: a built-in short name (in_memory, redis, valkey, dynamodb) or a dotted path to a ScheduleStore subclass",
    )
    redis: Optional[_ScheduleStoreRedisConfig] = None
    valkey: Optional[_ScheduleStoreValkeyConfig] = None
    dynamodb: Optional[_ScheduleStoreDynamoDBConfig] = None


class _ScheduleConfig(BaseModel):
    """Configuration for the scheduling capability (trigger provider, task store, tool scoping).
    The presence of the block is the enablement signal; its defaults (local provider,
    in_memory store) make a bare 'schedule:' block work for local development."""

    provider: _ScheduleProviderConfig = Field(
        default_factory=_ScheduleProviderConfig, description="Backend that fires the triggers at their scheduled times"
    )
    store: _ScheduleStoreConfig = Field(default_factory=_ScheduleStoreConfig, description="Backend that persists the scheduled task records")
    agents: Optional[list[str]] = Field(
        default=None,
        description="Agent names the schedule tools and system-prompt guidance attach to; omitted = all agents",
    )


class _TraceConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable tracing")
    type: str = Field(
        default="langfuse",
        description="Tracing backend: a built-in short name (langfuse, openllmetry, logfire) or a dotted path to a BaseTrace subclass",
    )


class _GuardrailParamConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable Guardrail")
    type: str = Field(
        default="openai",
        description="Guardrail backend: a built-in short name (openai, bedrock, walledai) or a dotted path to an InputGuardrail/OutputGuardrail subclass",
    )
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
    type: str = Field(
        default=None,
        description="Response store backend: a built-in short name (in_memory, redis, valkey, dynamodb) or a dotted path to a ResponseStore subclass",
    )
    retry_count: int = Field(default=5, description="Number of retry attempts for response store reads")
    delay: float = Field(default=5, description="Delay in seconds between response store reads retry attempts")
    redis: Optional[_ResponseStoreRedisConfig] = None
    valkey: Optional[_ResponseStoreValkeyConfig] = None
    dynamodb: Optional[_ResponseStoreDynamoDBConfig] = None


class _InputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Input queue URL (sqs transport only)")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from input queue before being treated as permanently failed"
    )
    no_of_consumers: int = Field(
        default=5,
        description=(
            "Number of independent consumer threads that each poll the input queue in a continuous "
            "loop. Used by the in-process pipeline (agent-runner worker threads) and by ECS "
            "containerized deployments; not used in serverless (Lambda) mode, which has no consumer "
            "threads. Override via env var AK_EXECUTION__QUEUES__INPUT__NO_OF_CONSUMERS."
        ),
    )


class _OutputQueueConfig(BaseModel):
    url: str = Field(default=None, description="Output queue URL (sqs transport only)")
    max_receive_count: int = Field(
        default=3, description="Maximum number of times a message can be received from output queue before being treated as permanently failed"
    )
    no_of_consumers: int = Field(
        default=2,
        description=(
            "Number of independent consumer threads that each poll the output queue in a continuous "
            "loop. Used by the in-process pipeline (response-handler worker threads) and by ECS "
            "containerized deployments; not used in serverless (Lambda) mode, which has no consumer "
            "threads. Override via env var AK_EXECUTION__QUEUES__OUTPUT__NO_OF_CONSUMERS."
        ),
    )


class _InMemoryQueueConfig(BaseModel):
    ack_wait: float = Field(
        default=300.0,
        description=(
            "Seconds an unacknowledged in-memory message stays invisible before redelivery. "
            "Redelivery rescues stuck worker threads; keep this above your longest expected agent run "
            "or a slow run will be executed again."
        ),
    )
    dedup_window: float = Field(default=300.0, description="Seconds within which a repeated message_deduplication_id is dropped")


class _KafkaQueueConfig(BaseModel):
    bootstrap_servers: str = Field(default="localhost:9092", description="Kafka bootstrap servers (host:port, comma-separated)")
    input_topic: str = Field(default="agent-input", description="Topic carrying chat requests")
    output_topic: str = Field(default="agent-output", description="Topic carrying agent replies")
    group_id: str = Field(
        default="agent-kernel",
        description="Consumer group id prefix; the input and output consumers append their queue name to it",
    )
    dlq_suffix: str = Field(
        default=".dlq",
        description="Suffix appended to a topic name for its dead-letter topic, where permanently failed records are routed",
    )
    retry_backoff: float = Field(default=2.0, description="Seconds to wait before an in-process retry of a failed record")
    delivery_timeout: float = Field(default=30.0, description="Seconds to wait for the broker to confirm a produced message before failing the send")
    metadata_timeout: float = Field(
        default=5.0,
        description="Seconds to wait for topic metadata during the startup partition-capacity check (the check is skipped on timeout)",
    )
    client_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Passthrough settings merged into the confluent-kafka producer and consumer configs (SASL, TLS, tuning)",
    )


class _NatsQueueConfig(BaseModel):
    url: str = Field(default="nats://localhost:4222", description="NATS server URL (comma-separated for a cluster)")
    input_stream: str = Field(default="AGENT_REQUESTS", description="JetStream stream carrying chat requests")
    input_subject_prefix: str = Field(default="chat.req", description="Subject prefix for chat requests")
    output_stream: str = Field(default="AGENT_REPLIES", description="JetStream stream carrying agent replies")
    output_subject_prefix: str = Field(default="chat.out", description="Subject prefix for agent replies")
    partitions: int = Field(
        default=32,
        description=(
            "Number of partition subjects per stream, each served by its own durable consumer. Sessions hash to a "
            "partition, so this caps how many messages can be in flight at once: keep it at or above "
            "no_of_consumers x replicas. Changing it re-maps sessions, so size it up front (idle partitions cost "
            "almost nothing)."
        ),
    )
    ack_wait: float = Field(
        default=300.0,
        description=(
            "Seconds the server waits for an acknowledgement before redelivering. Must exceed your longest agent "
            "turn: a turn that outlives it is redelivered and executed a second time."
        ),
    )
    retry_backoff: float = Field(default=2.0, description="Seconds to delay a redelivery after a failed message (nak delay)")
    duplicate_window: float = Field(default=300.0, description="Seconds within which a repeated dedup id is dropped by the stream (SQS parity)")
    max_age: float = Field(
        default=86400.0,
        description="Seconds before an unconsumed message is discarded. A safety net: work-queue messages are otherwise kept forever",
    )
    request_timeout: float = Field(default=10.0, description="Seconds to wait for a NATS request (publish, ack, management call) to complete")
    auto_provision: bool = Field(
        default=False,
        description=(
            "Create the streams and per-partition consumers at startup if missing. Convenient for local and dev "
            "clusters; leave false in production, where the objects are managed declaratively (NACK CRs) and a "
            "missing object should fail loudly instead of being created with defaults."
        ),
    )


class _QueuesConfig(BaseModel):
    type: str = Field(
        description=(
            "Queue transport: in_memory | sqs | kafka | nats, or a dotted path to a QueueTransport "
            "subclass. Mandatory whenever this block is declared: the transport decides the "
            "deployment topology, so it is declared by the application rather than inferred from "
            "whichever queue coordinates a deployment happens to inject. Omitting the whole block "
            "leaves the single-process 'in_memory' transport."
        ),
    )
    input: _InputQueueConfig = Field(default_factory=_InputQueueConfig, description="Input queue configuration for queue execution mode")
    output: _OutputQueueConfig = Field(default_factory=_OutputQueueConfig, description="Output queue configuration for queue execution mode")
    in_memory: Optional[_InMemoryQueueConfig] = Field(default=None, description="in_memory transport settings")
    kafka: Optional[_KafkaQueueConfig] = Field(default=None, description="kafka transport settings")
    nats: Optional[_NatsQueueConfig] = Field(default=None, description="nats transport settings")
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
    # The default carries the transport type explicitly: `type` is mandatory inside a declared
    # queues block, and a config that declares no block at all still runs single-process on the
    # in-process pipeline, whose topology needs no queue coordinates.
    queues: Optional[_QueuesConfig] = Field(
        default_factory=lambda: _QueuesConfig(type="in_memory"),
        description="Queue transport and queue settings for queue-based execution",
    )
    response_store: Optional[_ResponseStoreConfig] = Field(
        default=None,
        description="Response storage configuration for async execution mode",
    )


class _SandboxIdentityConfig(BaseModel):
    mode: str = Field(
        default="agent",
        pattern="^(agent|user)$",
        description="Execution identity: 'agent' runs under the agent's own credentials, 'user' under the invoking user's resolved identity",
    )


class _SandboxPolicyConfig(BaseModel):
    network_egress: str = Field(
        default="allow",
        pattern="^(allow|deny|allowlist)$",
        description="Network egress policy: 'allow' all, 'deny' all, or 'allowlist' to restrict to network_allow",
    )
    network_allow: list[str] = Field(default_factory=list, description="Domains and/or CIDRs permitted when network_egress is 'allowlist'")
    fs_allow_read: list[str] = Field(default_factory=list, description="Filesystem paths the sandbox may read; empty uses the provider default")
    fs_allow_write: list[str] = Field(default_factory=list, description="Filesystem paths the sandbox may write; empty uses the provider default")
    cpu: Optional[float] = Field(default=None, description="CPU core limit for the sandbox; None leaves it to the provider default")
    memory_mb: Optional[int] = Field(default=None, description="Memory limit in megabytes; None leaves it to the provider default")
    timeout: float = Field(default=120.0, description="Per-execution wall-clock timeout in seconds")
    strict: bool = Field(default=True, description="Fail closed when a policy dimension cannot be enforced by the selected provider")


class _SandboxLocalSubprocessConfig(BaseModel):
    workdir: Optional[str] = Field(default=None, description="Base directory for per-sandbox working directories; None uses the system temp location")


class _SandboxDockerConfig(BaseModel):
    image: str = Field(default="python:3.12-slim", description="Container image used to create sandboxes")
    runtime: str = Field(default="docker", description="Container runtime to invoke (e.g. docker, nvidia)")
    attach_to: Optional[str] = Field(default=None, description="Existing container id to attach to instead of creating one (mode 3)")


class _SandboxE2BConfig(BaseModel):
    api_key_env: str = Field(default="E2B_API_KEY", description="Name of the environment variable holding the E2B API key")
    template: str = Field(default="base", description="E2B sandbox template to launch")


class _SandboxDaytonaConfig(BaseModel):
    api_key_env: str = Field(default="DAYTONA_API_KEY", description="Name of the environment variable holding the Daytona API key")
    target: Optional[str] = Field(default=None, description="Daytona target/region; None uses the SDK default")
    image: Optional[str] = Field(
        default=None,
        description="Container image for the sandbox (e.g. 'python:3.12-slim' or a registry image). Mutually exclusive with 'snapshot'; when neither is set Daytona uses its default snapshot.",
    )
    snapshot: Optional[str] = Field(
        default=None,
        description="Named Daytona snapshot to launch from. Mutually exclusive with 'image'; when neither is set Daytona uses its default snapshot.",
    )
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables set inside the sandbox")

    @model_validator(mode="after")
    def _image_snapshot_exclusive(self) -> "_SandboxDaytonaConfig":
        """A sandbox launches from exactly one base — reject configuring both."""
        if self.image and self.snapshot:
            raise ValueError("daytona config sets both 'image' and 'snapshot'; they are mutually exclusive — pick one")
        return self


class _SandboxBedrockAgentCoreConfig(BaseModel):
    region: Optional[str] = Field(default=None, description="AWS region for the Bedrock AgentCore code interpreter; None uses the boto3 default")
    network_mode: str = Field(default="sandbox", description="AgentCore session network mode (e.g. 'sandbox', 'public')")


class _SandboxKubernetesConfig(BaseModel):
    namespace: str = Field(default="default", description="Kubernetes namespace for sandbox pods")
    image: str = Field(default="python:3.12-slim", description="Container image used for launched sandbox pods")
    attach_to: Optional[str] = Field(default=None, description="Existing '<namespace>/<pod>' to exec into instead of launching a pod (mode 3)")
    kubeconfig: Optional[str] = Field(default=None, description="Path to a kubeconfig file; None uses in-cluster or default configuration")
    service_account: Optional[str] = Field(
        default=None,
        description="ServiceAccount assigned to sandbox pods; bind it to the (read-only) RBAC role that is the execution's security boundary",
    )
    image_pull_secrets: List[str] = Field(default_factory=list, description="imagePullSecrets names for the sandbox pod")
    labels: Dict[str, str] = Field(default_factory=dict, description="Extra labels merged onto sandbox pods")
    node_selector: Dict[str, str] = Field(default_factory=dict, description="nodeSelector for sandbox pods")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables set in the sandbox container")
    security_context: Dict[str, Any] = Field(default_factory=dict, description="Pod-level securityContext overlay")
    container_security_context: Dict[str, Any] = Field(
        default_factory=dict, description="Container-level securityContext overlay (over the hardened defaults)"
    )
    network_policy: bool = Field(
        default=False,
        description="Create per-pod NetworkPolicies for deny/allowlist egress and declare policy_network; "
        "set only when the cluster CNI enforces NetworkPolicy",
    )
    create_timeout: float = Field(default=120.0, description="Seconds to wait for a sandbox pod to reach Running before failing provisioning")


class _SandboxEC2SSMConfig(BaseModel):
    region: Optional[str] = Field(default=None, description="AWS region for SSM; None uses the boto3 default")
    attach_to: Optional[str] = Field(default=None, description="EC2 instance id to run commands against via SSM (attach-only)")


class _ExecutionBrokerConfig(BaseModel):
    flavor: str = Field(
        default="thread",
        description="Broker flavor: 'embedded' | 'thread' (in-process) | 'queue' (transport-backed, #503) | a dotted path to an ExecutionBroker subclass",
    )
    wait_timeout: float = Field(
        default=60.0,
        description="Max seconds a synchronous wait blocks before promotion to a task (0 = always promote); "
        "on the 'queue' flavor this also bounds waits submitted without an explicit wait",
    )
    wait_poll_interval: float = Field(
        default=0.5, description="Seconds between response-store polls while a 'queue'-flavor caller waits synchronously"
    )
    inline_payload_max_bytes: int = Field(
        default=131072,
        description="On the 'queue' flavor: requests larger than this are rejected at submit, and result output beyond it is truncated with a notice",
    )
    response_ttl: int = Field(default=86400, description="TTL in seconds for stored task completions and broker-side session-inventory records")
    sweep_interval: int = Field(default=300, description="Interval in seconds between broker-side idle-session sweeps")
    worker_timeout_ceiling: Optional[float] = Field(
        default=None,
        description="Max effective execution timeout (s) the provisioned worker supports; terraform output — 840 in serverless mode, null in server_based. None = no ceiling.",
    )
    queue: Optional[_QueuesConfig] = Field(
        default=None,
        description="Sandbox broker queues for the 'queue' flavor; reuses the execution.queues shape "
        "(input carries execution requests to the worker, output carries completions back to the response store)",
    )
    response_store: Optional[_ResponseStoreConfig] = Field(
        default=None,
        description="Response storage for the 'queue' flavor (required by it); reuses the execution response store model. "
        "Its ttl fields are overridden by response_ttl, and retry_count/delay are unused (queue-flavor waits are deadline-driven)",
    )


class _SandboxProfileConfig(BaseModel):
    type: str = Field(description="Provider short name (e.g. 'docker', 'e2b') or a dotted path to a SandboxProvider subclass")
    scope: str = Field(
        default="per_session",
        pattern="^(per_call|per_session|per_runtime)$",
        description="Sandbox lifetime: 'per_call' (new per execution), 'per_session' (per AK session), or 'per_runtime' (shared)",
    )
    environment: str = Field(
        default="managed",
        pattern="^(managed|attached)$",
        description="Environment lifecycle: 'managed' (the provider creates and disposes sandboxes) or 'attached' "
        "(deliberately connect to an existing environment the framework never owns; requires the provider's attach_to)",
    )
    idle_timeout: int = Field(default=1800, description="Seconds of inactivity before a sandbox session is closed on next touch")
    identity: _SandboxIdentityConfig = Field(default_factory=_SandboxIdentityConfig, description="Execution identity configuration")
    policy: _SandboxPolicyConfig = Field(
        default_factory=_SandboxPolicyConfig, description="Execution policy (network, filesystem, resources, timeout)"
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Arbitrary parameters passed to a dotted-path provider")
    local_subprocess: Optional[_SandboxLocalSubprocessConfig] = Field(default=None, description="Configuration for the 'local_subprocess' provider")
    docker: Optional[_SandboxDockerConfig] = Field(default=None, description="Configuration for the 'docker' provider")
    e2b: Optional[_SandboxE2BConfig] = Field(default=None, description="Configuration for the 'e2b' provider")
    daytona: Optional[_SandboxDaytonaConfig] = Field(default=None, description="Configuration for the 'daytona' provider")
    bedrock_agentcore: Optional[_SandboxBedrockAgentCoreConfig] = Field(
        default=None, description="Configuration for the 'bedrock_agentcore' provider"
    )
    kubernetes: Optional[_SandboxKubernetesConfig] = Field(default=None, description="Configuration for the 'kubernetes' provider")
    ec2_ssm: Optional[_SandboxEC2SSMConfig] = Field(default=None, description="Configuration for the 'ec2_ssm' provider")


class _SandboxConfig(BaseModel):
    enabled: bool = Field(
        default=False, description="Enable the sandbox capability; when False it is inert (no tools, no hook behavior, no provider imports)"
    )
    agents: Optional[list[str]] = Field(
        default=None,
        description="Agent names the sandbox tools and system-prompt guidance attach to; omitted = all agents",
    )
    default_profile: str = Field(default="default", description="Profile name used when a caller does not specify one")
    principal_resolver: Optional[str] = Field(
        default=None, description="Dotted path to a PrincipalResolver mapping the session/agent to a SandboxPrincipal"
    )
    tool_output_max_chars: int = Field(default=8000, description="Maximum characters of tool output returned to the agent before truncation")
    broker: _ExecutionBrokerConfig = Field(default_factory=_ExecutionBrokerConfig, description="Sandbox broker configuration")
    profiles: dict[str, _SandboxProfileConfig] = Field(
        default_factory=dict, description="Named workload profiles, each selecting a provider and its policy/identity"
    )
    # Single-backend sugar: when profiles is empty and type is set, a model_validator
    # synthesizes profiles[default_profile] from the top-level fields below.
    type: Optional[str] = Field(
        default=None, description="Single-backend sugar: provider short name or dotted path used to synthesize the default profile"
    )
    scope: Optional[str] = Field(
        default=None,
        pattern="^(per_call|per_session|per_runtime)$",
        description="Single-backend sugar: scope for the synthesized default profile",
    )
    environment: Optional[str] = Field(
        default=None,
        pattern="^(managed|attached)$",
        description="Single-backend sugar: environment lifecycle for the synthesized default profile",
    )
    local_subprocess: Optional[_SandboxLocalSubprocessConfig] = Field(
        default=None, description="Single-backend sugar: 'local_subprocess' provider configuration"
    )
    docker: Optional[_SandboxDockerConfig] = Field(default=None, description="Single-backend sugar: 'docker' provider configuration")
    e2b: Optional[_SandboxE2BConfig] = Field(default=None, description="Single-backend sugar: 'e2b' provider configuration")
    daytona: Optional[_SandboxDaytonaConfig] = Field(default=None, description="Single-backend sugar: 'daytona' provider configuration")
    bedrock_agentcore: Optional[_SandboxBedrockAgentCoreConfig] = Field(
        default=None, description="Single-backend sugar: 'bedrock_agentcore' provider configuration"
    )
    kubernetes: Optional[_SandboxKubernetesConfig] = Field(default=None, description="Single-backend sugar: 'kubernetes' provider configuration")
    ec2_ssm: Optional[_SandboxEC2SSMConfig] = Field(default=None, description="Single-backend sugar: 'ec2_ssm' provider configuration")

    @model_validator(mode="after")
    def _synthesize_default_profile(self) -> "_SandboxConfig":
        """Build profiles[default_profile] from the single-backend sugar fields.

        Only runs when no profiles are declared and a top-level type is set, so an
        explicit profiles map always takes precedence.
        """
        if not self.profiles and self.type is not None:
            profile_kwargs: dict[str, Any] = {
                "type": self.type,
                "local_subprocess": self.local_subprocess,
                "docker": self.docker,
                "e2b": self.e2b,
                "daytona": self.daytona,
                "bedrock_agentcore": self.bedrock_agentcore,
                "kubernetes": self.kubernetes,
                "ec2_ssm": self.ec2_ssm,
            }
            if self.scope is not None:
                profile_kwargs["scope"] = self.scope
            if self.environment is not None:
                profile_kwargs["environment"] = self.environment
            self.profiles = {self.default_profile: _SandboxProfileConfig(**profile_kwargs)}
        return self


class _AGUIStateConfig(BaseModel):
    """Opt-in for the AG-UI shared-state tools (`get_agui_state` / `update_agui_state`)."""

    enabled: bool = Field(default=False, description="Expose the AG-UI state tools to agents")
    agents: Optional[list[str]] = Field(default=None, description="Agent names the tools attach to; omitted = all agents")


class _AGUIClientContextConfig(BaseModel):
    """Opt-in for the read-only AG-UI client-context tools (forwarded props and context)."""

    enabled: bool = Field(
        default=False,
        description="Expose the read-only AG-UI client-context tools (forwarded props and context) to agents",
    )
    agents: Optional[list[str]] = Field(default=None, description="Agent names the tools attach to; omitted = all agents")


class _AGUIConfig(BaseModel):
    """Parameterizes a mounted AGUIRequestHandler. Mounting the handler is what enables AG-UI;
    this block never switches the surface on. The two nested blocks do switch on agent-facing tools."""

    agents: Optional[list[str]] = Field(default=None, description="Agent names reachable over AG-UI; omitted = all streaming-capable agents")
    prefix: str = Field(default="/agui", description="Route prefix for the AG-UI surface")
    default_agent: Optional[str] = Field(default=None, description="Agent served on the bare prefix route")
    state: _AGUIStateConfig = Field(default_factory=_AGUIStateConfig)
    client_context: _AGUIClientContextConfig = Field(default_factory=_AGUIClientContextConfig)


class AKConfig(YamlBaseSettingsModified):
    """Root configuration, loaded from config.yaml and `AK_`-prefixed environment variables."""

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
    teams: _TeamsConfig = Field(description="Microsoft Teams related configurations", default_factory=_TeamsConfig)
    gmail: _GmailConfig = Field(description="Gmail related configurations", default_factory=_GmailConfig)
    multimodal: _MultimodalConfig = Field(description="Multimodal attachment memory configurations", default_factory=_MultimodalConfig)
    thread: Optional[_ThreadStoreConfig] = Field(
        default=None,
        description="Conversation Thread Support configurations (store backend, naming). The feature is served by mounting AgentThreadRequestHandler; this block only parameterizes it.",
    )

    agui: _AGUIConfig = Field(description="AG-UI integration configurations", default_factory=_AGUIConfig)
    schedule: Optional[_ScheduleConfig] = Field(
        default=None,
        description="Scheduling capability configurations (trigger provider, task store, tool scoping). Absent = the capability is disabled.",
    )

    trace: _TraceConfig = Field(description="Tracing related configurations", default_factory=_TraceConfig)
    guardrail: _GuardrailConfig = Field(description="Guardrail related configurations", default_factory=_GuardrailConfig)
    sandbox: _SandboxConfig = Field(description="Sandbox capability configurations", default_factory=_SandboxConfig)
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
