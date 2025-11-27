---
sidebar_position: 3
---

# Multi-Agent Example

Build a collaborative multi-agent system.

## Complete Code

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

# Supervisor agent
supervisor = CrewAgent(
    role="supervisor",
    goal="Coordinate work between specialist agents",
    backstory="""You are a project manager who delegates tasks to specialists.
    You analyze requests and route them to the appropriate specialist.""",
    verbose=False,
)

# Specialist agents
researcher = CrewAgent(
    role="researcher",
    goal="Research topics thoroughly",
    backstory="""You are an expert researcher who finds accurate information.
    You provide detailed, well-sourced answers.""",
    verbose=False,
)

writer = CrewAgent(
    role="writer",
    goal="Write clear and engaging content",
    backstory="""You are a skilled writer who creates well-structured content.
    You take research and turn it into readable articles.""",
    verbose=False,
)

reviewer = CrewAgent(
    role="reviewer",
    goal="Review content for quality and accuracy",
    backstory="""You are a detail-oriented reviewer who ensures quality.
    You check for errors, clarity, and completeness.""",
    verbose=False,
)

# Register all agents
CrewAIModule([supervisor, researcher, writer, reviewer])

if __name__ == "__main__":
    CLI.main()
```

## Running the Example

```bash
pip install agentkernel[crewai]
export OPENAI_API_KEY=sk-...
python multi_agent.py
```

## Next Steps

- [Multi-Agent Systems](../advanced/multi-agent)
- [Deployment Guide](../deployment/overview)
