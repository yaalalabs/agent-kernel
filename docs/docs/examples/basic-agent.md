---
sidebar_position: 2
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
CrewAIModule([assistant])

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

## Next Steps

- [Multi-Agent Example](./multi-agent)
- [Framework Integration](../frameworks/overview)
