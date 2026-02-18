---
slug: /framework-agnostic-tool-binding
title: "Write Once, Run Anywhere: Universal Tools for AI Agents"
authors: [yaala]
tags: [agent-kernel, tools, openai, google-adk, crewai, langgraph, framework-agnostic, portability]
image: /img/card.png
---

# Write Once, Run Anywhere: Universal Tools for AI Agents

**Stop rewriting the same tools for different AI frameworks.**

Imagine building a calculator app, then discovering you need to rebuild it from scratch every time you want to run it on a different device. That's what building AI agent tools feels like today.

Write a weather lookup tool for OpenAI? It won't work with Google's framework. Build it for CrewAI? Start over if you switch to LangGraph. This wastes time and creates headaches every time you want to try a new AI framework.

**Agent Kernel solves this: write your tools once, use them everywhere.**

<!-- truncate -->

## The Problem: Every Framework Wants Tools Written Differently

Think of tools as capabilities you give your AI agent—like looking up weather, searching a database, or sending emails. Right now, each AI framework requires you to write these tools in a completely different way.

Here's the same weather tool written for four different frameworks:

```python
# OpenAI version
@function_tool
def get_weather(city: str) -> str:
    return f"Weather in {city}: sunny"

# CrewAI version  
@tool
def get_weather(city: str) -> str:
    return f"Weather in {city}: sunny"

# LangGraph version
@tool
def get_weather(city: str) -> str:
    return f"Weather in {city}: sunny"

# Google ADK version
def _get_weather(city: str) -> str:
    return f"Weather in {city}: sunny"
get_weather = FunctionTool(_get_weather)
```

**It's the same weather lookup, but you have to write and maintain four different versions.**

Want to switch frameworks? Rewrite everything. Want to try a new framework alongside your current one? Duplicate all your tools. Building 10 custom tools means maintaining 40 versions if you use all four frameworks.

## The Solution: Write Normal Python Functions

With Agent Kernel, you write your tools as regular Python functions—no special decorators or framework-specific code:

```python
def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"
```

That's it. Just a normal Python function with a helpful description. Then use it with any framework you want.

## Using Your Tool with Any Framework

Once you've written your tool as a normal Python function, you can add it to agents in any framework. The only thing that changes is one line of code:

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs>
<TabItem value="openai" label="OpenAI Agents" default>

```python
from agents import Agent
from agentkernel.openai import OpenAIToolBuilder

weather_agent = Agent(
    name="weather",
    instructions="You provide weather information.",
    tools=OpenAIToolBuilder.bind([get_weather]),  # ← Add your tool here
)
```

</TabItem>
<TabItem value="crewai" label="CrewAI">

```python
from crewai import Agent
from agentkernel.crewai import CrewAIToolBuilder

weather_agent = Agent(
    role="weather",
    goal="You provide weather information",
    backstory="Use the get_weather tool for queries.",
    tools=CrewAIToolBuilder.bind([get_weather]),  # ← Add your tool here
)
```

</TabItem>
<TabItem value="langgraph" label="LangGraph">

```python
from langgraph.prebuilt import create_react_agent
from agentkernel.langgraph import LangGraphToolBuilder

weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),  # ← Add your tool here
    model=model,
    prompt="Use the get_weather tool for queries.",
)
```

</TabItem>
<TabItem value="adk" label="Google ADK">

```python
from google.adk.agents import Agent
from agentkernel.adk import GoogleADKToolBuilder

weather_agent = Agent(
    name="weather",
    model="gemini-2.0-flash-exp",
    description="You provide weather information",
    tools=GoogleADKToolBuilder.bind([get_weather]),  # ← Add your tool here
)
```

</TabItem>
</Tabs>

**Same `get_weather` function. Works everywhere.**

The `.bind()` method translates your normal Python function into whatever format each framework needs. You don't have to worry about the details—just write your function once and use it anywhere.

## Why Framework-Agnostic Tools Are So Hard

Making tools work across frameworks sounds simple, but it's actually quite challenging. Each framework has its own way of handling tools, and these differences create real technical problems.

### Different Execution Models

Frameworks handle async/sync functions differently:

**LangGraph (LangChain)** requires you to specify whether a tool is async or sync upfront:
```python
# Sync tools use 'func' parameter
StructuredTool.from_function(func=my_tool)

# Async tools use 'coroutine' parameter
StructuredTool.from_function(coroutine=my_async_tool)
```

**OpenAI Agents SDK** automatically handles both, but wraps them differently internally.

**Google ADK** expects all tools to potentially receive a `tool_context` parameter from the framework itself, which other frameworks don't provide.

Agent Kernel detects whether your function is async or sync and generates the right code for each framework automatically. You just write `def` or `async def`.

### Different Context Mechanisms

This is the hardest problem: frameworks provide execution context (session info, runtime state) in completely different ways.

**OpenAI, CrewAI, LangGraph** work well with Python's standard `contextvars`, which lets you set context in one place and access it anywhere in the call stack:

```python
# Set once before calling agent
context.set()

# Access anywhere in your tool
ctx = ToolContext.get()
```

**Google ADK** manages its own execution context internally and doesn't reliably propagate Python's `contextvars`. Instead, it passes a `tool_context` parameter to every tool function:

```python
# ADK calls your tool like this:
def my_tool(city: str, tool_context: ADKToolContext):
    # ADK's context, not yours
```

This means your tool function signature must be different for ADK versus other frameworks. Or does it?

Agent Kernel solves this by:
1. **Wrapping tools for ADK** - Adding the `tool_context` parameter automatically
2. **Bridging contexts** - Converting ADK's context to Agent Kernel's unified `ToolContext`
3. **Passing context through session state** - Storing context IDs in ADK's session and retrieving them in the wrapper

All this happens behind the scenes. You write one function, and it works everywhere.

### Different Tool Metadata Requirements

Each framework expects different information about your tool:

| Framework | Name Source | Description Source | Schema Generation |
|-----------|-------------|-------------------|-------------------|
| OpenAI | Function name | Docstring | Automatic from type hints |
| CrewAI | Function name | Docstring | Automatic from type hints |
| LangGraph | Must specify | Must specify or falls back to function name | Must extract from function |
| Google ADK | Function name | Function name if no docstring | Type inspection required |

Agent Kernel extracts metadata once from your Python function (name, docstring, parameters, types) and formats it appropriately for each framework.

### Different Error Handling

When a tool raises an exception, frameworks handle it differently:

- **OpenAI** catches exceptions and reports them to the model
- **LangGraph** can retry tools or propagate errors through the graph
- **CrewAI** logs errors and may retry depending on agent configuration
- **Google ADK** wraps errors in its own exception types

Agent Kernel doesn't hide these differences (they're tied to framework behavior), but it ensures your tool code doesn't need to know which framework is calling it.

### Different Import Paths and Dependencies

Each framework's tool classes come from different packages:

```python
from agents import function_tool              # OpenAI
from crewai_tools import tool                 # CrewAI  
from langchain_core.tools import StructuredTool  # LangGraph
from google.adk.tools import FunctionTool     # Google ADK
```

If you write tools using framework-specific decorators, you're locked in. Agent Kernel's `ToolBuilder` classes handle these imports internally, so your tool code has zero framework dependencies.

### The Hidden Complexity

Here's what Agent Kernel does behind the scenes for a single tool:

1. **Inspects your function** - signature, type hints, docstring, async/sync
2. **Generates metadata** - name, description, parameter schema
3. **Creates framework wrapper** - adds any framework-specific parameters
4. **Handles context bridging** - ensures `ToolContext.get()` works in your tool
5. **Preserves semantics** - maintains async/sync behavior correctly
6. **Validates at bind time** - catches errors early with clear messages

All so you can write this:

```python
def my_tool(param: str) -> str:
    """Does something useful."""
    return result

tools = AnyFrameworkToolBuilder.bind([my_tool])
```

**This simplicity is hard-won.** Framework-agnostic tools require handling edge cases most developers never see.

## Accessing Runtime Information

Sometimes your tools need to know things like "which user is asking?" or "what session is this?" Agent Kernel provides this information in a consistent way, regardless of which framework you're using:

```python
from agentkernel.core import ToolContext

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    # Get information about the current execution
    ctx = ToolContext.get()
    
    session = ctx.session      # Who's asking?
    agent = ctx.agent          # Which agent is calling this?
    
    # Example: Use session data for personalization
    user_prefs = session.get_non_volatile_cache().get("preferences", {})
    units = user_prefs.get("temperature_units", "celsius")
    
    return f"Weather in {city}: sunny, 25°C"
```

This works the same way across all frameworks—you don't need to learn different methods for each one.

## Real Example: Switching Frameworks Is Easy

Here's a complete example using OpenAI:

```python
from agentkernel.core import ToolContext
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    else:
        return f"Cannot find weather for {city}."

# Create agents
weather_agent = Agent(
    name="weather",
    instructions="Use the get_weather tool for weather questions.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

math_agent = Agent(
    name="math",
    instructions="You help with math problems.",
)

triage_agent = Agent(
    name="triage",
    instructions="Route questions to the right agent.",
    handoffs=[math_agent, weather_agent],
)

OpenAIModule([triage_agent, math_agent, weather_agent])
```

**Want to try LangGraph instead?** Change just the framework-specific parts:

```python
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langgraph.prebuilt import create_react_agent

# Same get_weather function - no changes!

weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),  # Different builder
    model=ChatOpenAI(model="gpt-4o-mini"),
    prompt="Use the get_weather tool for weather questions.",
)

# Define other agents...
LangGraphModule([triage_agent, math_agent, weather_agent])
```

Your `get_weather` function? **Completely untouched.** No rewriting. No debugging. Just works.

## Async Functions Work Too

If your tool needs to do asynchronous work (like database queries or API calls), just write it as an async function:

```python
async def search_database(query: str, limit: int = 10) -> str:
    """Searches the database for matching records."""
    results = await db.search(query, limit=limit)
    return str(results)

# Works with any framework automatically
tools = OpenAIToolBuilder.bind([search_database])
tools = LangGraphToolBuilder.bind([search_database])
tools = GoogleADKToolBuilder.bind([search_database])
```

Agent Kernel handles the async details for you—just write your function normally.

## Using Multiple Tools

Real agents usually need multiple tools. Just add them all to the list:

```python
tools = OpenAIToolBuilder.bind([
    get_weather,
    search_database,
    send_email,
    get_user_profile,
])

agent = Agent(
    name="assistant",
    instructions="You're a helpful assistant with multiple tools.",
    tools=tools,
)
```

All tools work together seamlessly, regardless of your framework.

## Why This Matters

### 1. Try Different Frameworks Without Rewriting Code

Want to see if LangGraph is better than OpenAI for your use case? Just switch. Your tools keep working. No migration project needed.

### 2. Much Simpler Testing

Test your tools as regular Python functions:

```python
def test_get_weather():
    result = get_weather("Tokyo")
    assert "sunny" in result.lower()
```

No complicated framework setup. No mocking. Just normal Python testing.

### 3. Cleaner, More Readable Code

Your tools are just functions. Easy to read. Easy to understand. Easy to maintain. No framework magic hiding what your code does.

### 4. Faster Team Onboarding

New developers don't need to learn framework-specific tool systems. They write regular Python functions. Everything else is handled automatically.

## Local Tools vs. MCP: When to Use Each

You might have heard of **MCP (Model Context Protocol)** and wonder: "Should I use MCP for my tools, or build them locally?"

The answer depends on what your tools do. Let's break it down simply:

### MCP: External Services

MCP is designed for **connecting to external tool servers** that run as separate processes. Think of it like calling a web API or external service.

**Use MCP when:**
- Tools are provided by external services (like a company-wide document search server)
- Multiple teams share the same tool infrastructure
- Tools need to run independently of your agent (different machines, different languages)
- You're connecting to third-party tool providers

**MCP Example:**
```
Your Agent → Network → MCP Server → External Database
```

### Agent Kernel Tools: Part of Your Code

Agent Kernel's tool binding is for **tools that are part of your agent's business logic**—functions that live in your codebase alongside your agents.

**Use local tool binding when:**
- Tools are specific to your agent's logic (like calculating pricing, formatting data)
- Tools access your application's state or databases directly
- You want simple, fast function calls without network overhead
- You want to test tools as regular Python code

**Local Tool Example:**
```
Your Agent → Direct Function Call → Your Code
```

### Why Local Tools Are Often Better

For most business logic, building tools directly in your agent code is simpler and more efficient:

#### 1. No Extra Complexity
```python
# Local tool - just a function
def calculate_price(quantity: int, item_type: str) -> float:
    """Calculate price with discounts."""
    base_price = PRICES[item_type] * quantity
    discount = get_bulk_discount(quantity)
    return base_price * (1 - discount)

# Use it immediately
tools = OpenAIToolBuilder.bind([calculate_price])
```

With MCP, you'd need to:
- Set up a separate MCP server process
- Define network protocols
- Handle connection errors and retries
- Manage server lifecycle

#### 2. Faster Execution

Local tools are just function calls—microseconds. MCP involves network requests—milliseconds or more. For tools that run frequently, this adds up.

```python
# Local: Direct call, ~microseconds
result = calculate_price(100, "widget")

# MCP: Network round-trip, ~10-100ms
result = await mcp_client.call_tool("calculate_price", {...})
```

#### 3. Easier Testing

```python
# Test local tools like any Python function
def test_bulk_discount():
    price = calculate_price(quantity=100, item_type="widget")
    assert price < calculate_price(quantity=10, item_type="widget")

# MCP tools require running a server, mocking network calls, etc.
```

#### 4. Better Debugging

When something goes wrong with a local tool, your debugger works normally. Step through your code, inspect variables, see the full stack trace.

With MCP, you're debugging across process boundaries and network calls. Much harder.

#### 5. Simpler Deployment

Local tools deploy with your agent—one Docker container, one deployment. MCP tools need separate infrastructure, monitoring, and coordination.

### When MCP Makes Sense

Don't get us wrong—MCP is valuable for the right use cases:

**Shared Corporate Tools:**
Your company has a central "Employee Directory" service used by 50 different AI agents. One MCP server, everyone connects to it.

**External Services:**  
You're integrating with a third-party tool provider (like a specialized search engine or data enrichment service) that offers MCP access.

**Language Boundaries:**
Your tool is written in Rust for performance, but your agent is in Python. MCP lets them communicate.

**Heavy Resources:**
Your tool needs 64GB of RAM and a GPU. Run it on a dedicated server via MCP instead of bundling it with every agent instance.

### The Practical Rule

**Start with local tools.** They're simpler, faster, and easier to build and test.

Only use MCP when you have a specific reason:
- The tool truly needs to be external
- Multiple agents need to share one tool instance
- The tool is provided by someone else as a service

For most business logic—data formatting, calculations, querying your own databases, calling your internal APIs—local tools are the right choice.

### Best of Both Worlds

Agent Kernel supports both approaches. Use local tools for your custom logic, and connect to MCP servers when you need external capabilities:

```python
# Local tools for your business logic
local_tools = OpenAIToolBuilder.bind([
    calculate_price,
    format_invoice,
    check_inventory,
])

# MCP tools for external services (if needed)
# Connect to MCP server for shared document search
mcp_tools = await connect_to_mcp_server("company-docs")

# Use both together
agent = Agent(
    name="sales_assistant",
    tools=local_tools + mcp_tools,
)
```

**The key insight:** Local tools and MCP serve different purposes. Don't add MCP complexity unless you need it. For most agent development, simple local tools are the better choice.

## What Your Tools Keep

When you write a tool as a normal Python function, Agent Kernel automatically extracts everything the AI needs to know:

- **Function name** → The tool's name
- **Docstring** → Description (helps the AI know when to use it)
- **Parameters** → What inputs the tool needs
- **Default values** → Optional parameters
- **Return type** → What the tool gives back

The AI sees the same tool, no matter which framework you use.

## Getting Started

Using framework-agnostic tools is simple:

### 1. Install Agent Kernel

```bash
pip install agentkernel
```

### 2. Write your tool as a normal function

```python
def my_tool(param: str) -> str:
    """Description of what this tool does."""
    # Your code here
    return result
```

### 3. Add it to your agent

```python
from agentkernel.openai import OpenAIToolBuilder
from agents import Agent

agent = Agent(
    name="my_agent",
    instructions="Use my_tool when needed.",
    tools=OpenAIToolBuilder.bind([my_tool]),
)
```

That's all. Three steps, and your tool works across all frameworks.

---

**Stop maintaining multiple versions of the same tool.**

Write your tools once. Test them once. Use them everywhere. That's the promise of framework-agnostic tools in Agent Kernel.

Try different frameworks. Migrate painlessly. Focus on building great tools, not maintaining duplicates.

---

## Learn More

- **[Tool Documentation](https://yaalalabs.github.io/agent-kernel/docs/core-concepts/tools)** — Complete guide with more examples
- **[Code Examples](https://github.com/yaalalabs/agent-kernel/tree/main/examples)** — Working examples for all frameworks
- **[Join our Community](https://github.com/yaalalabs/agent-kernel)** — Questions? We're here to help

Start building framework-agnostic tools today. Your future self will thank you.
