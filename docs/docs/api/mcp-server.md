---
sidebar_position: 2
---

# MCP Server

Expose agents using the Model Context Protocol (MCP).

## What is MCP?

MCP (Model Context Protocol) is a standardized protocol for AI systems to interact with external tools and data sources.

## Enabling MCP

```bash
export AK_MCP__ENABLED=true
```
or
```yaml
mcp:
  enabled: true
```

> **Endpoint**: The MCP server is always mounted at `/mcp` on the main API server. The full endpoint is `http://{api.host}:{api.port}/mcp`. Use `api.port` (or `AK_API__PORT`) to change the port.

## Starting MCP Server

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

## Agent as MCP Tool

Agents are automatically exposed as MCP tools if you set `mcp.expose_agents` to `true`. You can selectively expose agents as well. 

An agent tool call always goes through the [queue pipeline](../advanced/queue-mode-guide.md), like a
REST chat request: it is put on the input queue, the agent runner executes it, and the reply is read
back from the response store. The tool's `session_id` argument is the Agent Kernel session.

| How the app starts | MCP with `expose_agents: true` |
|---|---|
| `RESTAPI.run()` with no `execution.queues` block (the laptop default) | ✅ one process, in-memory queue |
| `IOHandler.run(handlers=[...])`, any transport | ✅ through the queue |
| `RESTAPI.run(handlers=[...])`, `RESTAPI.run()` on SQS/Kafka/NATS, `AWSRestAPI`, `AWSWebsocketAPI`, `ECSIOHandler` | ❌ refuses to start (`AKConfigError`): these start no agent runner |

- **Split deployments** (SQS, Kafka or NATS, with the agent runner in its own process): import the
  same agent modules in the IO process as in the runner, because agent tools are built from the IO
  process's registry. Without them the IO process logs a warning and lists no agent tools. The
  response store must be shared (`redis`, `valkey` or `dynamodb`) in every execution mode. With more
  than one IO replica behind a load balancer, set `mcp.stateless_http: true`, since a stateful MCP
  session is pinned to one replica.
- **Latency**: the reply is picked up by polling the response store, so it takes at least one
  `execution.response_store.delay` (1 s without a `response_store` block), and the wait gives up
  after `retry_count` reads (about 59 s without a block).
- **Errors**: a failed run, a timeout or any other error reaches the client as a `ToolError` with a
  fixed message; the details go to the server logs only.
- **Execution mode**: MCP ignores `execution.mode` and always waits for one whole reply.

## Custom Tools

Expose custom tools via MCP:

```python
from agentkernel.mcp import MCP
from agentkernel.api import RESTAPI

mcp = MCP.get()

@mcp.tool
def custom_tool(param: str) -> str:
    return f"Processed: {param}"

RESTAPI.run()
```

Custom tools are your application's own code: they run in the web-server process, not through the
queue. An MCP server with `expose_agents: false` serves only these tools, so it runs no agent and
starts on any entry point.

## Configuration

```yaml
mcp:
  enabled: true
  expose_agents: true
  agents: ['*']
  stateless_http: false  # Set to true for stateless mode (no Mcp-Session-Id)
```

## Integration

Use agents from other AI systems:

```python
result = mcp_client.call_tool(
    "custom_tool",
    {"param": "Hello!"}
)
```

## Structured replies

A tool returns the agent's reply as text, unless that reply carries a format label — set by the
[A2UI capability](../advanced/a2ui.md) or by an application post-hook. A labelled reply arrives as
`structuredContent`, with the format in MCP's own `_meta` slot:

```json
{
  "structuredContent": {"version": "v1.0", "createSurface": {"surfaceId": "s1"}},
  "_meta": {"media_type": "application/a2ui+json"}
}
```

fastmcp emits a text block alongside it, so a client reading only text blocks keeps working. Every
unlabelled reply — text, image, or structured-but-unlabelled — returns exactly the string it always
did.

A payload that is a JSON **array** rather than an object is the one case that changes shape. MCP
requires `structuredContent` to be an object, so the array travels under a `result` key with the
flag that tells a client to unwrap it again:

```json
{
  "structuredContent": {"result": [{"createSurface": {"surfaceId": "s1"}}]},
  "_meta": {"media_type": "application/a2ui+json", "fastmcp": {"wrap_result": true}}
}
```

A fastmcp client hands you the array itself; any other client reads it from `result`.

Note that `_meta` is optional in MCP: a host is free to drop it, in which case the client receives
the payload without knowing its format.
