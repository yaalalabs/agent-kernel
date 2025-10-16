---
sidebar_position: 2
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
module = CrewAIModule([supervisor, researcher, writer, reviewer])

if __name__ == "__main__":
    CLI.main()
```

## Running the Example

```bash
pip install agentkernel[crewai]
export OPENAI_API_KEY=sk-...
python multi_agent.py
```

## Example Session

```
Agent Kernel CLI
Available agents:
  - supervisor
  - researcher
  - writer
  - reviewer

Type your message (or 'quit' to exit):
> Research and write an article about quantum computing

[supervisor] I'll coordinate this task. Let me start with research.
[supervisor handed off to researcher]

[researcher] I've researched quantum computing...
[researcher handed off to writer]

[writer] Based on the research, here's the article...
[writer handed off to reviewer]

[reviewer] The article looks great! Minor suggestions...

> quit
Goodbye!
```

## Pipeline Pattern

Create a sequential pipeline:

```python
class ContentPipeline:
    def __init__(self):
        from agentkernel.core import Runtime
        self.runtime = Runtime.get()
    
    async def create_content(self, topic: str, session_id: str):
        session = self.runtime.get_session(session_id)
        
        # Step 1: Research
        researcher = self.runtime.get_agent("researcher")
        research = await researcher.runner.run(
            researcher, session, f"Research {topic}"
        )
        
        # Step 2: Write
        writer = self.runtime.get_agent("writer")
        article = await writer.runner.run(
            writer, session, f"Write article about {research}"
        )
        
        # Step 3: Review
        reviewer = self.runtime.get_agent("reviewer")
        final = await reviewer.runner.run(
            reviewer, session, f"Review: {article}"
        )
        
        return final
```

## Deployment

Deploy as API to enable programmatic access:

```bash
python multi_agent.py --mode api --port 8000
```

Test:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "supervisor",
    "message": "Research quantum computing",
    "session_id": "project-1"
  }'
```

## Next Steps

- [Custom Tools Example](./custom-tools)
- [Multi-Agent Systems](../advanced/multi-agent)
- [Deployment Guide](../deployment/overview)
