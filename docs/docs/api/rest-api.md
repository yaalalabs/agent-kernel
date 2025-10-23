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

## Endpoints

### POST /chat

Execute an agent with a message.

**Request:**

```json
{
  "agent": "assistant",
  "message": "What is 2 + 2?",
  "session_id": "user-123"
}
```

**Response:**

```json
{
  "response": "2 + 2 equals 4.",
  "agent": "assistant",
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
  "status": "healthy",
  "version": "0.1.2b17"
}
```

## Error Handling

**400 Bad Request:**

```json
{
  "error": "Missing required field: agent"
}
```

**404 Not Found:**

```json
{
  "error": "Agent not found: nonexistent"
}
```

**500 Internal Server Error:**

```json
{
  "error": "Agent execution failed",
  "details": "Error details..."
}
```

## Streaming

Support for streaming responses will be available soon

```python
POST /chat/stream
```

## Best Practices

- Use unique session IDs per conversation
- Handle errors gracefully
- Implement rate limiting in production
- Use HTTPS in production
- Add authentication
- Monitor API performance
