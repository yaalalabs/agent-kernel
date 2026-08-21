# Agent Kernel

[![PyPI version](https://badge.fury.io/py/agentkernel.svg)](https://badge.fury.io/py/agentkernel)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Agent Kernel is a lightweight **AI agent runtime** and adapter layer for building and running AI agents across multiple frameworks. Migrate your existing agents to Agent Kernel and instantly utilize pre-built execution and testing capabilities. Deploy the same agent code without modification — see the "Multi-Cloud Deployment" section below for supported platforms.

## Features

- **Unified API**: Common abstractions (Agent, Runner, Session, Module, Runtime) across frameworks
- **Multi-Framework Support**: OpenAI Agents SDK, CrewAI, LangGraph, Google ADK, Smolagents, and Pydantic AI
- **Session Management**: Built-in session abstraction with pluggable storage backends
- **Knowledge Bases**: Unified `KnowledgeBase` interface with ChromaDB, Neo4j, and Starburst/Trino backends via `KnowledgeBuilder`
- **Sandbox**: Execute agent-generated code and shell commands in an isolated, permission-bounded environment with pluggable providers (`local_subprocess`, `docker`, `e2b`, `daytona`, `ec2_ssm`), workload profiles, policy enforcement, and per-user identity
- **Flexible Deployment**: Interactive CLI, REST API, serverless, or containerized deployment — see the "Multi-Cloud Deployment" section below
- **Pluggable Architecture**: Easy to extend with custom framework adapters
- **MCP Server**: Built-in Model Context Protocol server for exposing agents as MCP tools and exposing any custom tool
- **A2A Server**: Built-in Agent-to-Agent communication server for exposing agents with a simple configuration change
- **REST API**: Built-in REST API server for agent interaction
- **Test Automation**: Built-in test suite for testing agents

## Installation

```bash
pip install agentkernel
```

Install optional knowledge base extras as needed:

```bash
pip install "agentkernel[chromadb]"
pip install "agentkernel[neo4j]"
pip install "agentkernel[trino]"
```

For LLM-based thread naming with Conversation Thread Support:

```bash
pip install "agentkernel[thread]"
```

For the sandbox providers (the `local_subprocess` provider needs no extra; `ec2_ssm` rides
the `aws` extra):

```bash
pip install "agentkernel[sandbox-docker]"   # docker provider
pip install "agentkernel[e2b]"              # e2b cloud provider
pip install "agentkernel[daytona]"          # daytona cloud provider
pip install "agentkernel[aws]"              # ec2_ssm provider (boto3)
```

For cron parsing with the Scheduling capability (the `eventbridge` provider rides the `aws` extra):

```bash
pip install "agentkernel[cron]"
```

**Requirements:**
- Python 3.12+

## Quick Start

### Basic Concepts

- **Agent**: Framework-specific agent wrapped by an Agent Kernel adapter
- **Runner**: Framework-specific execution strategy
- **Session**: Shared state across conversation turns
- **Module**: Container that registers agents with the Runtime
- **Runtime**: Global registry and orchestrator for agents

### CrewAI Example

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

general_agent = CrewAgent(
    role="general",
    goal="Agent for general questions",
    backstory="You provide assistance with general queries. Give direct and short answers",
    verbose=False,
)

math_agent = CrewAgent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

# Register agents with Agent Kernel
CrewAIModule([general_agent, math_agent])

if __name__ == "__main__":
    CLI.main()
```

### LangGraph Example

```python
from langgraph.graph import StateGraph
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

# Build and compile your graph
sg = StateGraph(...)
compiled = sg.compile()
compiled.name = "assistant"

LangGraphModule([compiled])

if __name__ == "__main__":
    CLI.main()
```

### OpenAI Agents SDK Example

```python
from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

OpenAIModule([general_agent])

if __name__ == "__main__":
    CLI.main()
```

### Google ADK Example

```python
from google.adk.agents import Agent
from agentkernel.cli import CLI
from agentkernel.adk import GoogleADKModule
from google.adk.models.lite_llm import LiteLlm

# Create Google ADK agents
math_agent = Agent(
    name="math",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Specialist agent for math questions",
    instruction="""
    You provide help with math problems.
    Explain your reasoning at each step and include examples.
    If prompted for anything else you refuse to answer.
    """,
)

GoogleADKModule([math_agent])

if __name__ == "__main__":
    CLI.main()
```

## Interactive CLI

Agent Kernel includes an interactive CLI for local development and testing.

**Available Commands:**
- `!h`, `!help` — Show help
- `!ld`, `!load <module_name>` — Load a Python module containing agents
- `!ls`, `!list` — List registered agents
- `!s`, `!select <agent_name>` — Select an agent
- `!n`, `!new` — Start a new session
- `!q`, `!quit` — Exit

**Usage:**

```bash
python demo.py
```

Then interact with your agents:

```text
(assistant) >> !load my_agents
(assistant) >> !select researcher
(researcher) >> What is the latest news on AI?
```

## Multi-Cloud Deployment

**Supported Cloud Platforms:** AWS, Azure, GCP

Deploy your agents to AWS, Azure, or GCP using the built-in cloud deployment handlers.

### AWS Lambda Deployment

Deploy your agents as serverless functions using the built-in Lambda handler.

```python
from openai import OpenAI
from agents import Agent as OpenAIAgent
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule

client = OpenAI()
assistant = OpenAIAgent(name="assistant")

OpenAIModule([assistant])
handler = Lambda.handler
```

**Note that this is just the simple serverless version. A more advanced serverless deployment mode, which uses queues for scalability, is also available. For queue-backed execution modes and response-store configuration, see the [AWS Serverless Deployment](https://github.com/yaalalabs/agent-kernel/tree/develop/docs/docs/deployment/aws-serverless.md) guide.**

The AWS serverless handler accepts both a direct `BaseRunRequest` payload and the normalized `BaseRequest` envelope. If a flat run payload is provided, Agent Kernel generates a `request_id` and normalizes it before processing. 

Accepted payloads:

```json
{
  "prompt": "Hello agent",
  "agent": "assistant",
  "session_id": "user-123"
}
```

```json
{
  "request_id": "req-123",
  "user_id": "user-123",
  "body": {
    "prompt": "Hello agent",
    "agent": "assistant",
    "session_id": "user-123"
  }
}
```

### Azure Functions Deployment

Deploy your agents as Azure Functions using the built-in Azure handler.

```python
from openai import OpenAI
from agents import Agent as OpenAIAgent
from agentkernel.azure import AzureFunctions
from agentkernel.openai import OpenAIModule

client = OpenAI()
assistant = OpenAIAgent(name="assistant")

OpenAIModule([assistant])
handler = AzureFunctions.handler
```

**Request Format:**

```json
{
  "request_id": "req-123",
  "user_id": "user-123",
  "body": {
    "prompt": "Hello agent",
    "agent": "assistant",
    "session_id": "user-123"
  }
}
```

Azure Functions also accepts the normalized envelope, and flat run payloads are normalized in the same way before the request reaches the agent runtime.

**Response Format:**

```json
{
  "result": "Agent response here"
}
```

**Status Codes:**
- `200` — Success
- `400` — No agent available
- `500` — Unexpected error

### GCP Cloud Run Deployment

Deploy your agents to GCP Cloud Run using the built-in `CloudRun` handler.

```python
from agentkernel.gcp import CloudRun
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

@CloudRun.register("/app", method="GET")
def app_handler() -> dict:
    return {"status": "ok"}

def main() -> None:
    CloudRun.run()

if __name__ == "__main__":
    main()
```

`CloudRun` is the GCP equivalent of `Lambda` (AWS) and `AzureFunctions` (Azure). It wraps `RESTAPI` and starts a FastAPI/uvicorn server. Custom routes are registered with `@CloudRun.register(path, method)`. Use `CloudRun.run()` instead of `RESTAPI.run()` when deploying to GCP.

For full Terraform deployment configuration, see [`ak-deployment/ak-gcp/`](https://github.com/yaalalabs/agent-kernel/tree/develop/ak-deployment/ak-gcp) or the [GCP deployment docs](https://github.com/yaalalabs/agent-kernel/tree/develop/docs/docs/deployment/gcp-serverless.md).

### On-Prem / Kubernetes Deployment

Deploy the queue pipeline to any Kubernetes cluster with the official Helm chart: an
io-handler Deployment (REST API + Response Handler), an agent-runner Deployment, and an
optional WebSocket gateway, over Kafka or NATS JetStream (or SQS on EKS). Your image supplies
one entry file per component:

```python
# app_io_handler.py
from agentkernel.pipeline import IOHandler

IOHandler.run()

# app_agent_runner.py
from agentkernel.openai import OpenAIModule
from agentkernel.pipeline import AgentRunner

OpenAIModule([...])
AgentRunner.run()
```

The chart injects broker and store connections as `AK_*` environment variables. See
[`ak-deployment/ak-k8s/`](https://github.com/yaalalabs/agent-kernel/tree/develop/ak-deployment/ak-k8s),
the [On-Prem / Kubernetes docs](https://github.com/yaalalabs/agent-kernel/tree/develop/docs/docs/deployment/onprem-kubernetes.md),
and the end-to-end example at
[`examples/k8s/openai-queue-mode`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/k8s/openai-queue-mode).

## Configuration

Agent Kernel can be configured via environment variables, `.env` files, or YAML/JSON configuration files.

### Configuration Precedence

Values are loaded in the following order (highest precedence first):
1. Environment variables (including variables from `.env` file)
2. Configuration file (YAML or JSON)
3. Built-in defaults

### Configuration File

By default, Agent Kernel looks for `./config.yaml` in the current working directory.

**Override the config file path:**

```bash
export AK_CONFIG_PATH_OVERRIDE=config.json
# or
export AK_CONFIG_PATH_OVERRIDE=conf/agent-kernel.yaml
```

Supported formats: `.yaml`, `.yml`, `.json`

### Configuration Options

#### Logging Configuration

- **Field**: `logging.ak.level`
- **Type**: string
- **Default**: `WARNING`
- **Description**: Agent Kernel logger level (INFO, DEBUG, ERROR, WARNING, CRITICAL)
- **Environment Variable**: `AK_LOGGING__AK__LEVEL`

- **Field**: `logging.system.level`
- **Type**: string
- **Default**: `WARNING`
- **Description**: System/root logger level (INFO, DEBUG, ERROR, WARNING, CRITICAL)
- **Environment Variable**: `AK_LOGGING__SYSTEM__LEVEL`

#### Session Store

Configure where agent sessions are stored (supports multi-cloud storage backends).

- **Field**: `session.type`
- **Type**: string
- **Options**: `in_memory`, `redis`, `valkey` (AWS), `dynamodb` (AWS), `cosmosdb` (Azure), `firestore` (GCP)
- **Default**: `in_memory`
- **Environment Variable**: `AK_SESSION__TYPE`

##### Redis Configuration

Required when `session.type=redis`:

- **URL**
  - **Field**: `session.redis.url`
  - **Default**: `redis://localhost:6379`
  - **Description**: Redis connection URL. Use `rediss://` for SSL
  - **Environment Variable**: `AK_SESSION__REDIS__URL`

- **TTL (Time to Live)**
  - **Field**: `session.redis.ttl`
  - **Default**: `604800` (7 days)
  - **Description**: Session TTL in seconds
  - **Environment Variable**: `AK_SESSION__REDIS__TTL`

- **Key Prefix**
  - **Field**: `session.redis.prefix`
  - **Default**: `ak:sessions:`
  - **Description**: Key prefix for session storage
  - **Environment Variable**: `AK_SESSION__REDIS__PREFIX`

##### Valkey Configuration

Required when `session.type=valkey` (requires the `agentkernel[valkey]` extra). [Valkey](https://valkey.io/)
is the open-source, Linux Foundation-governed fork of Redis — wire-compatible with Redis and
available on AWS ElastiCache at a lower price point than the Redis OSS engine:

- **URL**
  - **Field**: `session.valkey.url`
  - **Default**: `valkey://localhost:6379`
  - **Description**: Valkey connection URL. Use `valkeys://` for SSL
  - **Environment Variable**: `AK_SESSION__VALKEY__URL`

- **TTL (Time to Live)**
  - **Field**: `session.valkey.ttl`
  - **Default**: `604800` (7 days)
  - **Description**: Session TTL in seconds
  - **Environment Variable**: `AK_SESSION__VALKEY__TTL`

- **Key Prefix**
  - **Field**: `session.valkey.prefix`
  - **Default**: `ak:sessions:`
  - **Description**: Key prefix for session storage
  - **Environment Variable**: `AK_SESSION__VALKEY__PREFIX`

#### Conversation Thread Support

Mounting `AgentThreadRequestHandler` (from `agentkernel.thread`) instead of the default REST handler
enables persistent, named conversation threads keyed by `session_id`: it serves the standard chat routes
with thread recording, plus the read routes (`GET /api/v1/threads` and
`GET /api/v1/threads/{session_id}`, optionally protected by a pluggable `Authoriser`). The `thread`
block in the configuration only selects the store backend and naming. On the thread handler's chat
routes `user_id` is required, and a thread is auto-created on a session's first request. Sending
`thread_name` on any chat request sets or renames the thread's display name and locks it against automatic
naming. Threads created without an explicit `thread_name` are
named by a pluggable naming strategy — by default an LLM call derives a concise title from the first prompt
(falling back to a prefix of the prompt when `litellm` or an API key is unavailable). Attachments in thread
mode additionally require `multimodal.enabled: true` with a shared attachment store (`in_memory`, `redis`, or
`dynamodb` — `session_cache` is rejected). See `examples/api/thread-openai` and
`examples/api/multimodal/thread-openai`.

- **Field**: `thread.type`
- **Type**: string
- **Options**: `in_memory`, `redis`, `valkey`, `dynamodb` (AWS), `firestore` (GCP), `cosmosdb` (Azure)
- **Default**: `in_memory`
- **Environment Variable**: `AK_THREAD__TYPE`

- **Naming Model**
  - **Field**: `thread.naming.model`
  - **Type**: string
  - **Default**: `gpt-4o-mini`
  - **Description**: LiteLLM model used to generate thread names (requires the `thread` extra — `pip install "agentkernel[thread]"` — and an API key in the environment; falls back to a truncated prompt prefix otherwise)
  - **Environment Variable**: `AK_THREAD__NAMING__MODEL`

- **Auto-name Max Length**
  - **Field**: `thread.naming.max_length`
  - **Type**: integer
  - **Default**: `80`
  - **Description**: Maximum length of an auto-generated thread name
  - **Environment Variable**: `AK_THREAD__NAMING__MAX_LENGTH`

##### Redis Thread Store

Required when `thread.type=redis`:

- **URL**
  - **Field**: `thread.redis.url`
  - **Default**: `redis://localhost:6379`
  - **Description**: Redis connection URL. Use `rediss://` for SSL
  - **Environment Variable**: `AK_THREAD__REDIS__URL`

- **TTL (Time to Live)**
  - **Field**: `thread.redis.ttl`
  - **Default**: `2592000` (30 days)
  - **Description**: Thread TTL in seconds (0 disables)
  - **Environment Variable**: `AK_THREAD__REDIS__TTL`

- **Key Prefix**
  - **Field**: `thread.redis.prefix`
  - **Default**: `ak:thread:`
  - **Description**: Key prefix for Redis thread storage
  - **Environment Variable**: `AK_THREAD__REDIS__PREFIX`

##### Valkey Thread Store

Required when `thread.type=valkey`. Requires the `valkey` extra (`pip install "agentkernel[valkey]"`):

- **URL**
  - **Field**: `thread.valkey.url`
  - **Default**: `valkey://localhost:6379`
  - **Description**: Valkey connection URL. Use `valkeys://` for SSL
  - **Environment Variable**: `AK_THREAD__VALKEY__URL`

- **TTL (Time to Live)**
  - **Field**: `thread.valkey.ttl`
  - **Default**: `2592000` (30 days)
  - **Description**: Thread TTL in seconds (0 disables)
  - **Environment Variable**: `AK_THREAD__VALKEY__TTL`

- **Key Prefix**
  - **Field**: `thread.valkey.prefix`
  - **Default**: `ak:thread:`
  - **Description**: Key prefix for Valkey thread storage
  - **Environment Variable**: `AK_THREAD__VALKEY__PREFIX`

##### DynamoDB Thread Store

Used when `thread.type=dynamodb`:

- **Table Name**
  - **Field**: `thread.dynamodb.table_name`
  - **Default**: `ak-agent-threads`
  - **Description**: DynamoDB table name. The table must have a partition key named `session_id` (S) and a sort key named `sk` (S)
  - **Environment Variable**: `AK_THREAD__DYNAMODB__TABLE_NAME`

- **TTL (Time to Live)**
  - **Field**: `thread.dynamodb.ttl`
  - **Default**: `0` (disabled)
  - **Description**: DynamoDB item TTL in seconds
  - **Environment Variable**: `AK_THREAD__DYNAMODB__TTL`

##### Firestore Thread Store

Used when `thread.type=firestore`:

- **Collection Name**
  - **Field**: `thread.firestore.collection_name`
  - **Default**: `ak-agent-threads`
  - **Description**: Firestore collection name; each document ID is a `session_id`
  - **Environment Variable**: `AK_THREAD__FIRESTORE__COLLECTION_NAME`

- **Project ID**
  - **Field**: `thread.firestore.project_id`
  - **Default**: `null` (inferred from Application Default Credentials)
  - **Environment Variable**: `AK_THREAD__FIRESTORE__PROJECT_ID`

- **Database ID**
  - **Field**: `thread.firestore.database_id`
  - **Default**: `null` (the `(default)` database)
  - **Environment Variable**: `AK_THREAD__FIRESTORE__DATABASE_ID`

- **TTL (Time to Live)**
  - **Field**: `thread.firestore.ttl`
  - **Default**: `0` (disabled)
  - **Description**: Thread TTL in seconds
  - **Environment Variable**: `AK_THREAD__FIRESTORE__TTL`

##### Cosmos DB Thread Store

Required when `thread.type=cosmosdb`:

- **Connection String**
  - **Field**: `thread.cosmosdb.connection_string`
  - **Description**: Cosmos DB connection string (Azure Portal → Keys). Uses the Table API; entities are partitioned by `session_id`. No TTL support
  - **Environment Variable**: `AK_THREAD__COSMOSDB__CONNECTION_STRING`

- **Table Name**
  - **Field**: `thread.cosmosdb.table_name`
  - **Default**: `akagentthreads`
  - **Description**: Cosmos DB table name for thread storage
  - **Environment Variable**: `AK_THREAD__COSMOSDB__TABLE_NAME`

#### Scheduling

The presence of a `schedule` block enables deferred and recurring chat execution: a chat request carrying a
`schedule` block (`at` for one-time, `cron` for recurring, plus `timezone` and `session_mode`) is not run —
it is registered as a scheduled task and acknowledged with HTTP 202. When an occurrence is due, the provider
delivers the stored prompt into the input queue as a plain chat request, so scheduling requires the queue
execution pipeline. Agent Kernel also mounts the management routes (`GET`/`PUT`/`DELETE /api/v1/schedules`,
optionally protected by a pluggable `Authoriser`) and injects five agent tools (`create_schedule`,
`list_schedules`, `get_schedule`, `update_schedule`, `delete_schedule`). Every scheduling request needs a
`user_id`: it is the owner the task is stored under and the identity later reads and changes are checked
against. A bare `schedule:` block works for local development — its defaults are the `local` provider and
the `in_memory` store. See `examples/api/schedule-openai`.

- **Provider Type**
  - **Field**: `schedule.provider.type`
  - **Type**: string
  - **Default**: `local`
  - **Options**: `local` (in-process scheduler thread; requires the `in_memory` transport and store),
    `eventbridge` (AWS EventBridge Scheduler; requires the `sqs` transport and the `aws` extra), or a dotted
    path to a `ScheduleProvider` subclass
  - **Environment Variable**: `AK_SCHEDULE__PROVIDER__TYPE`

- **Store Type**
  - **Field**: `schedule.store.type`
  - **Type**: string
  - **Default**: `in_memory`
  - **Options**: `in_memory`, `redis`, `valkey`, `dynamodb`, or a dotted path to a `ScheduleStore` subclass
  - **Environment Variable**: `AK_SCHEDULE__STORE__TYPE`

- **Tool Scoping**
  - **Field**: `schedule.agents`
  - **Type**: list of strings
  - **Default**: `null` (all agents)
  - **Description**: Agent names the schedule tools and system-prompt guidance attach to
  - **Environment Variable**: `AK_SCHEDULE__AGENTS`

##### EventBridge Scheduler Provider

Required when `schedule.provider.type=eventbridge`. All three are supplied by the AWS Terraform modules
when `enable_scheduling = true`; a missing one fails at startup with an `AKConfigError`.

- **Group Name**
  - **Field**: `schedule.provider.eventbridge.group_name`
  - **Description**: EventBridge Scheduler schedule-group name the schedules are created in
  - **Environment Variable**: `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__GROUP_NAME`

- **Role ARN**
  - **Field**: `schedule.provider.eventbridge.role_arn`
  - **Description**: Execution role ARN Scheduler assumes to deliver triggers to the input queue
  - **Environment Variable**: `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__ROLE_ARN`

- **Queue ARN**
  - **Field**: `schedule.provider.eventbridge.queue_arn`
  - **Description**: Input queue ARN used as the schedule target
  - **Environment Variable**: `AK_SCHEDULE__PROVIDER__EVENTBRIDGE__QUEUE_ARN`

##### Redis / Valkey Schedule Store

Required when `schedule.store.type=redis` (or `valkey`, with `schedule.store.valkey.*` / `AK_SCHEDULE__STORE__VALKEY__*`).

- **URL**
  - **Field**: `schedule.store.redis.url`
  - **Default**: `redis://localhost:6379`
  - **Description**: Redis connection URL. Use `rediss://` for SSL
  - **Environment Variable**: `AK_SCHEDULE__STORE__REDIS__URL`

- **Key Prefix**
  - **Field**: `schedule.store.redis.prefix`
  - **Default**: `ak:schedule:`
  - **Description**: Key prefix for scheduled-task storage
  - **Environment Variable**: `AK_SCHEDULE__STORE__REDIS__PREFIX`

- **TTL (Time to Live)**
  - **Field**: `schedule.store.redis.ttl`
  - **Default**: `0` (disabled)
  - **Description**: Scheduled task TTL in seconds. Unlike threads this defaults to 0 — a task that
    silently expired would stop firing with no audit trail
  - **Environment Variable**: `AK_SCHEDULE__STORE__REDIS__TTL`

##### DynamoDB Schedule Store

Required when `schedule.store.type=dynamodb`. The table needs a partition key named `task_id` (S) and no
sort key; the AWS Terraform modules create it when `create_dynamodb_schedule_table = true`.

- **Table Name**
  - **Field**: `schedule.store.dynamodb.table_name`
  - **Default**: `ak-agent-schedules`
  - **Description**: DynamoDB table name for scheduled-task storage
  - **Environment Variable**: `AK_SCHEDULE__STORE__DYNAMODB__TABLE_NAME`

- **TTL (Time to Live)**
  - **Field**: `schedule.store.dynamodb.ttl`
  - **Default**: `0` (disabled)
  - **Description**: DynamoDB item TTL in seconds
  - **Environment Variable**: `AK_SCHEDULE__STORE__DYNAMODB__TTL`

#### Execution Configuration

Configure queue-backed and serverless execution behavior.

- **Execution Mode**
  - **Field**: `execution.mode`
  - **Options**: `rest_sync`, `rest_async`, `stream`, `async`
  - **Default**: `None`
  - **Description**: Selects the execution mode used for queue-backed and serverless request handling
  - **Environment Variable**: `AK_EXECUTION__MODE`

- **Queues**
  - **Field**: `execution.queues`
  - **Description**: Queue settings used by the queue execution pipeline (in-process by default, or serverless/containerized backends)

  - **Transport Type**
    - **Field**: `execution.queues.type`
    - **Options**: `in_memory`, `sqs`, `kafka`, `nats`, or a dotted path to a `QueueTransport` subclass
    - **Default**: none — **mandatory whenever an `execution.queues` block is declared**
    - **Description**: Queue transport used by the pipeline, and the only thing that selects it: queue coordinates are injected per component by a deployment, so they are never used to infer the transport. Declaring the block without a `type` is a configuration error. Omitting the block entirely leaves `in_memory` — a zero-dependency, in-process transport for local development and single-process deployments.
    - **Environment Variable**: `AK_EXECUTION__QUEUES__TYPE`

  - **Input Queue URL**
    - **Field**: `execution.queues.input.url`
    - **Default**: `None`
    - **Description**: Input queue URL (`sqs` transport only)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__INPUT__URL`

  - **Output Queue URL**
    - **Field**: `execution.queues.output.url`
    - **Default**: `None`
    - **Description**: Output queue URL (`sqs` transport only)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__OUTPUT__URL`

  - **Input Queue Max Receive Count**
    - **Field**: `execution.queues.input.max_receive_count`
    - **Default**: `3`
    - **Environment Variable**: `AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT`

  - **Output Queue Max Receive Count**
    - **Field**: `execution.queues.output.max_receive_count`
    - **Default**: `3`
    - **Environment Variable**: `AK_EXECUTION__QUEUES__OUTPUT__MAX_RECEIVE_COUNT`

  - **Input Queue Consumer Count**
    - **Field**: `execution.queues.input.no_of_consumers`
    - **Default**: `5`
    - **Description**: Number of independent consumer threads that each poll the input queue in a continuous loop. Used by the in-process pipeline (agent-runner worker threads) and by ECS containerized deployments; not used in serverless (Lambda) mode, which has no consumer threads.
    - **Environment Variable**: `AK_EXECUTION__QUEUES__INPUT__NO_OF_CONSUMERS`

  - **Output Queue Consumer Count**
    - **Field**: `execution.queues.output.no_of_consumers`
    - **Default**: `5`
    - **Description**: Number of independent consumer threads that each poll the output queue in a continuous loop. Used by the in-process pipeline (response-handler worker threads) and by ECS containerized deployments; not used in serverless (Lambda) mode, which has no consumer threads.
    - **Environment Variable**: `AK_EXECUTION__QUEUES__OUTPUT__NO_OF_CONSUMERS`

  - **In-Memory Transport Ack Wait**
    - **Field**: `execution.queues.in_memory.ack_wait`
    - **Default**: `300.0`
    - **Description**: Seconds an unacknowledged in-memory message stays invisible before redelivery. Redelivery rescues stuck worker threads; keep this above your longest expected agent run or a slow run will be executed again.

  - **In-Memory Transport Dedup Window**
    - **Field**: `execution.queues.in_memory.dedup_window`
    - **Default**: `300.0`
    - **Description**: Seconds within which a repeated `message_deduplication_id` is dropped

  - **Kafka Bootstrap Servers**
    - **Field**: `execution.queues.kafka.bootstrap_servers`
    - **Default**: `localhost:9092`
    - **Description**: Kafka bootstrap servers (host:port, comma-separated)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__BOOTSTRAP_SERVERS`

  - **Kafka Input Topic**
    - **Field**: `execution.queues.kafka.input_topic`
    - **Default**: `agent-input`
    - **Description**: Topic carrying chat requests
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__INPUT_TOPIC`

  - **Kafka Output Topic**
    - **Field**: `execution.queues.kafka.output_topic`
    - **Default**: `agent-output`
    - **Description**: Topic carrying agent replies
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__OUTPUT_TOPIC`

  - **Kafka Consumer Group Id**
    - **Field**: `execution.queues.kafka.group_id`
    - **Default**: `agent-kernel`
    - **Description**: Consumer group id prefix; the input and output consumers append their queue name to it
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__GROUP_ID`

  - **Kafka Dead-Letter Topic Suffix**
    - **Field**: `execution.queues.kafka.dlq_suffix`
    - **Default**: `.dlq`
    - **Description**: Suffix appended to a topic name for its dead-letter topic, where permanently failed records are routed
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__DLQ_SUFFIX`

  - **Kafka Retry Backoff**
    - **Field**: `execution.queues.kafka.retry_backoff`
    - **Default**: `2.0`
    - **Description**: Seconds to wait before an in-process retry of a failed record
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__RETRY_BACKOFF`

  - **Kafka Delivery Timeout**
    - **Field**: `execution.queues.kafka.delivery_timeout`
    - **Default**: `30.0`
    - **Description**: Seconds to wait for the broker to confirm a produced message before failing the send
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__DELIVERY_TIMEOUT`

  - **Kafka Metadata Timeout**
    - **Field**: `execution.queues.kafka.metadata_timeout`
    - **Default**: `5.0`
    - **Description**: Seconds to wait for topic metadata during the startup partition-capacity check (the check is skipped on timeout)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__KAFKA__METADATA_TIMEOUT`

  - **Kafka Client Config**
    - **Field**: `execution.queues.kafka.client_config`
    - **Default**: `{}`
    - **Description**: Passthrough settings merged into the `confluent-kafka` producer and consumer configs (SASL, TLS, tuning); set via `config.yaml`, not individually exported as environment variables

  - **NATS Server URL**
    - **Field**: `execution.queues.nats.url`
    - **Default**: `nats://localhost:4222`
    - **Description**: NATS server URL (comma-separated for a cluster)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__URL`

  - **NATS Input Stream**
    - **Field**: `execution.queues.nats.input_stream`
    - **Default**: `AGENT_REQUESTS`
    - **Description**: JetStream stream carrying chat requests
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__INPUT_STREAM`

  - **NATS Input Subject Prefix**
    - **Field**: `execution.queues.nats.input_subject_prefix`
    - **Default**: `chat.req`
    - **Description**: Subject prefix for chat requests
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__INPUT_SUBJECT_PREFIX`

  - **NATS Output Stream**
    - **Field**: `execution.queues.nats.output_stream`
    - **Default**: `AGENT_REPLIES`
    - **Description**: JetStream stream carrying agent replies
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__OUTPUT_STREAM`

  - **NATS Output Subject Prefix**
    - **Field**: `execution.queues.nats.output_subject_prefix`
    - **Default**: `chat.out`
    - **Description**: Subject prefix for agent replies
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__OUTPUT_SUBJECT_PREFIX`

  - **NATS Partitions**
    - **Field**: `execution.queues.nats.partitions`
    - **Default**: `32`
    - **Description**: Number of partition subjects per stream, each served by its own durable consumer. Sessions hash to a partition, so this caps how many messages can be in flight at once: keep it at or above `no_of_consumers` x replicas. Changing it re-maps sessions, so size it up front (idle partitions cost almost nothing)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__PARTITIONS`

  - **NATS Ack Wait**
    - **Field**: `execution.queues.nats.ack_wait`
    - **Default**: `300.0`
    - **Description**: Seconds the server waits for an acknowledgement before redelivering. Must exceed your longest agent turn: a turn that outlives it is redelivered and executed a second time
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__ACK_WAIT`

  - **NATS Retry Backoff**
    - **Field**: `execution.queues.nats.retry_backoff`
    - **Default**: `2.0`
    - **Description**: Seconds to delay a redelivery after a failed message (nak delay)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__RETRY_BACKOFF`

  - **NATS Duplicate Window**
    - **Field**: `execution.queues.nats.duplicate_window`
    - **Default**: `300.0`
    - **Description**: Seconds within which a repeated dedup id is dropped by the stream (SQS parity)
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__DUPLICATE_WINDOW`

  - **NATS Max Age**
    - **Field**: `execution.queues.nats.max_age`
    - **Default**: `86400.0`
    - **Description**: Seconds before an unconsumed message is discarded. A safety net: work-queue messages are otherwise kept forever
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__MAX_AGE`

  - **NATS Request Timeout**
    - **Field**: `execution.queues.nats.request_timeout`
    - **Default**: `10.0`
    - **Description**: Seconds to wait for a NATS request (publish, ack, management call) to complete
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__REQUEST_TIMEOUT`

  - **NATS Auto Provision**
    - **Field**: `execution.queues.nats.auto_provision`
    - **Default**: `false`
    - **Description**: Create the streams and per-partition consumers at startup if missing. Convenient for local and dev clusters; leave false in production, where the objects are managed declaratively (NACK CRs) and a missing object should fail loudly instead of being created with defaults
    - **Environment Variable**: `AK_EXECUTION__QUEUES__NATS__AUTO_PROVISION`

  - **Queue Batch Size**
    - **Field**: `execution.queues.batch_size`
    - **Default**: `None`
    - **Description**: Max number of messages fetched per receive call, shared by the input and output queues. Only used by containerized deployments — never set for serverless deployments, which control batch size differently. Controlled by the deployment tooling via env var `AK_EXECUTION__QUEUES__BATCH_SIZE` — do not set in `config.yaml`.
    - **Environment Variable**: `AK_EXECUTION__QUEUES__BATCH_SIZE`

- **Response Store**
  - **Field**: `execution.response_store`
  - **Description**: Response persistence settings used by the serverless response handler

  - **Type**
    - **Field**: `execution.response_store.type`
    - **Options**: `in_memory`, `redis`, `valkey`, `dynamodb`, or a dotted path to a `ResponseStore` subclass
    - **Description**: Response store backend selector configured in `config.yaml`; this value is not exported as an environment variable. Defaults to an in-process `in_memory` store when unset and no other backend is configured.

  - **Retry Count**
    - **Field**: `execution.response_store.retry_count`
    - **Default**: `5`
    - **Description**: Number of lookup attempts when polling for a response
    - **Environment Variable**: `AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT`

  - **Delay**
    - **Field**: `execution.response_store.delay`
    - **Default**: `5`
    - **Description**: Delay in seconds between response lookup attempts
    - **Environment Variable**: `AK_EXECUTION__RESPONSE_STORE__DELAY`

  - **Redis Backend**
    - **Field**: `execution.response_store.redis`
    - **Environment Variables**: `AK_EXECUTION__RESPONSE_STORE__REDIS__URL`, `AK_EXECUTION__RESPONSE_STORE__REDIS__PREFIX`, `AK_EXECUTION__RESPONSE_STORE__REDIS__TTL`

  - **Valkey Backend**
    - **Field**: `execution.response_store.valkey`
    - **Environment Variables**: `AK_EXECUTION__RESPONSE_STORE__VALKEY__URL`, `AK_EXECUTION__RESPONSE_STORE__VALKEY__PREFIX`, `AK_EXECUTION__RESPONSE_STORE__VALKEY__TTL`
    - **Description**: Valkey-backed response storage (requires the `agentkernel[valkey]` extra)

  - **DynamoDB Backend**
    - **Field**: `execution.response_store.dynamodb`
    - **Environment Variables**: `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME`, `AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TTL`
    - **Description**: DynamoDB-backed response storage with table name and TTL

Use the built-in `in_memory` response store for local development and single-process deployments (zero extra services required), or Redis, Valkey, or DynamoDB for distributed/serverless deployments. The runtime accepts `BaseRunRequest` payloads directly, normalizes them internally when queueing is required, and uses `request_id` plus optional `user_id` as queue message attributes.

#### API Configuration

Configure the REST API server (if using the API module).

- **Host**
  - **Field**: `api.host`
  - **Default**: `0.0.0.0`
  - **Environment Variable**: `AK_API__HOST`

- **Port**
  - **Field**: `api.port`
  - **Default**: `8000`
  - **Environment Variable**: `AK_API__PORT`

- **Custom Router Prefix**
  - **Field**: `api.custom_router_prefix`
  - **Default**: `/custom`
  - **Environment Variable**: `AK_API__CUSTOM_ROUTER_PREFIX`

- **Enabled Routes**
  - **Field**: `api.enabled_routes.agents`
  - **Default**: `true`
  - **Description**: Enable agent interaction routes
  - **Environment Variable**: `AK_API__ENABLED_ROUTES__AGENTS`

#### A2A (Agent-to-Agent) Configuration

- **Enabled**
  - **Field**: `a2a.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_A2A__ENABLED`

- **Agents**
  - **Field**: `a2a.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to enable A2A (use `["*"]` for all)
  - **Environment Variable**: `AK_A2A__AGENTS` (comma-separated)

- **URL**
  - **Field**: `a2a.url`
  - **Default**: `http://localhost:8000/a2a`
  - **Environment Variable**: `AK_A2A__URL`

- **Task Store Type**
  - **Field**: `a2a.task_store_type`
  - **Options**: `in_memory`, `redis`
  - **Default**: `in_memory`
  - **Environment Variable**: `AK_A2A__TASK_STORE_TYPE`

#### MCP (Model Context Protocol) Configuration

- **Enabled**
  - **Field**: `mcp.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_MCP__ENABLED`

- **Expose Agents**
  - **Field**: `mcp.expose_agents`
  - **Default**: `false`
  - **Description**: Expose agents as MCP tools
  - **Environment Variable**: `AK_MCP__EXPOSE_AGENTS`

- **Agents**
  - **Field**: `mcp.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to expose as MCP tools
  - **Environment Variable**: `AK_MCP__AGENTS` (comma-separated)

- **Stateless HTTP**
  - **Field**: `mcp.stateless_http`
  - **Default**: `false`
  - **Description**: Run MCP in stateless HTTP mode (no `Mcp-Session-Id`)
  - **Environment Variable**: `AK_MCP__STATELESS_HTTP`

- **Endpoint** (not configurable)
  - The MCP server is always mounted at `/mcp` on the main API server.
  - Full URL: `http://{api.host}:{api.port}/mcp` — use `api.port` / `AK_API__PORT` to change the port.

#### Trace (Observability) Configuration

Configure tracing and observability for monitoring agent execution.

- **Enabled**
  - **Field**: `trace.enabled`
  - **Default**: `false`
  - **Description**: Enable tracing/observability
  - **Environment Variable**: `AK_TRACE__ENABLED`

- **Type**
  - **Field**: `trace.type`
  - **Options**: `langfuse`, `openllmetry`, `logfire`
  - **Default**: `langfuse`
  - **Description**: Type of tracing provider to use
  - **Environment Variable**: `AK_TRACE__TYPE`

**Langfuse Setup:**

To use Langfuse for tracing, install the langfuse extra:

```bash
pip install agentkernel[langfuse]
```

Configure Langfuse credentials via environment variables:

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance
```

Enable tracing in your configuration:

```yaml
trace:
  enabled: true
  type: langfuse
```

**OpenLLMetry (Traceloop) Setup:**

To use OpenLLMetry for tracing, install the openllmetry extra:

```bash
pip install agentkernel[openllmetry]
```

Configure Traceloop credentials via environment variables:

```bash
export TRACELOOP_API_KEY=your-api-key
export TRACELOOP_BASE_URL=https://api.traceloop.com  # Optional: for self-hosted
```

Enable tracing in your configuration:

```yaml
trace:
  enabled: true
  type: openllmetry
```

**Pydantic Logfire Setup:**

To use Logfire for tracing, install the logfire extra:

```bash
pip install agentkernel[logfire]
```

Configure the Logfire write token via an environment variable (optional — without a token, Logfire
runs locally and does not ship traces):

```bash
export LOGFIRE_TOKEN=your-write-token
```

Enable tracing in your configuration:

```yaml
trace:
  enabled: true
  type: logfire
```

#### Test Configuration

Configure test comparison modes for automated testing. Test configuration is separate from the application configuration: it is **not** part of `config.yaml`. It lives in its own `test-config.yaml` file and is only loaded when the testing utilities (`agentkernel.test`) are used — see the [Test Configuration (test-config.yaml)](#test-configuration-test-configyaml) section for file resolution, environment variables, and migration notes.

- **Mode**
  - **Field**: `mode`
  - **Options**: `fuzzy`, `judge`, `fallback`
  - **Default**: `fallback`
  - **Description**: Test comparison mode
  - **Environment Variable**: `AK_TEST__MODE`

- **Judge Model**
  - **Field**: `judge.model`
  - **Default**: `gpt-4o-mini`
  - **Description**: LLM model for judge evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__MODEL`

- **Judge Provider**
  - **Field**: `judge.provider`
  - **Default**: `openai`
  - **Description**: LLM provider for judge evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__PROVIDER`

- **Judge Embedding Model**
  - **Field**: `judge.embedding_model`
  - **Default**: `text-embedding-3-small`
  - **Description**: Embedding model for similarity evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__EMBEDDING_MODEL`

**Test Modes:**
- `fuzzy`: Uses fuzzy string matching (RapidFuzz)
- `judge`: Uses LLM-based evaluation (Ragas) for semantic similarity
- `fallback`: Tries fuzzy first, falls back to judge if fuzzy fails

```yaml
# test-config.yaml (separate file — not config.yaml)
mode: fallback
judge:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```

#### Guardrails Configuration

Configure input and output guardrails to validate agent requests and responses for safety and compliance.

- **Input Guardrails**
  - **Enabled**
    - **Field**: `guardrail.input.enabled`
    - **Default**: `false`
    - **Description**: Enable input validation guardrails
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__ENABLED`

  - **Type**
    - **Field**: `guardrail.input.type`
    - **Default**: `openai`
    - **Options**: `openai`, `bedrock`, `walledai`
    - **Description**: Guardrail provider type
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__TYPE`

  - **Config Path**
    - **Field**: `guardrail.input.config_path`
    - **Default**: `None`
    - **Description**: Path to guardrail configuration JSON file (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__CONFIG_PATH`

  - **Model**
    - **Field**: `guardrail.input.model`
    - **Default**: `gpt-4o-mini`
    - **Description**: LLM model to use for guardrail validation (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__MODEL`

  - **ID**
    - **Field**: `guardrail.input.id`
    - **Default**: `None`
    - **Description**: AWS Bedrock guardrail ID (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__ID`

  - **Version**
    - **Field**: `guardrail.input.version`
    - **Default**: `DRAFT`
    - **Description**: AWS Bedrock guardrail version (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__VERSION`

- **Output Guardrails**
  - **Enabled**
    - **Field**: `guardrail.output.enabled`
    - **Default**: `false`
    - **Description**: Enable output validation guardrails
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__ENABLED`

  - **Type**
    - **Field**: `guardrail.output.type`
    - **Default**: `openai`
    - **Options**: `openai`, `bedrock`, `walledai`
    - **Description**: Guardrail provider type
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__TYPE`

  - **Config Path**
    - **Field**: `guardrail.output.config_path`
    - **Default**: `None`
    - **Description**: Path to guardrail configuration JSON file (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__CONFIG_PATH`

  - **Model**
    - **Field**: `guardrail.output.model`
    - **Default**: `gpt-4o-mini`
    - **Description**: LLM model to use for guardrail validation (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__MODEL`

  - **ID**
    - **Field**: `guardrail.output.id`
    - **Default**: `None`
    - **Description**: AWS Bedrock guardrail ID (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__ID`

  - **Version**
    - **Field**: `guardrail.output.version`
    - **Default**: `DRAFT`
    - **Description**: AWS Bedrock guardrail version (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__VERSION`

**Guardrail Setup:**

To use OpenAI guardrails, install the openai-guardrails package:

```bash
pip install agentkernel[openai]
```

To use AWS Bedrock guardrails, install the AWS package:

```bash
pip install agentkernel[aws]
```

To use Walled AI guardrails, install the Walled AI package:

```bash
pip install agentkernel[walledai]
```

Create guardrail configuration:

**For OpenAI:** Create configuration files following the [OpenAI Guardrails format](https://guardrails.openai.com/).

**For Bedrock:** Create a guardrail in AWS Bedrock and note the guardrail ID and version.

**For Walled AI:** Set `WALLED_API_KEY`, use guardrail type `walledai`, and control PII masking with `pii`.

Configure guardrails in your configuration:

**OpenAI Example:**
```yaml
guardrail:
  input:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_input.json
  output:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_output.json
```

**Bedrock Example:**
```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"  # or "DRAFT"
  output:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"
```

**Walled AI Example:**
```yaml
guardrail:
  input:
    enabled: true
    type: walledai
    pii: true
  output:
    enabled: true
    type: walledai
    pii: true
```

#### Sandbox Configuration

Enable the sandbox capability to let agents execute code and shell commands in an isolated,
permission-bounded environment. When enabled, agents automatically gain sandbox tools
(`run_code`, `run_command`, `write_sandbox_file`, `read_sandbox_file`, `check_sandbox_task`,
`list_sandbox_sessions`, `new_sandbox_session`, `destroy_sandbox_session`) and the usage
guidance is injected into their system prompt.

Minimal single-backend form (a `default` profile is synthesized from `type` + its config block):

```yaml
sandbox:
  enabled: true
  type: local_subprocess        # provider short name, or a dotted path to a SandboxProvider subclass
  local_subprocess: {}
  broker:
    flavor: thread              # thread (local default) | embedded
```

Full form with explicit workload profiles (provider + lifetime + policy + identity):

```yaml
sandbox:
  enabled: true
  agents: [coder]               # optional: attach tools/prompt only to these agents; omit = all
  default_profile: workspace
  principal_resolver: null      # optional dotted path to a PrincipalResolver; null = agent identity
  tool_output_max_chars: 8000
  broker:
    flavor: thread
    wait_timeout: 60.0          # seconds before a sync wait promotes to a background task (0 = always)
  profiles:
    workspace:
      type: docker              # container-isolated; needs the sandbox-docker extra + a Docker daemon
      scope: per_session        # per_call | per_session | per_runtime
      idle_timeout: 1800        # seconds of inactivity before the sandbox is reset on next touch
      identity:
        mode: agent             # agent | user
      policy:
        network_egress: deny    # allow | deny | allowlist
        cpu: 1.0
        memory_mb: 512
        timeout: 30.0           # per-execution wall-clock seconds (always enforced)
        strict: true            # fail closed when the provider can't enforce a policy dimension
      docker:
        image: python:3.12-slim
```

Key fields:

- **`enabled`** (`AK_SANDBOX__ENABLED`, default `false`) — master switch; inert when off.
- **`agents`** — agent names the tools/prompt attach to; omit for all agents.
- **`type`** (per profile) — `local_subprocess` (no isolation; dev/test), `docker`
  (container isolation; `sandbox-docker` extra), `e2b` (managed micro-VMs; `e2b` extra),
  `daytona` (cloud containers; `daytona` extra), `ec2_ssm` (attach to an existing EC2
  instance via SSM; `aws` extra), or a dotted path to your own `SandboxProvider`.
- **`scope`** — `per_call` (fresh per execution), `per_session` (persists across turns),
  `per_runtime` (one shared sandbox per profile).
- **`environment`** — `managed` (default; the provider creates and disposes sandboxes) or
  `attached` (deliberately connect to an existing environment the framework never owns,
  e.g. an EC2 instance via `ec2_ssm`; requires the provider's `attach_to` and is validated
  against the provider's lifecycle capabilities at startup).
- **`policy`** — network egress, filesystem paths, cpu/memory, timeout; enforced per provider,
  fail-closed under `strict`.
- **`identity.mode`** + **`principal_resolver`** — run code under the agent's or the invoking
  user's identity.
- **`broker.flavor`** — `thread` (default, for CLI/REST) or `embedded` (inline/synchronous).

See the [Sandbox guide](https://kernel.yaala.ai/docs/advanced/sandbox) for the full
reference and the `examples/sandbox` and `examples/sandbox/identity` examples.

#### Messaging Platform Integrations

Configure integrations with messaging platforms.

##### Slack

- **Agent**
  - **Field**: `slack.agent`
  - **Default**: `""`
  - **Description**: Default agent for Slack interactions
  - **Environment Variable**: `AK_SLACK__AGENT`

- **Agent Acknowledgement**
  - **Field**: `slack.agent_acknowledgement`
  - **Default**: `""`
  - **Description**: Acknowledgement message when Slack message is received
  - **Environment Variable**: `AK_SLACK__AGENT_ACKNOWLEDGEMENT`

##### WhatsApp

- **Agent**
  - **Field**: `whatsapp.agent`
  - **Default**: `""`
  - **Description**: Default agent for WhatsApp interactions
  - **Environment Variable**: `AK_WHATSAPP__AGENT`

- **Verify Token**, **Access Token**, **App Secret**, **Phone Number ID**, **API Version**
  - **Environment Variables**: `AK_WHATSAPP__VERIFY_TOKEN`, `AK_WHATSAPP__ACCESS_TOKEN`, `AK_WHATSAPP__APP_SECRET`, `AK_WHATSAPP__PHONE_NUMBER_ID`, `AK_WHATSAPP__API_VERSION`

##### Facebook Messenger

- **Agent**
  - **Field**: `messenger.agent`
  - **Default**: `""`
  - **Description**: Default agent for Facebook Messenger interactions
  - **Environment Variable**: `AK_MESSENGER__AGENT`

- **Verify Token**, **Access Token**, **App Secret**, **API Version**
  - **Environment Variables**: `AK_MESSENGER__VERIFY_TOKEN`, `AK_MESSENGER__ACCESS_TOKEN`, `AK_MESSENGER__APP_SECRET`, `AK_MESSENGER__API_VERSION`

##### Instagram

- **Agent**
  - **Field**: `instagram.agent`
  - **Default**: `""`
  - **Description**: Default agent for Instagram interactions
  - **Environment Variable**: `AK_INSTAGRAM__AGENT`

- **Instagram Account ID**, **Verify Token**, **Access Token**, **App Secret**, **API Version**
  - **Environment Variables**: `AK_INSTAGRAM__INSTAGRAM_ACCOUNT_ID`, `AK_INSTAGRAM__VERIFY_TOKEN`, `AK_INSTAGRAM__ACCESS_TOKEN`, `AK_INSTAGRAM__APP_SECRET`, `AK_INSTAGRAM__API_VERSION`

##### Telegram

- **Agent**
  - **Field**: `telegram.agent`
  - **Default**: `""`
  - **Description**: Default agent for Telegram interactions
  - **Environment Variable**: `AK_TELEGRAM__AGENT`

- **Bot Token**, **Webhook Secret**, **API Version**
  - **Environment Variables**: `AK_TELEGRAM__BOT_TOKEN`, `AK_TELEGRAM__WEBHOOK_SECRET`, `AK_TELEGRAM__API_VERSION`

##### Gmail

- **Agent**
  - **Field**: `gmail.agent`
  - **Default**: `"general"`
  - **Description**: Default agent for Gmail interactions
  - **Environment Variable**: `AK_GMAIL__AGENT`

- **Client ID**, **Client Secret**, **Token File**, **Poll Interval**, **Label Filter**
  - **Environment Variables**: `AK_GMAIL__CLIENT_ID`, `AK_GMAIL__CLIENT_SECRET`, `AK_GMAIL__TOKEN_FILE`, `AK_GMAIL__POLL_INTERVAL`, `AK_GMAIL__LABEL_FILTER`

### Configuration Examples

#### Environment Variables

Use the `AK_` prefix and underscores for nested fields:

```bash
export AK_DEBUG=true
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
export AK_SESSION__REDIS__TTL=604800
export AK_SESSION__REDIS__PREFIX=ak:sessions:
export AK_API__HOST=0.0.0.0
export AK_API__PORT=8000
export AK_A2A__ENABLED=true
export AK_MCP__ENABLED=false
export AK_TRACE__ENABLED=true
export AK_TRACE__TYPE=langfuse  # or openllmetry, logfire
# For Langfuse:
# export LANGFUSE_PUBLIC_KEY=pk-lf-...
# export LANGFUSE_SECRET_KEY=sk-lf-...
# export LANGFUSE_HOST=https://cloud.langfuse.com
# For OpenLLMetry:
# export TRACELOOP_API_KEY=your-api-key
# For Logfire:
# export LOGFIRE_TOKEN=your-write-token
# Test harness (loaded from the separate test-config.yaml — see Test Configuration)
export AK_TEST__MODE=fallback  # Options: fuzzy, judge, fallback
export AK_TEST__JUDGE__MODEL=gpt-4o-mini
export AK_TEST__JUDGE__PROVIDER=openai
export AK_TEST__JUDGE__EMBEDDING_MODEL=text-embedding-3-small
# Guardrails configuration
export AK_GUARDRAIL__INPUT__ENABLED=false
export AK_GUARDRAIL__INPUT__TYPE=openai
export AK_GUARDRAIL__INPUT__MODEL=gpt-4o-mini
export AK_GUARDRAIL__INPUT__CONFIG_PATH=/path/to/guardrails_input.json
export AK_GUARDRAIL__OUTPUT__ENABLED=false
export AK_GUARDRAIL__OUTPUT__TYPE=openai
export AK_GUARDRAIL__OUTPUT__MODEL=gpt-4o-mini
export AK_GUARDRAIL__OUTPUT__CONFIG_PATH=/path/to/guardrails_output.json
# Walled AI guardrails
export WALLED_API_KEY=your-walledai-api-key
export AK_GUARDRAIL__INPUT__PII=true
export AK_GUARDRAIL__OUTPUT__PII=true
export AK_DEBUG=true
# Messaging platforms (optional)
export AK_SLACK__AGENT=my-agent
export AK_WHATSAPP__AGENT=my-agent
export AK_MESSENGER__AGENT=my-agent
export AK_INSTAGRAM__AGENT=my-agent
export AK_TELEGRAM__AGENT=my-agent
export AK_GMAIL__AGENT=my-agent
export AK_GMAIL__CLIENT_ID=your-google-client-id
export AK_GMAIL__CLIENT_SECRET=your-google-client-secret
```

#### .env File

Create a `.env` file in your working directory:

```env
AK_DEBUG=false
AK_SESSION__TYPE=redis
AK_SESSION__REDIS__URL=rediss://my-redis:6379
AK_SESSION__REDIS__TTL=1209600
AK_SESSION__REDIS__PREFIX=ak:prod:sessions:
AK_API__HOST=0.0.0.0
AK_API__PORT=8080
AK_A2A__ENABLED=true
AK_A2A__URL=http://localhost:8080/a2a
AK_TRACE__ENABLED=true
AK_TRACE__TYPE=langfuse  # or openllmetry, logfire
# Langfuse credentials (if using langfuse):
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://cloud.langfuse.com
# OpenLLMetry credentials (if using openllmetry):
# TRACELOOP_API_KEY=your-api-key
# Logfire credentials (if using logfire):
# LOGFIRE_TOKEN=your-write-token
```

#### config.yaml

```yaml
session:
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 604800
    prefix: "ak:sessions:"
thread: # optional; configures Conversation Thread Support (enabled by mounting AgentThreadRequestHandler)
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 2592000
    prefix: "ak:thread:"
execution:
  mode: rest_sync
  queues:
    type: sqs # in_memory | sqs | kafka | nats, or a dotted path to a QueueTransport subclass — mandatory whenever this block is declared
    input:
      url: https://queue.example.com/<accountno>/<queuename> # sqs transport only
      max_receive_count: 3
      no_of_consumers: 5 # in-process pipeline + containerized deployments, ignored by serverless deployments
    output:
      url: https://queue.example.com/<accountno>/<queuename> # sqs transport only
      max_receive_count: 3
      no_of_consumers: 5 # in-process pipeline + containerized deployments, ignored by serverless deployments
    # in_memory: {ack_wait: 300.0, dedup_window: 300.0}  # in_memory transport settings, unused otherwise
    # kafka:  # kafka transport settings, unused otherwise
    #   bootstrap_servers: localhost:9092
    #   input_topic: agent-input
    #   output_topic: agent-output
    #   group_id: agent-kernel
    #   dlq_suffix: .dlq
    #   retry_backoff: 2.0
    #   delivery_timeout: 30.0
    #   metadata_timeout: 5.0
    #   client_config: {} # passthrough confluent-kafka producer/consumer settings (SASL, TLS, tuning)
    # nats:  # nats transport settings, unused otherwise
    #   url: nats://localhost:4222
    #   input_stream: AGENT_REQUESTS
    #   input_subject_prefix: chat.req
    #   output_stream: AGENT_REPLIES
    #   output_subject_prefix: chat.out
    #   partitions: 32
    #   ack_wait: 300.0
    #   retry_backoff: 2.0
    #   duplicate_window: 300.0
    #   max_age: 86400.0
    #   request_timeout: 10.0
    #   auto_provision: false # true for local/dev; leave false where NACK CRs own the objects
    # batch_size is set by the deployment tooling — set via AK_EXECUTION__QUEUES__BATCH_SIZE, never here
  response_store:
    type: redis # in_memory | redis | valkey | dynamodb | dotted path — omit for the built-in in_memory store
    retry_count: 5
    delay: 5
    redis: # if this is given, then valkey/dynamodb response store parts cannot be given
      url: redis://localhost:6379
      prefix: "ak:responses:"
      ttl: 3600
    valkey: # if this is given, then redis/dynamodb response store parts cannot be given (requires the `valkey` extra)
      url: valkey://localhost:6379
      prefix: "ak:responses:"
      ttl: 3600
    dynamodb: # if this is given, then redis/valkey response store parts cannot be given
      table_name: table-name
      table_arn: table-arn
      ttl: 3600
api:
  host: 0.0.0.0
  port: 8000
  enabled_routes:
    agents: true
a2a:
  enabled: true
  agents: ["*"]
  url: http://localhost:8000/a2a
  task_store_type: in_memory
mcp:
  enabled: false
  expose_agents: false
  agents: ["*"]
trace:
  enabled: true
  type: langfuse
# Note: test configuration is no longer set here — it lives in a separate
# test-config.yaml file (see the Test Configuration section)
guardrail:
  input:
    enabled: false
    type: openai
    pii: true
    model: gpt-4o-mini
    config_path: /path/to/guardrails_input.json
  output:
    enabled: false
    type: openai
    pii: true
    model: gpt-4o-mini
    config_path: /path/to/guardrails_output.json
  # For Walled AI, set type: walledai, WALLED_API_KEY,
  # and optionally use input/output pii (default: true) to enable/disable PII masking.
slack:
  agent: my-agent
  agent_acknowledgement: "Processing your request..."
whatsapp:
  agent: my-agent
  agent_acknowledgement: "Processing..."
messenger:
  agent: my-agent
instagram:
  agent: my-agent
telegram:
  agent: my-agent
gmail:
  agent: my-agent
  poll_interval: 30
  label_filter: "INBOX"
```

#### config.json

```json
{
  "debug": false,
  "session": {
    "type": "redis",
    "redis": {
      "url": "redis://localhost:6379",
      "ttl": 604800,
      "prefix": "ak:sessions:"
    }
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "enabled_routes": {
      "agents": true
    }
  },
  "a2a": {
    "enabled": true,
    "agents": ["*"],
    "url": "http://localhost:8000/a2a",
    "task_store_type": "in_memory"
  },
  "mcp": {
    "enabled": false,
    "expose_agents": false,
    "agents": ["*"]
  },
  "trace": {
    "enabled": true,
    "type": "langfuse"
  },
  "guardrail": {
    "input": {
      "enabled": false,
      "type": "openai",
      "model": "gpt-4o-mini",
      "config_path": "/path/to/guardrails_input.json"
    },
    "output": {
      "enabled": false,
      "type": "openai",
      "model": "gpt-4o-mini",
      "config_path": "/path/to/guardrails_output.json"
    }
  },
  "slack": {
    "agent": "my-agent",
    "agent_acknowledgement": "Processing your request..."
  },
  "whatsapp": {
    "agent": "my-agent",
    "agent_acknowledgement": "Processing..."
  },
  "messenger": {
    "agent": "my-agent"
  },
  "instagram": {
    "agent": "my-agent"
  },
  "telegram": {
    "agent": "my-agent"
  },
  "gmail": {
    "agent": "my-agent",
    "poll_interval": 30,
    "label_filter": "INBOX"
  }
}
```

### Configuration Notes

- Empty environment variables are ignored
- Unknown fields in files or environment variables are ignored
- Environment variables override configuration file values
- Configuration file values override built-in defaults
- Nested fields use underscore (`_`) delimiter in environment variables

### Test Configuration (test-config.yaml)

Test harness configuration (comparison mode and judge models) is separate from the application configuration. It is not part of `config.yaml` — it lives in its own `test-config.yaml` file, resolved from the current working directory, and is only loaded when the testing utilities (`agentkernel.test`) are used. A legacy `test:` section in `config.yaml` is ignored. See [Test Configuration](#test-configuration) under Configuration Options for the full list of fields and defaults.

**test-config.yaml:**

```yaml
mode: fallback
judge:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```

Note that the file is un-nested — there is no top-level `test:` key. If the file is missing, defaults apply silently (fuzzy and fallback tests need no configuration file at all).

**Override the test config file path:**

```bash
export AK_TEST_CONFIG_PATH_OVERRIDE=/path/to/test-config.yaml
```

**Environment variables** use the `AK_TEST__` prefix and override `test-config.yaml` values:

```bash
export AK_TEST__MODE=fallback  # Options: fuzzy, judge, fallback
export AK_TEST__JUDGE__MODEL=gpt-4o-mini
export AK_TEST__JUDGE__PROVIDER=openai
export AK_TEST__JUDGE__EMBEDDING_MODEL=text-embedding-3-small
```

> **Migration note:** Earlier versions read test configuration from a `test:` section in `config.yaml`. That section is now ignored — move its contents (un-nested, without the `test:` key) to a sibling `test-config.yaml`. The `AK_TEST__*` environment variables are unchanged, so CI pipelines that use them need no updates.

## Extensibility

### Custom Framework Adapters

To add support for a new framework:

1. Implement a `Runner` class for your framework
2. Create an `Agent` wrapper class
3. Create a `Module` class that registers agents with the Runtime

Example structure:

```python
from agentkernel.core import Agent, Runner, Module

class MyFrameworkRunner(Runner):
    def run(self, agent, prompt, session):
        # Implement framework-specific execution
        pass

class MyFrameworkAgent(Agent):
    def __init__(self, native_agent):
        self.native_agent = native_agent
        self.runner = MyFrameworkRunner()

class MyFrameworkModule(Module):
    def __init__(self, agents):
        super().__init__()
        for agent in agents:
            wrapped = MyFrameworkAgent(agent)
            self.register(wrapped)
```

### Session Management

Sessions maintain state across agent interactions. Framework adapters manage their own session storage within the Session object using namespaced keys:

- `"crewai"` — CrewAI session data
- `"langgraph"` — LangGraph session data
- `"openai"` — OpenAI Agents SDK session data
- `"adk"` — Google ADK session data
- `"pydanticai"` — Pydantic AI session data (message history)

Access the session in your runner:

```python
def run(self, agent, prompt, session):
    # Get framework-specific data
    my_data = session.get("my_framework", {})
    
    # Process and update data
    my_data["last_prompt"] = prompt
    
    # Update session
    session.set("my_framework", my_data)
```

## Development

**Requirements:**
- Python 3.12+
- uv 0.8.0+ (recommended) or pip

**Setup:**

```bash
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/ak-py
uv sync  # or: pip install -e ".[dev]"
```

**Run Tests:**

```bash
uv run pytest
# or: pytest
```

**Code Quality:**

The project uses:
- `black` — Code formatting
- `isort` — Import sorting
- `mypy` — Type checking

## License

Unless otherwise specified, all content, including all source code files and documentation files in this repository are:

Copyright (c) 2025-2026 Yaala Labs.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.

SPDX-License-Identifier: Apache-2.0

## Support

- **Issues**: [GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
- **Documentation**: [Full Documentation](https://github.com/yaalalabs/agent-kernel)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

