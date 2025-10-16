---
sidebar_position: 1
---

# REST API

Agent Kernel provides a built-in REST API server for agent interaction.

## Starting the API Server

```python
from agentkernel.api import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000)
```

Or from CLI:

```bash
python my_agent.py --mode api --port 8000
```

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

## Authentication

Add authentication middleware:

```python
from agentkernel.api import create_app
from your_auth import AuthMiddleware

app = create_app()
app.add_middleware(AuthMiddleware)
```

## CORS

Enable CORS for web apps:

```python
from fastapi.middleware.cors import CORSMiddleware

app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Example Client

### Python

```python
import requests

response = requests.post(
    "http://localhost:8000/chat",
    json={
        "agent": "assistant",
        "message": "Hello!",
        "session_id": "user-123"
    }
)

print(response.json()["response"])
```

### JavaScript

```javascript
const response = await fetch('http://localhost:8000/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    agent: 'assistant',
    message: 'Hello!',
    session_id: 'user-123'
  })
});

const data = await response.json();
console.log(data.response);
```

### cURL

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "assistant",
    "message": "Hello!",
    "session_id": "user-123"
  }'
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

Support for streaming responses (planned feature):

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
