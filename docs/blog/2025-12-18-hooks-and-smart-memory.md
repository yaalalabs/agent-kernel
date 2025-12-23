---
slug: /hooks-and-smart-memory
title: "Power Up Your Agents: Execution Hooks and Smart Memory in Agent Kernel"
authors: [yaala]
tags: [agent-kernel, hooks, memory, RAG, guard-rails, cache, execution-hooks, pre-hooks, post-hooks]
image: /img/card.png
---

# Power Up Your Agents: Execution Hooks and Smart Memory in Agent Kernel

Ever wished you could intercept your AI agent's thoughts before they speak? Or give them a photographic memory that lasts exactly as long as you need? We've got you covered.

Agent Kernel now features **Execution Hooks** and **Smart Memory Management** - two game-changing capabilities that give you surgical control over how your agents think, remember, and respond. Whether you're building enterprise chatbots, RAG-powered assistants, or multi-agent systems, these features unlock new levels of sophistication without the complexity.

<!-- truncate -->

## The Challenge: Control Meets Flexibility

Building production AI agents isn't just about picking the right LLM. You need:

- **Safety mechanisms** that prevent harmful outputs before they escape
- **Context injection** to make your agents smarter with domain knowledge
- **Memory that adapts** to different use cases - ephemeral for some data, persistent for others
- **Audit trails** that show exactly what your agent saw and said

Traditional approaches force you to hack this together with prompt engineering, custom middleware, or framework-specific workarounds. Agent Kernel takes a different path: **first-class support** for hooks and memory that works across any framework.

## Execution Hooks: Your Agent's Control Panel

Think of hooks as strategic checkpoints in your agent's execution pipeline. You get two powerful interception points:

### Pre-Execution Hooks: Shape the Input

These run **before** your agent sees the user's prompt. Perfect for:

**🛡️ Guard Rails** - Block inappropriate content before it reaches your agent:

```python
class GuardRailHook(PreHook):
    BLOCKED_KEYWORDS = ["hack", "illegal", "exploit"]
    
    async def on_run(self, session, agent, requests):
        prompt = requests[0].text.lower()
        
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in prompt:
                return AgentReplyText(
                    text=f"I cannot assist with requests related to '{keyword}'."
                )
        
        return requests  # Safe - proceed to agent
```

**🧠 RAG Context Injection** - Enrich prompts with knowledge from your databases:

```python
class RAGHook(PreHook):
    async def on_run(self, session, agent, requests):
        prompt = requests[0].text
        
        # Search your knowledge base
        context = await search_knowledge_base(prompt)
        
        # Inject context into the prompt
        enriched_prompt = f"""Context: {context}
        
Question: {prompt}"""
        
        return [AgentRequestText(text=enriched_prompt)]
```

**💡 Pro Tip: Custom Data in REST API Mode**

When using Agent Kernel's REST API, you can pass custom data in your JSON request body beyond the standard `agent`, `session_id`, and `prompt` fields. Any additional keys are automatically converted to `AgentRequestAny` objects and passed to your pre-hooks:

```bash
# REST API request with custom fields
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "assistant",
    "session_id": "user-123",
    "prompt": "What is my account status?",
    "user_id": "12345",
    "additional_context": {
      "account_type": "premium",
      "region": "us-west"
    }
  }'
```

In your pre-hook, access these custom fields:

```python
class CustomDataHook(PreHook):
    async def on_run(self, session, agent, requests):
        # Find custom data in requests
        user_id = None
        additional_context = None
        
        for req in requests:
            if isinstance(req, AgentRequestAny):
                if req.name == "user_id":
                    user_id = req.content
                elif req.name == "additional_context":
                    additional_context = req.content
        
        # Use the data for personalization, auth, etc.
        if user_id and additional_context:
            # Store in cache for tools to access
            session.get_non_volatile_cache().set("user_id", user_id)
            session.get_non_volatile_cache().set("context", additional_context)
        
        return requests
```

This is powerful for passing metadata like user IDs, session context, feature flags, or any custom data your hooks need **without cluttering the actual prompt** sent to the LLM. The custom fields are processed by your hooks but never sent to the agent unless you explicitly add them.

### Post-Execution Hooks: Polish the Output

These run **after** your agent generates a response. Ideal for:

**⚖️ Adding Disclaimers** - Compliance made automatic:

```python
class DisclaimerHook(PostHook):
    async def on_run(self, session, requests, agent, agent_reply):
        disclaimer = "\n\n*This is AI-generated. Verify important decisions.*"
        agent_reply.text += disclaimer
        return agent_reply
```

**🔒 Output Moderation** - Filter sensitive information from responses

**📊 Analytics** - Log interactions for monitoring and improvement

### Hook Chaining: The Power of Composition

Multiple hooks execute in sequence, each building on the last:

```python
from agentkernel.openai import OpenAIModule
from agents import Agent

# Create agent
agent = Agent(name="assistant", instructions="You are a helpful assistant.")

# Register hooks in order using method chaining
OpenAIModule([agent]).pre_hook(agent, [
    RAGHook(),        # Add context first
    GuardRailHook(),  # Then validate everything
]).post_hook(agent, [
    ModerationHook(),   # Filter sensitive content
    DisclaimerHook(),   # Add legal disclaimer
])
```

**Flow:** User Input → RAG → Guard Rails → Agent → Moderation → Disclaimer → Final Response

If any pre-hook returns an `AgentReply` (like guard rails blocking a request), execution **stops immediately** - the agent never sees the prompt.

## Smart Memory: The Right Persistence at the Right Time

Not all data needs to live forever. Agent Kernel gives you two types of cache with identical APIs but different lifecycles:

### Volatile Cache: Ephemeral Context

Data that lives **only during a single request execution** and vanishes afterward:

```python
# In a pre-hook - inject context into cache
cache = session.get_volatile_cache()
cache.set("rag_context", retrieved_documents)

# In a tool - retrieve the context
cache = GlobalRuntime.instance().get_volatile_cache()
docs = cache.get("rag_context")
return query_documents(docs, question)
```

**Perfect for:**
- 📄 Document content from file uploads (don't clutter prompts)
- 🔍 RAG search results (fresh every request)
- 🔢 Temporary calculations and intermediate data
- 🧪 Request-scoped feature flags

### Non-Volatile Cache: Persistent Memory

Data that **persists across multiple requests** in the same session:

```python
# First request - store user preferences
cache = session.get_non_volatile_cache()
cache.set("user_language", "Spanish")
cache.set("notification_enabled", True)

# Later requests - retrieve preferences
language = cache.get("user_language")  # Still "Spanish"
```

**Perfect for:**
- 👤 User preferences and settings
- 📝 Extracted metadata from conversations
- 🎯 Session-specific configurations
- 🏷️ Tags and classifications

### Why This Matters: Clean Prompts, Lower Costs

Instead of stuffing everything into the prompt:

**Before (bloated prompt):**
```python
prompt = f"""
User preferences: {json.dumps(prefs)}
Document content: {huge_document}
Previous context: {conversation_history}

Question: {user_question}
"""
```

**After (clean and efficient):**
```python
# Store in appropriate cache
volatile.set("document", huge_document)
non_volatile.set("preferences", prefs)

# Simple prompt
prompt = user_question  # Agent tools fetch from cache as needed
```

**Benefits:**
- ✂️ **Reduced token usage** - Only send what the LLM needs to see
- ⚡ **Faster responses** - Less to process per request
- 💰 **Lower costs** - Fewer tokens = smaller bills
- 🧹 **Cleaner prompts** - Focus on the actual question

### Real-World Example: RAG with Cache

Check out our [key-value-cache example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/memory/key-value-cache):

```python
# Senior assistant with RAG hook
@function_tool
def query_knowledge_base(query: str) -> str:
    cache = GlobalRuntime.instance().get_volatile_cache()
    context = cache.get("rag_context")  # Retrieved by pre-hook
    
    if context:
        return search_in_context(query, context)
    return "No information found."

# Register the hook with the Module
OpenAIModule([senior_assistant]).pre_hook(senior_assistant, [RAGHook()])
```

The `RAGHook` searches your knowledge base and populates the cache. The tool accesses it transparently. The prompt stays clean.

## Framework-Agnostic Magic

Here's the best part: **this works with any agent framework** Agent Kernel supports:

- OpenAI Agents SDK
- LangGraph
- CrewAI
- Google ADK

Same hook code. Same cache API. Different frameworks. One unified experience.

```python
# Works with OpenAI
from agentkernel.openai import OpenAIModule
OpenAIModule([my_openai_agent]).pre_hook(my_openai_agent, [RAGHook()])

# Works with CrewAI
from agentkernel.crewai import CrewAIModule
CrewAIModule([my_crew_agent]).pre_hook(my_crew_agent, [RAGHook()])

# Same hooks and cache for both!
cache = session.get_volatile_cache()
```

## Production-Ready Architecture

Behind the scenes, Agent Kernel's memory system supports multiple backends:

**Development:**
```bash
export AK_SESSION__TYPE=in_memory
```

**Production (Redis):**
```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://your-redis-instance
```

**Production (DynamoDB):**
```bash
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-sessions
```

Same code, different backends. Swap them with environment variables.

## Getting Started in Minutes

### 1. Install Agent Kernel

```bash
pip install agentkernel
```

### 2. Create a Hook

```python
from agentkernel import PreHook
from agentkernel import AgentRequestText

class SimpleRAGHook(PreHook):
    async def on_run(self, session, agent, requests):
        # Add context from your knowledge base
        context = get_relevant_context(requests[0].text)
        enriched = f"Context: {context}\n\nQuestion: {requests[0].text}"
        return [AgentRequestText(text=enriched)]
    
    def name(self):
        return "SimpleRAGHook"
```

### 3. Register and Run

```python
from agentkernel import GlobalRuntime
from agentkernel.openai import OpenAIModule
from agents import Agent

agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

# Register agent and hooks using method chaining
OpenAIModule([agent]).pre_hook(agent, [SimpleRAGHook()])

# Use CLI, REST API, or deploy to AWS
from agentkernel.api import RESTAPI
RESTAPI.run()
```

### 4. Test It

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "assistant",
    "session_id": "test-123",
    "prompt": "What is Agent Kernel?"
  }'
```

Your hook enriches the prompt before the agent sees it. Magic! ✨

## Learn More

**Examples:**
- 🎯 [Hooks Example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/hooks) - Guard rails, RAG, and disclaimers
- 💾 [Memory Example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/memory/key-value-cache) - Volatile and non-volatile cache
- ☁️ [Redis/DynamoDB Examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/memory) - Production memory backends

**Documentation:**
- 📚 [Execution Hooks Guide](/docs/integrations/hooks) - Complete reference with examples
- 🧠 [Memory Management](/docs/architecture/memory-management) - Cache backends and configuration
- 🏗️ [Core Concepts](/docs/core-concepts/overview) - Understanding Agent Kernel architecture

## Why This Matters

Agent Kernel's hooks and memory system give you:

✅ **Separation of Concerns** - Business logic separate from agent framework code  
✅ **Reusability** - Write hooks once, use across all agents and frameworks  
✅ **Testability** - Unit test hooks independently from agents  
✅ **Composability** - Chain hooks to build complex behaviors  
✅ **Performance** - Cache reduces token usage and costs  
✅ **Flexibility** - Swap memory backends without code changes  

This is the kind of control you need for **production AI agents** that are safe, smart, and cost-effective.

## What's Next?

We're not stopping here. Coming soon:

- 🔐 **RBAC Hooks** - Role-based access control out of the box
- 🤖 **Human-in-the-Loop** - Pause execution for human approval
- 🌊 **Streaming Hooks** - Real-time interception for streaming responses
- 📦 **Hook Marketplace** - Share and discover community hooks

Ready to level up your agents? [Get started with Agent Kernel today](/docs/quick-start) and join our [Discord community](https://discord.gg/snrPzb46uu) to share what you build!

---

**Built with ❤️ by [Yaala Labs](https://www.yaalalabs.com/)**
