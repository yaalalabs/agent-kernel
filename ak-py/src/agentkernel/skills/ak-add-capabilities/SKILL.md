---
name: ak-add-capabilities
description: >
  Add capabilities to an existing Agent Kernel project. This skill guides you through
  adding guardrails, tracing/observability, session persistence, knowledge bases, MCP server,
  A2A server, pre/post hooks, multimodal support, conversation thread support, and the sandbox
  capability (isolated code execution). Session
  persistence supports Redis, DynamoDB (AWS), Cosmos DB (Azure), and Firestore (GCP).
  Conversation threads support in-memory, Redis, DynamoDB (AWS), Firestore (GCP), and
  Cosmos DB (Azure) backends. Generates configuration and code changes needed.
license: Apache-2.0
metadata:
  author: yaalalabs
  version: "0.7.0"
  category: user
---

# Add Capabilities

Use this skill to enhance your Agent Kernel project with additional capabilities.

## Instructions for the Agent

When the user wants to add a capability, follow this workflow:

### Step 1: Identify the Project

Check for an existing Agent Kernel project with `pyproject.toml` and agent definition file.

### Step 2: Ask Which Capability

Which capability would you like to add?

1. **Guardrails** — Content safety filters for input and/or output
2. **Tracing** — Observability and monitoring (Langfuse, OpenLLMetry, or Pydantic Logfire)
3. **Session Persistence** — Durable conversation state (Redis, DynamoDB, Cosmos DB, Firestore)
4. **Knowledge Base** — Durable cross-session knowledge tools (ChromaDB, Neo4j, Starburst, or custom backend)
5. **MCP Server** — Expose agents as Model Context Protocol tools
6. **A2A Server** — Agent-to-Agent communication protocol
7. **Hooks** — Custom pre/post processing (RAG, logging, prompt modification)
8. **Multimodal** — Image and file attachment support
9. **Conversation Threads** — Persistent, named conversation history keyed by `session_id`
10. **Sandbox** — Isolated code/command execution with pluggable providers, workload profiles, policy, and per-user identity

### Step 3: Generate Changes

---

#### Guardrails

**Ask:** Input guardrails, output guardrails, or both? Which provider — OpenAI, AWS Bedrock, or Walled AI?

**For OpenAI Guardrails:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api]>=0.7.0",
    # OpenAI guardrails use the openai extra — already included if using OpenAI framework
]
```

2. Create `guardrails_input.json`:
```json
[
  {
    "type": "moderation",
    "moderation_config": {
      "content_type": ["violence", "sexual", "harassment", "self-harm"],
      "threshold": 0.5
    }
  },
  {
    "type": "jailbreak",
    "jailbreak_config": {}
  }
]
```

3. Create `guardrails_output.json`:
```json
[
  {
    "type": "pii_detection",
    "pii_config": {
      "output_handling": "block",
      "entities": ["email_address", "phone_number", "ssn"]
    }
  }
]
```

4. Update `config.yaml`:
```yaml
guardrail:
  input:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: guardrails_input.json
  output:
    enabled: true
    type: openai
    config_path: guardrails_output.json
```

**For AWS Bedrock Guardrails:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,aws]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    guardrail_id: "<your-bedrock-guardrail-id>"
    guardrail_version: "DRAFT"
  output:
    enabled: true
    type: bedrock
    guardrail_id: "<your-bedrock-guardrail-id>"
    guardrail_version: "DRAFT"
```

3. Prerequisites: Create a guardrail in AWS Bedrock Console and note the guardrail ID.

**For Walled AI Guardrails:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,walledai]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
guardrail:
  input:
    enabled: true
    type: walledai
    pii: true   # enable PII redaction on input
  output:
    enabled: true
    type: walledai
    pii: true   # enable PII unmasking on output
```

3. Set the environment variable:
```bash
export WALLED_API_KEY="your-walledai-api-key"
```

4. **How it works:**
   - **Input**: Text is checked for safety via `WalledProtect`. If unsafe, the request is blocked. If `pii: true`, text is redacted via `WalledRedact` and the PII mapping is stored in the session's non-volatile cache.
   - **Output**: If `pii: true`, redacted placeholders in the agent's reply are replaced with the original values using the stored mapping.

---

#### Tracing (Observability)

**Ask:** Which tracing backend — Langfuse, OpenLLMetry (Traceloop), or Pydantic Logfire?

**For Langfuse:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,langfuse]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
trace:
  enabled: true
  type: langfuse
```

3. Set environment variables:
```bash
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"   # or self-hosted URL
```

4. No code changes needed — tracing is automatically applied to all agent executions.

**For OpenLLMetry (Traceloop):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,openllmetry]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
trace:
  enabled: true
  type: openllmetry
```

3. Set environment variables per the Traceloop documentation.

**For Pydantic Logfire:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,logfire]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
trace:
  enabled: true
  type: logfire
```

3. Set the write token (optional — without it, Logfire runs locally and does not ship traces):
```bash
export LOGFIRE_TOKEN="your-write-token"
```

4. No code changes needed — tracing is automatically applied to all agent executions.

---

#### Session Persistence

**Ask:** Which backend — Redis, DynamoDB (AWS), Cosmos DB (Azure), or Firestore (GCP)?

**For Redis:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,redis]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
session:
  type: redis
  cache: 256                    # LRU cache size (optional, improves performance)
  redis:
    prefix: "ak:<project>:"    # Key prefix for namespacing
    url: "redis://localhost:6379"
    ttl: 3600                   # Session TTL in seconds (optional)
```

**For DynamoDB:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,aws]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
session:
  type: dynamodb
  cache: 256
  dynamodb:
    table_name: "<your-table-name>"
    region: "us-east-1"
    ttl: 3600
```

3. Create a DynamoDB table with partition key `session_id` (String) and sort key `key` (String). Enable TTL on `expiry_time` attribute.

**For Cosmos DB:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,azure]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
session:
  type: cosmosdb
  cache: 256
  cosmosdb:
    endpoint: "https://<account>.table.cosmos.azure.com:443/"
    table_name: "<your-table-name>"
    ttl: 3600
```

3. Set `AZURE_COSMOS_KEY` environment variable.

**For Firestore (GCP):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,gcp]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
session:
  type: firestore
  cache: 256
  firestore:
    collection_name: "ak_sessions"
    project_id: "<your-gcp-project-id>"   # optional, inferred from ADC if omitted
    ttl: 604800
```

3. Enable a TTL policy on the Firestore collection pointing to the `expiry_time` field for automatic document expiry.

---

#### Knowledge Base

Add durable knowledge tools that your agents can query and update across sessions.

**Ask:** Which backend do you want to use?
- ChromaDB (semantic/vector)
- Neo4j (graph/relationships)
- Starburst (read-only SQL via Trino)
- Custom adapter (developer extension)

**1. Update `pyproject.toml` dependencies based on backend:**

```toml
dependencies = [
  "agentkernel[openai,api,chromadb]>=0.7.0",  # for Chroma
  # or "agentkernel[openai,api,neo4j]>=0.7.0"
  # or "agentkernel[openai,api,trino]>=0.7.0"
]
```

**2. Configure backend + `KnowledgeBuilder` in your agent file (OpenAI example):**

```python
from agents import Agent
from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder

backend = ChromaManager(name="ChromaDB").add_schema(
  {
    "description": "Semantic vector store for unstructured facts",
    "store_payload": {"text": "string", "source": "string"},
    "read_payload": {"query": "string", "limit": "int"},
  }
)

kb = KnowledgeBuilder([backend])
kb_tools = kb.build()  # -> get_schemas, read_kb, write_kb, get_all_kb_descriptions

router = Agent(
  name="kb_router",
  instructions="Call get_schemas() first, then route reads/writes to the correct backend.",
  tools=OpenAIToolBuilder.bind(kb_tools),
)

OpenAIModule([router])

if __name__ == "__main__":
  CLI.main()
```

**3. Multi-backend routing with semantic placeholders (for Starburst or mixed backends):**

```python
kb = KnowledgeBuilder(
  [backend_a, backend_b],
  semantic_map={
    "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID'))",
    "<MONGO_SOURCE>": "mongodb.default.clients",
  },
)
```

**4. Backend notes:**
- `ChromaManager`: semantic search and fuzzy retrieval.
- `Neo4jManager`: entity/relationship graphs and Cypher queries.
- `StarburstManager`: **read-only**; use `read_kb`, do not route `write_kb`.

**5. Environment variables (examples):**

```bash
# Neo4j
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="password"

# Starburst
export STARBURST_HOST="<cluster>.trino.galaxy.starburst.io"
export STARBURST_USER="<user>"
export STARBURST_PASSWORD="<password-or-token>"
export STARBURST_PORT=443
```

**6. If the user asks for a new backend adapter:**
- Add a custom backend by implementing `KnowledgeBase` under `ak-py/src/agentkernel/knowledgebase/`.
- Use developer skill `.agents/skills/ak-dev-new-knowledgebase-integration/SKILL.md` for contributor workflows.

---

#### MCP Server

Expose your agents as MCP (Model Context Protocol) tools so other AI systems can discover and call them.

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,mcp]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
mcp:
  enabled: true
  expose_agents: true             # Auto-expose all registered agents
  # agents:                       # Or list specific agents
  #   - name: general
  #   - name: math
  url: "http://localhost:8000"    # Base URL of your server
```

3. No code changes needed. The MCP server endpoint is automatically available.

---

#### A2A Server

Enable Agent-to-Agent communication via Google's A2A protocol.

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,a2a]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
a2a:
  enabled: true
  agents:
    - general         # List agents to expose via A2A
  url: "http://localhost:8000"
```

3. No code changes needed. The A2A well-known endpoint is automatically available at `/.well-known/agent.json`.

---

#### Custom Hooks

Add custom pre/post processing to your agents.

**Pre-hook example (RAG injection):**

```python
from agentkernel.core import Agent, PreHook, Session
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestText


class RAGPreHook(PreHook):
    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        # Extract the user's prompt
        prompt = ""
        for req in requests:
            if isinstance(req, AgentRequestText):
                prompt = req.prompt
                break

        # Retrieve relevant context (your RAG logic here)
        context = await self._retrieve_context(prompt)

        # Modify the prompt with additional context
        if context:
            enhanced_prompt = f"Context: {context}\n\nUser question: {prompt}"
            return [AgentRequestText(prompt=enhanced_prompt)]

        return requests

    async def _retrieve_context(self, query: str) -> str:
        # Implement your retrieval logic
        return ""

    def name(self) -> str:
        return "rag_prehook"
```

**Post-hook example (disclaimer):**

```python
from agentkernel.core import Agent, PostHook, Session
from agentkernel.core.model import AgentReply, AgentRequest


class DisclaimerPostHook(PostHook):
    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        agent_reply.response += "\n\n_Disclaimer: This is AI-generated content._"
        return agent_reply

    def name(self) -> str:
        return "disclaimer_posthook"
```

**Attach hooks to agents:**

```python
from agentkernel.openai import OpenAIModule
from agents import Agent

agent = Agent(name="general", instructions="...")
module = OpenAIModule([agent])
module.pre_hook(agent, [RAGPreHook()])
module.post_hook(agent, [DisclaimerPostHook()])
```

**Streaming token hook (optional):** override `on_stream_chunk` on a `PostHook` to inspect or modify each token delta while `execution.mode: stream` is active (e.g. redact sensitive text before it reaches the client). Return `None` to drop a token entirely. Only called when streaming; regular `on_run()` still handles the non-streaming path.

```python
class RedactingPostHook(DisclaimerPostHook):
    async def on_stream_chunk(self, session, requests, agent, delta: str) -> str | None:
        return delta.replace("SECRET", "***")
```

---

#### Multimodal Support

Enable image and file processing in your agents.

**Ask:** Which storage backend — in-memory (default, dev), Redis (production), or DynamoDB (serverless/AWS)?

**Basic setup (in-memory storage, good for development):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,multimodal]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
multimodal:
  enabled: true
  max_attachments: 20
  description_model: "gpt-4o"          # Model for generating brief descriptions
  analysis_model: "gpt-4o"             # Model for detailed analysis via tool
```

3. No further code changes needed. When enabled:
   - A system tool (`analyze_attachments`) is automatically attached to all agents
   - Image/file attachments in requests are processed, described by a vision LLM, and stored in a separate in-memory attachment store (outside the conversation history/session state, non-persistent, in-process)
   - Binary data is kept out of conversation history to prevent memory bloat
   - Agents see attachment IDs and descriptions in their context
   - Agents can call `analyze_attachments(attachment_ids, prompt)` for detailed analysis

**For Redis storage (production, persistent, distributed):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,redis,multimodal]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
multimodal:
  enabled: true
  storage_type: redis
  max_attachments: 20
  description_model: "gpt-4o"
  analysis_model: "gpt-4o"
  redis:
    url: "redis://localhost:6379"
    prefix: "ak:attachments:"
    ttl: 604800                         # Attachment TTL in seconds (7 days)
```

**For DynamoDB storage (serverless/AWS):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,aws,multimodal]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
multimodal:
  enabled: true
  storage_type: dynamodb
  max_attachments: 20
  description_model: "gpt-4o"
  analysis_model: "gpt-4o"
  dynamodb:
    table_name: "ak-attachments"
    ttl: 604800
```

3. Create a DynamoDB table with partition key `session_id` (String) and sort key `attachment_id` (String). Enable TTL on `expiry_time` attribute.

**Storage type comparison:**

| Type | Persistence | Multi-process | Setup | Best for |
|------|-------------|---------------|-------|----------|
| `in_memory` | Lost on restart | Single process | None | Dev/testing |
| `redis` | Persistent | Distributed | Redis server | Production |
| `dynamodb` | Persistent | Distributed | AWS table | Serverless/Lambda |

**How it works:**
- When a user sends an image or file, a vision LLM generates a brief one-sentence description
- The binary data is saved to the configured storage backend (not in conversation history)
- The agent receives the text prompt enriched with attachment IDs and descriptions
- When the agent needs to inspect an attachment in detail, it calls the `analyze_attachments` tool
- The tool retrieves the binary from storage, sends it to the analysis LLM, and returns clean text

**Send multimodal requests via API:**

```bash
# Base64 image
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is in this image?",
    "session_id": "test-1",
    "agent": "general",
    "image": "<base64-data>",
    "image_name": "photo.jpg"
  }'

# File upload (multipart)
curl -X POST http://localhost:8000/run \
  -F "prompt=Summarize this document" \
  -F "session_id=test-1" \
  -F "agent=general" \
  -F "file=@document.pdf"
```

**Environment variables (all storage types):**

```bash
# Required: LLM API key for vision models
export OPENAI_API_KEY="sk-..."

# For Redis storage
export AK_MULTIMODAL__STORAGE_TYPE=redis
export AK_MULTIMODAL__REDIS__URL="redis://localhost:6379"

# For DynamoDB storage
export AK_MULTIMODAL__STORAGE_TYPE=dynamodb
export AK_MULTIMODAL__DYNAMODB__TABLE_NAME="ak-attachments"
```

---

#### Conversation Thread Support

Enable persistent, named conversation threads keyed by `session_id`.

**Ask:** Which thread store backend — in-memory (default, dev), Redis, DynamoDB (AWS), Firestore (GCP), or Cosmos DB (Azure)?

**Basic setup (in-memory store, good for development):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api]>=0.7.0",
]
```

2. Update `config.yaml`:
```yaml
thread:
  type: memory  # other supported backends: redis | dynamodb | firestore | cosmosdb
```

3. No further code changes needed. When enabled:
   - `user_id` becomes required on every chat request
   - A thread is auto-created on a session's first request
   - `GET /api/v1/threads` and `GET /api/v1/threads/{session_id}` become available for reading thread history (open by default, or protected by a pluggable `Authoriser`)
   - Threads are auto-named by an LLM call deriving a concise title from the first prompt (falls back to a truncated prompt prefix without `litellm`/an API key)
   - Sending `thread_name` on any chat request sets/renames the thread and locks it against automatic naming

**For LLM-based thread naming**, add the `thread` extra:
```toml
dependencies = [
    "agentkernel[openai,api,thread]>=0.7.0",
]
```
```yaml
thread:
  type: memory
  naming:
    model: "gpt-4o-mini"   # LiteLLM model used to name threads
    max_length: 80
```

**For Redis storage (production, persistent, distributed):**

```toml
dependencies = [
    "agentkernel[openai,api,redis,thread]>=0.7.0",
]
```
```yaml
thread:
  type: redis
  redis:
    url: "redis://localhost:6379"
    prefix: "ak:thread:"
    ttl: 2592000            # Thread TTL in seconds (30 days, 0 disables)
```

**For DynamoDB storage (serverless/AWS):**

```toml
dependencies = [
    "agentkernel[openai,api,aws,thread]>=0.7.0",
]
```
```yaml
thread:
  type: dynamodb
  dynamodb:
    table_name: "ak-agent-threads"   # partition key session_id (S), sort key sk (S)
    ttl: 0
```

**For Firestore storage (serverless/GCP):**

```yaml
thread:
  type: firestore
  firestore:
    collection_name: "ak-agent-threads"
    ttl: 0
```

**For Cosmos DB storage (Azure, Table API):**

```yaml
thread:
  type: cosmosdb
  cosmosdb:
    connection_string: "${AZURE_COSMOS_CONNECTION_STRING}"
    table_name: "akagentthreads"
```

**Protecting the read endpoints with an Authoriser:**

```python
from typing import Optional
from agentkernel.api import RESTAPI, AgentRESTRequestHandler, ThreadRESTRequestHandler
from agentkernel.core.thread import Authoriser

class DemoAuthoriser(Authoriser):
    def authorise(self, token: str) -> Optional[str]:
        # Validate the ****** against your own auth provider, return the user_id or None.
        return {"alice-token": "alice", "bob-token": "bob"}.get(token)

RESTAPI.run(handlers=[AgentRESTRequestHandler(), ThreadRESTRequestHandler(authoriser=DemoAuthoriser())])
```

Passing an explicit `ThreadRESTRequestHandler` replaces the default open thread routes that are mounted
automatically when a `thread` block is present in `config.yaml`. With an Authoriser configured, thread listings
are scoped to the resolved `user_id` and reading another user's thread is rejected (403).

**Attachments in thread mode:** require `multimodal.enabled: true` with a shared attachment store —
`in_memory`, `redis`, or `dynamodb` (`session_cache` is rejected).

**Send a chat request with a thread:**

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?", "session_id": "ses-1", "user_id": "alice", "thread_name": "Capitals quiz"}'
```

See `examples/api/thread-openai` and `examples/api/multimodal/thread-openai`.

---

#### Sandbox

**What it does:** Lets agents execute code and shell commands in an isolated, permission-bounded
environment. When enabled, agents automatically gain sandbox tools (`run_code`, `run_command`,
`write_sandbox_file`, `read_sandbox_file`, `check_sandbox_task`, `list_sandbox_sessions`,
`new_sandbox_session`, `destroy_sandbox_session`) and the usage guidance is injected into their
system prompt — the agent's own instructions need not mention the sandbox.

**Ask:** Which provider — `local_subprocess` (no isolation; dev/test only) or `docker`
(container isolation; needs the `sandbox-docker` extra and a Docker daemon)? Should it apply to
all agents or only some (the `agents` list)?

**1. Install the extra (docker only):**

```bash
pip install "agentkernel[sandbox-docker]"
```

**2. Add a `sandbox` block to `config.yaml`.**

Minimal (single-backend sugar synthesizes a `default` profile):

```yaml
sandbox:
  enabled: true
  type: local_subprocess       # or: docker
  local_subprocess: {}         # or a docker: { image: python:3.12-slim } block
  broker:
    flavor: thread             # thread (CLI/REST default) | embedded
```

With explicit profiles, policy, and scoping:

```yaml
sandbox:
  enabled: true
  agents: [coder]              # optional: only these agents get the sandbox (omit = all)
  default_profile: workspace
  tool_output_max_chars: 8000
  profiles:
    workspace:
      type: docker
      scope: per_session       # per_call | per_session | per_runtime
      environment: managed     # managed (default) | attached (connect to an existing environment; needs attach_to)
      idle_timeout: 1800
      policy:
        network_egress: deny   # allow | deny | allowlist
        cpu: 1.0
        memory_mb: 512
        timeout: 30.0
        strict: true           # fail closed when the provider can't enforce a dimension
      docker:
        image: python:3.12-slim
  broker:
    flavor: thread
```

**3. No agent code changes needed** — the tools and prompt guidance attach automatically. Keep
the agent's instructions about *what* to do; the sandbox usage is injected.

:::caution
`local_subprocess` runs code directly on the host with **no isolation** — dev/test only. Use
`docker` (or another isolating provider) in production.
:::

For per-user identity (running sandboxed code under the invoking user's identity), set
`principal_resolver` to a dotted path and a profile's `identity.mode: user`; see the
[Sandbox guide](https://kernel.yaala.ai/docs/next/advanced/sandbox) and the
`examples/sandbox/identity` example.

---

### What to Do Next

You've added new capabilities to your project. Here's what you might do next:

- **Add more tools & agents** → Use the `ak-build` skill to add new tools and specialist agents that leverage your new capabilities (e.g., agents that use guardrails or hooks).
- **Connect a messaging platform** → Use the `ak-add-integration` skill to add Slack, WhatsApp, Telegram, or other channels so users can interact with your enhanced agents.
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy your agent (with all its capabilities) to AWS or Azure.
- **Set up testing** → Use the `ak-test` skill to verify your capabilities work correctly — especially guardrails and hooks.
- **Extend knowledge backends** → Contributors can use `.agents/skills/ak-dev-new-knowledgebase-integration/SKILL.md` to add new KnowledgeBase adapters.
