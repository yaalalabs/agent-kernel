# Overview

Agent Kernel provides various built in integrations to connect your AI agents with external platforms and services. These integrations allow you to deploy your agents in real-world environments and interact with users through different channels.

## Execution Hooks

Agent Kernel provides powerful execution hooks that let you customize agent behavior at runtime.

- **[Execution Hooks](./hooks)** - Pre-execution and post-execution hooks for guardrails, RAG context injection, response moderation, and more. See the [detailed hooks documentation](./hooks) for complete guide with examples.

## Observability & Monitoring

- **Langfuse** - Open-source LLM engineering platform for tracing, evaluating, and monitoring AI applications. See [Traceability and Observability](../advanced/traceability) for detailed setup and usage.
- **OpenLLMetry (Traceloop)** - OpenTelemetry-based observability for LLM applications with support for multiple backends including Traceloop, Datadog, New Relic, and Honeycomb. See [Traceability and Observability](../advanced/traceability) for detailed setup and usage.

## Social media
These are built on REST APIs and you can install custom integrations as well.

### Built-in
The following built-in integrations are available.

- **[Slack](./slack)** - Deploy agents as Slack bots that can respond to mentions and direct messages in Slack workspaces
- **[WhatsApp](./whatsapp)** - Deploy agents as WhatsApp bots
- **[Messenger](./messenger)** - Deploy agents as FB Messenger bots
- **[Instagram](./instagram)** - Deploy agents as Instagram DM bots
- **[Telegram](./telegram)** - Deploy agents as Telegram bots
- **[Gmail](./gmail)** - Deploy agents as Gmail bots that automatically read and reply to emails
- **[Microsoft Teams](./teams)** - Deploy agents as Microsoft Teams bots via Azure Bot Framework, supporting 1:1 chats, group chats, and channels
- **[AG-UI](./agui)** - Serve agents over the AG-UI protocol to a custom frontend: streamed events for the answer, reasoning and tool calls, plus a shared state object the UI and the agent both read and write. Unlike the entries above this is not a hosted chat platform — it is a protocol your own UI speaks

```mermaid
---
config:
  layout: dagre
  elk: true
---
flowchart LR
    D["Integration"] --> I["Slack"] & J["WhatsApp"] & K["Messenger"] & M["Instagram"] & N["Telegram"] & O["Gmail"] & T["Teams"]

    style I fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style J fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style K fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style M fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style N fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style O fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style T fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
```

### How a messaging integration works

Every messaging integration is an **adapter pair** with the execution queue between them, so the
agent never runs inside the webhook turn: a slow model call can no longer exceed the platform's
delivery timeout and make it redeliver the message.

- The **inbound adapter** verifies the delivery, normalizes it (resolving the session and the
  platform's own message id at the edge), stores any attachments, and enqueues.
- The **agent runner** executes it, knowing nothing about the platform.
- The **outbound adapter** delivers the reply through the platform's API.

```mermaid
---
config:
  layout: dagre
  elk: true
---
flowchart LR
    P["Platform"] --> W["WebhookRESTRequestHandler<br/>(or PollerRunner for Gmail)"]
    W --> IN["InboundAdapter<br/>verify → parse"]
    IN --> Q(["Input queue"]) --> AR["AgentRunner"] --> OQ(["Output queue"])
    OQ --> RH["ResponseHandler"] --> OUT["OutboundAdapter<br/>deliver"] --> P

    style IN fill:#005073,stroke:#fff,stroke-width:2px,color:#fff
    style OUT fill:#005073,stroke:#fff,stroke-width:2px,color:#fff
    style AR fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
```

Mount an integration with `IOHandler.run(...)`, which starts the queue topology alongside the
webhook routes. `RESTAPI.run([...])` builds a bare API with no runner behind it, so it rejects an
integration handler rather than silently accepting messages nothing will answer.

Bring your own delivery for any platform by pointing its `outbound_adapter` setting at a dotted
path to your own `OutboundAdapter` subclass; bring your own parsing by passing your own
`InboundAdapter` subclass to the handler.

### Custom
For REST API based 'custom integrations' you can implement **RESTRequestHandler** and pass it to the `IOHandler.run(handlers=[...])` method alongside the messaging handlers.

```python
from fastapi import APIRouter
from agentkernel.api import RESTRequestHandler
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.pipeline import IOHandler
from agentkernel.slack import SlackInboundAdapter

class CustomHandler(RESTRequestHandler):
  def get_router(self) -> APIRouter:
      """
        - GET /health: Health check
        - GET /api/v1/agents: List available agents
      """
      router = APIRouter()

      @router.get("/health")
      def health():
          return {"status": "ok"}

      @router.get("/api/v1/agents")
      def list_agents():
          return {"agents": list(Runtime.instance().agents().keys())}

      @router.get("/rag_agent")
      def handle_rag(req: Request):
          return self._handler(req)

  def _handler(req):
      # Do a vector search and return something

if __name__ == "__main__":
    # Can pass multiple handlers
    IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter()), CustomHandler()])
```
