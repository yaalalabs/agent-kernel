---
sidebar_position: 2
---

# Local Deployment

Run Agent Kernel locally for development and testing.

## CLI Mode

The simplest way to run agents locally:

```python
from agentkernel.cli import CLI

if __name__ == "__main__":
    CLI.main()
```

Run:

```bash
python my_agent.py
```

## Interactive Session

```
Agent Kernel CLI
Available agents:
  - general
  - math
  - code

Type your message (or 'quit' to exit):
> What is 2 + 2?

[Agent responds...]

> quit
Goodbye!
```

## CLI Features

- Agent selection
- Session management
- Conversation history
- Error display
- Debug mode

## REST API Mode

Run as a local API server:

```bash
python my_agent.py --mode api --port 8000
```

Test with curl:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "general",
    "message": "Hello!",
    "session_id": "test-123"
  }'
```

## Configuration

```bash
# Log level
export AK_LOG_LEVEL=DEBUG

# Session storage
export AK_SESSION_STORAGE=in_memory

# Port (API mode)
export AK_API_PORT=8000
```

## Development Workflow

1. **Write agent code**
2. **Test in CLI** - `python my_agent.py`
3. **Test API locally** - `python my_agent.py --mode api`
4. **Deploy to cloud** when ready

## Best Practices

- Use CLI for rapid iteration
- Test with API mode before deployment
- Use in-memory sessions for development
- Enable DEBUG logging during development
