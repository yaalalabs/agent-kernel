---
sidebar_position: 1
---

# REST API

Agent Kernel provides a built-in REST API server for agent interaction.

## Starting the API Server

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

Or from CLI:

```bash
python my_agent.py
```

## Endpoints

### POST /run

Execute an agent with a message.

**Request:**

```json
{
  "agent": "assistant",
  "prompt": "What is 2 + 2?",
  "session_id": "user-123"
}
```

**Response:**

```json
{
  "result": "2 + 2 equals 4.",
  "session_id": "user-123"
}
```

### GET /agents

List all available agents.

**Response:**

```json
{
  "agents": ["assistant", "math", "code"]
}
```

### GET /health

Health check endpoint.

**Response:**

```json
{
  "status": "ok"
}
```

## Error Handling

**400 Bad Request:**

```json
{
  "error": "Missing required field: agent"
}
```

**500 Internal Server Error:**

```json
{
  "error": "Agent execution failed",
  "session_id": "session-x"
}
```

## Custom Routes

Agent Kernel REST API allows the users to add custom routes to the existing REST server by two ways. This is a support functioanlity that would avoid users from maintaining a separate REST server for other application work, and exposes an endpoint with a configurable prefix `/custom` by default.

### Option 1

Add a route directly

```python
from agentkernel.api import RESTAPI
from fastapi import APIRouter

# Optional custom route to add your own endpoints
router = APIRouter()


@router.post("/deposit")
async def run(req: dict):
    amount = req.get("amount")
    return {"result": f"Deposited ${amount} over the counter"}


RESTAPI.add(router=router)
# End of optional code block for REST API mode

if __name__ == "__main__":
    RESTAPI.run()
```

### Option 2

Add a the default Agent REST API handler

```python
class CustomRESTRequestHandler(AgentRESTRequestHandler):

    def __init__(self):
        super.__init()


    def get_router(self) -> APIRouter:
        router = super().get_router()

        @router.get("/custom")
        def custom():
            return cutom_request_handler()

        return router

if __name__ == "__main__":
    RESTAPI.run(handler=CustomRESTRequestHandler())
```


## Streaming

Support for streaming responses will be available soon


## Best Practices

- Use unique session IDs per conversation
- Handle errors gracefully
- Implement rate limiting in production
- Use HTTPS in production
- Add authentication
- Monitor API performance
