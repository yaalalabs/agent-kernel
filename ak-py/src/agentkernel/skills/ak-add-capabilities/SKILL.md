---
name: ak-add-capabilities
description: >
  Add capabilities to an existing Agent Kernel project. This skill guides you through
  adding guardrails, tracing/observability, session persistence, MCP server, A2A server,
  pre/post hooks, and multimodal support. Generates configuration and code changes needed.
license: Apache-2.0
metadata:
  author: yaalalabs
  version: "0.2.13"
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
2. **Tracing** — Observability and monitoring (Langfuse or OpenLLMetry)
3. **Session Persistence** — Durable conversation state (Redis, DynamoDB, Cosmos DB)
4. **MCP Server** — Expose agents as Model Context Protocol tools
5. **A2A Server** — Agent-to-Agent communication protocol
6. **Hooks** — Custom pre/post processing (RAG, logging, prompt modification)
7. **Multimodal** — Image and file attachment support

### Step 3: Generate Changes

---

#### Guardrails

**Ask:** Input guardrails, output guardrails, or both? Which provider — OpenAI, AWS Bedrock, or Walled AI?

**For OpenAI Guardrails:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api]>=0.2.13",
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
    "agentkernel[openai,api,aws]>=0.2.13",
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
    "agentkernel[openai,api,walledai]>=0.2.13",
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

**Ask:** Which tracing backend — Langfuse or OpenLLMetry (Traceloop)?

**For Langfuse:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,langfuse]>=0.2.13",
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
    "agentkernel[openai,api,openllmetry]>=0.2.13",
]
```

2. Update `config.yaml`:
```yaml
trace:
  enabled: true
  type: openllmetry
```

3. Set environment variables per the Traceloop documentation.

---

#### Session Persistence

**Ask:** Which backend — Redis, DynamoDB (AWS), or Cosmos DB (Azure)?

**For Redis:**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,redis]>=0.2.13",
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
    "agentkernel[openai,api,aws]>=0.2.13",
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
    "agentkernel[openai,api,azure]>=0.2.13",
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

---

#### MCP Server

Expose your agents as MCP (Model Context Protocol) tools so other AI systems can discover and call them.

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,mcp]>=0.2.13",
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
    "agentkernel[openai,api,a2a]>=0.2.13",
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
                prompt = req.text
                break

        # Retrieve relevant context (your RAG logic here)
        context = await self._retrieve_context(prompt)

        # Modify the prompt with additional context
        if context:
            enhanced_prompt = f"Context: {context}\n\nUser question: {prompt}"
            return [AgentRequestText(text=enhanced_prompt)]

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
        agent_reply.text += "\n\n_Disclaimer: This is AI-generated content._"
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

---

#### Multimodal Support

Enable image and file processing in your agents.

**Ask:** Which storage backend — in-memory (default, dev), Redis (production), or DynamoDB (serverless/AWS)?

**Basic setup (in-memory storage, good for development):**

1. Update `pyproject.toml`:
```toml
dependencies = [
    "agentkernel[openai,api,multimodal]>=0.2.13",
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
    "agentkernel[openai,api,redis,multimodal]>=0.2.13",
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
    "agentkernel[openai,api,aws,multimodal]>=0.2.13",
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

### What to Do Next

You've added new capabilities to your project. Here's what you might do next:

- **Add more tools & agents** → Use the `ak-build` skill to add new tools and specialist agents that leverage your new capabilities (e.g., agents that use guardrails or hooks).
- **Connect a messaging platform** → Use the `ak-add-integration` skill to add Slack, WhatsApp, Telegram, or other channels so users can interact with your enhanced agents.
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy your agent (with all its capabilities) to AWS or Azure.
- **Set up testing** → Use the `ak-test` skill to verify your capabilities work correctly — especially guardrails and hooks.
