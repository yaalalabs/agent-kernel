---
sidebar_position: 1
---

# Basic Agent Example

A complete example of creating and running a simple agent.

## Complete Code

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

# Define your agent
assistant = CrewAgent(
    role="assistant",
    goal="Provide helpful assistance to users",
    backstory="""You are a friendly and knowledgeable AI assistant.
    You provide clear, concise answers and help users with their questions.""",
    verbose=False,
)

# Register with Agent Kernel
module = CrewAIModule([assistant])

if __name__ == "__main__":
    CLI.main()
```

## Running the Example

```bash
# Install dependencies
pip install agentkernel[crewai]

# Set API key
export OPENAI_API_KEY=sk-...

# Run the agent
python basic_agent.py
```

## Example Session

```
Agent Kernel CLI
Available agents:
  - assistant

Type your message (or 'quit' to exit):
> Hello!

[assistant] Hello! How can I help you today?

> What is Python?

[assistant] Python is a high-level, interpreted programming language
known for its simplicity and readability. It's widely used for
web development, data science, automation, and more.

> quit
Goodbye!
```

## Customization

### Add Custom Instructions

```python
assistant = CrewAgent(
    role="assistant",
    goal="Provide helpful assistance",
    backstory="You are an expert in Python programming",
    verbose=False,
)
```

### Add Tools

```python
from crewai import Tool

def search_docs(query: str) -> str:
    # Your search implementation
    return f"Documentation for: {query}"

search_tool = Tool(
    name="search_docs",
    description="Search documentation",
    func=search_docs
)

assistant = CrewAgent(
    role="assistant",
    goal="Provide helpful assistance",
    backstory="You help users find documentation",
    tools=[search_tool],
    verbose=False,
)
```

## Deploy as API

```bash
# Run as REST API
python basic_agent.py --mode api --port 8000

# Test with curl
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"agent": "assistant", "message": "Hello!", "session_id": "test-1"}'
```

## Deploy to AWS

```bash
# Deploy to Lambda
ak-deploy --profile serverless --region us-east-1
```

## Next Steps

- [Multi-Agent Example](./multi-agent)
- [Custom Tools Example](./custom-tools)
- [Framework Integration](../frameworks/overview)
