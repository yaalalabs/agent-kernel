---
name: ak-build
description: >
  Add tools, agents, and handoffs to an existing Agent Kernel project. This skill guides
  you through reading the current project, understanding its framework and structure,
  then making context-aware additions — new tools, new agents, agent-to-agent handoffs,
  and Module wiring. The workhorse skill for iterative agent development.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: user
---

# Build: Add Tools & Agents

Use this skill to add new tools, agents, or handoffs to an existing Agent Kernel project.

## Instructions for the Agent

### Step 1: Read the Existing Project

**Before generating any code**, inspect the project to determine:

1. **Framework** — Open the main agent file (e.g., `app.py`, `demo.py`, `server.py`, `lambda.py`) and look for:
   - `from agentkernel.openai import OpenAIModule` → **OpenAI Agents SDK**
   - `from agentkernel.langgraph import LangGraphModule` → **LangGraph**
   - `from agentkernel.crewai import CrewAIModule` → **CrewAI**
   - `from agentkernel.adk import GoogleADKModule` → **Google ADK**
    - `from agentkernel.smolagents import SmolagentsModule` → **Smolagents**

2. **Existing agents** — List every agent already defined (names, roles, instructions).

3. **Existing tools** — List every tool function and which agent uses it.

4. **Entry point** — Is it CLI (`demo.py`), API (`RESTAPI.run()`), Lambda (`Lambda.handler`), or Azure Function?

5. **Config** — Read `config.yaml` for session type, guardrails, tracing, integrations already enabled.

6. **Dependencies** — Read `pyproject.toml` for the extras already installed (e.g., `[openai,api,redis]`).

Report back what you found before proceeding. Example:

> **Project summary:**
> - Framework: OpenAI Agents SDK
> - Entry point: `app.py` (API mode via `RESTAPI.run()`)
> - Agents: `triage` (routes to sub-agents), `math` (handles math), `general` (handles everything else)
> - Tools: `calculator` (bound to `math`), `web_search` (bound to `general`)
> - Session: Redis
> - Extras: `[openai,api,redis]`

---

### Step 2: Ask What to Add

Ask the user what they want to add:

1. **A new tool** — A Python function that an agent can call
2. **A new agent** — A new specialist agent
3. **A handoff** — Wire an existing agent to delegate to another
4. **All of the above** — Add a new agent with its own tools and wire it into the existing handoff graph

---

### Step 3: Add a Tool

#### 3a. Write the Tool Function

Create the tool function in the project's tool file (usually `tool.py`, or wherever existing tools live).

**Rules:**
- Tool functions are **plain Python functions** (sync or async) with type annotations and a docstring.
- Use `ToolContext.get()` **inside** the function body to access session and runtime. Never pass context as a parameter.
- Use `__` (double underscore) as the nested delimiter in environment variable names (e.g., `AK_REDIS__URL`).

```python
from agentkernel.core import ToolContext


def lookup_order(order_id: str) -> str:
    """Look up an order by its ID and return the order details."""
    context = ToolContext.get()
    session = context.session

    # Use session cache for expensive lookups
    cache = session.get_non_volatile_cache()
    cached = cache.get(f"order:{order_id}")
    if cached:
        return cached

    # Your lookup logic here
    result = f"Order {order_id}: shipped, arriving tomorrow"
    cache[f"order:{order_id}"] = result
    return result
```

#### 3b. Bind the Tool to an Agent

The binding syntax depends on the framework. Match what the project already uses:

**OpenAI Agents SDK:**
```python
from agentkernel.openai import OpenAIToolBuilder

tools = OpenAIToolBuilder.bind([lookup_order, existing_tool_1])
agent = Agent(name="support", instructions="...", tools=tools)
```

**LangGraph:**
```python
from agentkernel.langgraph import LangGraphToolBuilder

tools = LangGraphToolBuilder.bind([lookup_order, existing_tool_1])
agent = create_react_agent(name="support", tools=tools, model=model, prompt="...")
```

**CrewAI:**
```python
from agentkernel.crewai import CrewAIToolBuilder

tools = CrewAIToolBuilder.bind([lookup_order, existing_tool_1])
agent = Agent(role="support", goal="...", backstory="...", tools=tools, verbose=False)
```

**Google ADK:**
```python
from agentkernel.adk import GoogleADKToolBuilder

tools = GoogleADKToolBuilder.bind([lookup_order, existing_tool_1])
agent = Agent(name="support", model=LiteLlm(model="openai/gpt-4o-mini"),
              description="...", instruction="...", tools=tools)
```

**Smolagents:**
```python
from agentkernel.smolagents import SmolagentsToolBuilder

tools = SmolagentsToolBuilder.bind([lookup_order, existing_tool_1])
agent = ToolCallingAgent(
    tools=tools,
    model=model,
    name="support",
    description="...",
)
```

> **Gotcha:** Always add the new tool to the **existing** `bind()` call for that agent. Don't create a second `bind()`.

---

### Step 4: Add an Agent

#### 4a. Define the Agent

Match the framework already in use:

**OpenAI Agents SDK:**
```python
from agents import Agent
from agentkernel.openai import OpenAIToolBuilder

support_agent = Agent(
    name="support",
    handoff_description="Specialist for customer support and order inquiries",
    instructions="You help customers with order lookups, returns, and general support questions.",
    tools=OpenAIToolBuilder.bind([lookup_order]),
)
```

**LangGraph:**
```python
from langchain.chat_models import init_chat_model
from langgraph.prebuilt import create_react_agent
from agentkernel.langgraph import LangGraphToolBuilder

model = init_chat_model("openai:gpt-4o-mini")
support_agent = create_react_agent(
    name="support",    # Always pass name= explicitly!
    tools=LangGraphToolBuilder.bind([lookup_order]),
    model=model,
    prompt="You help customers with order lookups, returns, and general support questions.",
)
```

> **Gotcha (LangGraph):** Always pass `name=` to `create_react_agent()`. Without it the agent is unnamed and the supervisor cannot route to it.

**CrewAI:**
```python
from crewai import Agent
from agentkernel.crewai import CrewAIToolBuilder

support_agent = Agent(
    role="support",     # CrewAI uses role= as the identifier, NOT name=
    goal="Specialist for customer support and order inquiries",
    backstory="You help customers with order lookups, returns, and general support questions.",
    tools=CrewAIToolBuilder.bind([lookup_order]),
    verbose=False,
)
```

> **Gotcha (CrewAI):** Use `role=` as the agent identifier — Agent Kernel maps `agent.role` to the agent name. Setting `verbose=False` keeps output clean.

**Google ADK:**
```python
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from agentkernel.adk import GoogleADKToolBuilder

support_agent = Agent(
    name="support",
    model=LiteLlm(model="openai/gpt-4o-mini"),  # Always wrap in LiteLlm()
    description="Specialist for customer support and order inquiries",
    instruction="You help customers with order lookups, returns, and general support questions.",
    tools=GoogleADKToolBuilder.bind([lookup_order]),
)
```

> **Gotcha (Google ADK):** Use `LiteLlm(model="openai/gpt-4o-mini")` — never pass a bare model string like `"gpt-4o-mini"`.

**Smolagents:**
```python
from smolagents import LiteLLMModel, ToolCallingAgent
from agentkernel.smolagents import SmolagentsToolBuilder

model = LiteLLMModel(model_id="openai/gpt-4o")
support_agent = ToolCallingAgent(
    tools=SmolagentsToolBuilder.bind([lookup_order]),
    model=model,
    name="support",
    description="You help customers with order lookups, returns, and general support questions.",
)
```

#### 4b. Register with the Module

Add the new agent to the **existing** Module constructor call. Do not create a second Module.

```python
# Before:
OpenAIModule([triage_agent, math_agent, general_agent])

# After:
OpenAIModule([triage_agent, math_agent, general_agent, support_agent])
```

This applies to all frameworks — `LangGraphModule`, `CrewAIModule`, `GoogleADKModule`, `SmolagentsModule` work the same way.

---

### Step 5: Add Handoffs

Wire the new agent into the existing routing so the triage/supervisor agent can delegate to it.

**OpenAI Agents SDK:**

Add the new agent to the triage agent's `handoffs` list:

```python
triage_agent = Agent(
    name="triage",
    instructions="You route requests to the right specialist agent...",
    handoffs=[math_agent, general_agent, support_agent],  # Add here
)
```

Update the triage instructions to mention the new agent:

```python
instructions = """You route user requests to the right specialist:
- math agent: for calculations and math problems
- general agent: for general knowledge questions
- support agent: for customer support and order inquiries   ← ADD THIS
"""
```

**LangGraph:**

Add the new agent to the supervisor's `agents` list:

```python
from langgraph_supervisor import create_supervisor

triage_agent = create_supervisor(
    model=model,
    agents=[math_agent, general_agent, support_agent],  # Add here
    prompt="Route requests to the right specialist...",
).compile(name="triage")
```

**CrewAI:**

No explicit routing — CrewAI automatically makes all agents in the Module available. Just add the new agent to the Module list (Step 4b). The `Crew` will include it.

**Google ADK:**

Add the new agent to the triage agent's `sub_agents`:

```python
from google.adk.agents import LlmAgent

triage_agent = LlmAgent(
    name="triage",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Routes requests to specialists",
    instruction="""Route requests to the right specialist.
Use transfer_to_agent to delegate:
- math: for calculations
- general: for general knowledge
- support: for customer support and order inquiries   ← ADD THIS
""",
    sub_agents=[math_agent, general_agent, support_agent],  # Add here
)
```

**Smolagents:**

Add the new agent to the triage agent's `managed_agents` list:

```python
triage_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="triage",
    description="You determine which agent to use based on the user's question.",
    managed_agents=[math_agent, general_agent, support_agent],  # Add here
)
```

---

### Step 6: Add Hooks (Optional)

Attach pre/post processing to the new agent. See the `ak-add-capabilities` skill for full hook patterns.

```python
# Pre-hook: runs before the agent processes the request
module.pre_hook(support_agent, [RAGPreHook()])

# Post-hook: runs after the agent generates a response
module.post_hook(support_agent, [DisclaimerPostHook()])
```

Where `module` is the framework Module instance (e.g., `OpenAIModule`). To use hooks, assign the Module to a variable:

```python
module = OpenAIModule([triage_agent, math_agent, general_agent, support_agent])
module.pre_hook(support_agent, [RAGPreHook()])
```

---

### Step 7: Update Dependencies (If Needed)

If the new tool or agent requires additional packages, update `pyproject.toml`:

```toml
dependencies = [
    "agentkernel[openai,api,redis]>=0.4.0",
    "httpx>=0.27.0",        # Add any new deps for your tool
]
```

Then run:
```bash
uv sync
```

---

### Step 8: Verify

1. **Syntax check** — Run: `uv run python -c "import app"` (or whatever the entry file is)

2. **Test the new agent** — Add a test for the new agent (see `ak-test` skill for test setup):

```python
@pytest.mark.order(10)
async def test_support_routing(test_client):
    await test_client.send("What's the status of order 12345?")
    await test_client.expect(["order", "12345", "shipped"])
```

3. **Run tests**:
```bash
uv run pytest -v
```

4. **Manual test** (API mode):
```bash
python app.py &
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Check order 12345", "session_id": "test-1", "agent": "triage"}'
```

---

### Common Gotchas

| Gotcha | Details |
|--------|---------|
| **ToolContext access** | Always use `ToolContext.get()` inside the tool function body. Never pass context as a function parameter. |
| **LangGraph `name=`** | Always pass `name=` to `create_react_agent()`. Without it, the supervisor cannot route to the agent. |
| **CrewAI `role=`** | Use `role=` as the agent identifier, not `name=`. Agent Kernel reads `agent.role` as the agent name. |
| **CrewAI `verbose=`** | Set `verbose=False` on agents to prevent noisy console output. |
| **Google ADK `LiteLlm`** | Wrap the model string: `LiteLlm(model="openai/gpt-4o-mini")`. A bare string won't work. |
| **Env var nesting** | Use `__` (double underscore) as the nested delimiter: `AK_REDIS__URL`, `AK_WHATSAPP__ACCESS_TOKEN`. |
| **Single Module** | Only one Module instance per framework. Add new agents to the existing Module's agent list. |
| **Single `bind()`** | Add new tools to the existing `ToolBuilder.bind()` call for that agent. Don't create a second one. |

---

### What to Do Next

Now that you've added new tools and agents to your project, here are natural next steps:

- **Add more tools & agents** → Use this `ak-build` skill again (it's meant to be used repeatedly)
- **Add guardrails, tracing, or sessions** → Use the `ak-add-capabilities` skill to add input/output guardrails (OpenAI, Bedrock, Walled AI), observability tracing (Langfuse, OpenLLMetry), session persistence (Redis, DynamoDB, Cosmos DB), MCP server, A2A protocol, custom hooks, or multimodal support
- **Connect a messaging platform** → Use the `ak-add-integration` skill to add Slack, WhatsApp, Messenger, Instagram, Telegram, or Gmail
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy to AWS Lambda, AWS ECS/Fargate, Azure Functions, or Azure Container Apps with Terraform
- **Set up testing** → Use the `ak-test` skill to configure test modes (fuzzy, judge, fallback), write agent tests, and debug common issues
