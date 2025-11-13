# Integrations Overview

Agent Kernel provides various built in integrations to connect your AI agents with external platforms and services. These integrations allow you to deploy your agents in real-world environments and interact with users through different channels.

## API
For API custom integrations you can implement **RESTRequestHandler** and pass it to the RESTAPI.run() method.

```python
from fastapi import APIRouter
from agentkernel.api import RESTRequestHandler
from agentkernel.api import RESTAPI
from agentkernel.slack import AgentSlackRequestHandler

class CustomHandler(RESTRequestHandler):
  def get_router(self) -> APIRouter:
      """
        - GET /health: Health check
        - GET /agents: List available agents
      """
      router = APIRouter()

      @router.get("/health")
      def health():
          return {"status": "ok"}

      @router.get("/agents")
      def list_agents():
          return {"agents": list(Runtime.instance().agents().keys())}

      @router.get("/rag_agent")
      def handle_rag(req: Request):
          return self._handler(req)

  def _handler(req):
      # Do a vector search and return something

if __name__ == "__main__":
    RESTAPI.run([ AgentSlackRequestHandler(), CustomHandler()]) # Can pass multiple handlers
```

## Available Integrations

### Collaboration Platforms

- **[Slack](./slack)** - Deploy agents as Slack bots that can respond to mentions and direct messages in Slack workspaces

### Observability & Monitoring

- **Langfuse** - Open-source LLM engineering platform for tracing, evaluating, and monitoring AI applications. See [Traceability and Observability](../advanced/traceability) for detailed setup and usage.
- **Traceloops** - Available soon!