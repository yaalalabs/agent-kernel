# Research: Microsoft Agent Framework Integration into Agent Kernel

> **Issue**: [#720](https://github.com/yaalalabs/agent-kernel/issues/720) — Microsoft Agents Integration
> **Date**: 2026-10-02
> **Status**: Research complete, ready for design spec

---

## 1. Executive Summary

Microsoft Agent Framework (MAF) is Microsoft's unified, production-ready SDK for building, orchestrating, and deploying AI agents. Released as GA (v1.0) in April 2026, it supersedes and consolidates both **AutoGen** and **Semantic Kernel** into a single platform. Integrating MAF into Agent Kernel would make AK the first multi-framework orchestrator to support all seven major agent SDKs (OpenAI, CrewAI, LangGraph, Google ADK, Smolagents, Pydantic AI, and now Microsoft Agent Framework).

---

## 2. Microsoft Agent Framework — Background

### 2.1 History & Lineage

| Year | Event |
|------|-------|
| 2023 | Microsoft Research releases AutoGen (multi-agent conversational framework) |
| 2023 | Semantic Kernel reaches 1.0 (enterprise orchestration SDK) |
| 2025 | Microsoft announces Agent Framework as the unified successor |
| Apr 2026 | Agent Framework 1.0 GA released, consolidating AutoGen + Semantic Kernel |

### 2.2 Positioning

- **AutoGen** → research-grade multi-agent orchestration, team-based workflows
- **Semantic Kernel** → enterprise middleware, plugin architecture, OpenTelemetry
- **Agent Framework** → unified GA SDK: takes the multi-agent patterns from AutoGen and the enterprise features from SK, provides a single `pip install agent-framework`

### 2.3 Key Resources

| Resource | URL |
|----------|-----|
| GitHub Repository | https://github.com/microsoft/agent-framework |
| Samples Repository | https://github.com/microsoft/Agent-Framework-Samples |
| PyPI (core) | `agent-framework` |
| PyPI (OpenAI provider) | `agent-framework-openai` |
| PyPI (Foundry provider) | `agent-framework-foundry` |
| PyPI (AG-UI) | `agent-framework-ag-ui` |
| Python Import | `from agent_framework import Agent` |
| Language support | Python, .NET, Go |
| License | MIT |

---

## 3. MAF Architecture & Core Concepts

### 3.1 Agent Class

The primary abstraction is `Agent` (with `ChatAgent` as the LLM-backed implementation):

```python
from agent_framework import Agent

agent = Agent(
    name="weather_agent",
    chat_client=my_model_client,   # Azure OpenAI, OpenAI, Ollama, etc.
    tools=[get_weather],
    system_message="You are a helpful assistant."
)
```

Key properties:
- `name` — agent identifier
- `chat_client` — the LLM backend (protocol-based, any client implementing `IChatClient`)
- `tools` — list of tool functions (decorated with `@tool`)
- `system_message` — system instructions
- `middleware` — agent/function/chat middleware pipeline

### 3.2 Execution: `run()` and Streaming

**Non-streaming:**
```python
result = await agent.run("What is the weather in NYC?")
print(result.text)
```

**Streaming (unified via `stream=True`):**
```python
stream = agent.run("What is the weather?", stream=True)
async for update in stream:
    if update.text:
        print(update.text, end="", flush=True)
```

The streaming API yields `AgentResponseUpdate` objects with:
- `.text` — text delta (when present)
- `.tool_calls` — tool call information
- Other metadata fields

There is also `get_final_response()` for draining the stream:
```python
response_stream = agent.run("prompt", stream=True)
final = await response_stream.get_final_response()
```

### 3.3 Tools

Tools are defined with the `@tool` decorator:

```python
from agent_framework import tool, FunctionInvocationContext

@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: 73°F and sunny."

@tool
def search(query: str, ctx: FunctionInvocationContext) -> str:
    """Search with access to context."""
    session_id = ctx.session.session_id if ctx.session else "none"
    return f"Searched: {query}"
```

- The `@tool` decorator handles schema generation automatically
- `FunctionInvocationContext` provides runtime access to session, middleware chain, and kwargs
- Sub-agents can be used as tools via `agent.as_tool(propagate_session=True)`

### 3.4 Session & State Management

- Agents are inherently **stateless** — history must be managed externally
- `AgentSession` and `ChatMessageStore` provide session continuity
- Sessions are created explicitly: `session = agent.create_session()`
- State passes through `FunctionInvocationContext` in tools
- `StateBag` enables state persistence across channels

### 3.5 Middleware Pipeline

Three layers of middleware:

| Type | Intercepts | Use Cases |
|------|-----------|-----------|
| **Agent Middleware** | Agent execution (inputs/outputs) | Logging, guardrails, context injection |
| **Function Middleware** | Tool calls | Authorization, auditing |
| **Chat Client Middleware** | Raw LLM messages/options | Token counting, rate limiting, caching |

Middleware is registered as a sequence on the agent:
```python
agent = Agent(
    name="...",
    chat_client=client,
    middleware=[LoggingMiddleware(), GuardrailMiddleware()]
)
```

### 3.6 Multi-Agent Orchestration

MAF supports several orchestration patterns:

| Pattern | Builder | Description |
|---------|---------|-------------|
| Sequential | `SequentialBuilder` | Linear pipeline of agents |
| Concurrent | `ConcurrentBuilder` | Parallel agent execution |
| GroupChat | `GroupChatBuilder` | Team-based collaboration (Magentic supervisor pattern) |
| Handoff | `HandoffBuilder` | Agent-to-agent control transfer |
| Graph | Graph-based API | Custom DAG workflows |

Handoff uses synthetic tools generated by the framework:
```python
workflow = HandoffBuilder()
    .add_agent(researcher)
    .add_agent(writer)
    .build()
```

### 3.7 Structured Output

- Pydantic-based typed input/output schemas
- Agents can return structured responses when configured
- Maps cleanly to Agent Kernel's `AgentReplyAny`

### 3.8 Observability

- Native **OpenTelemetry** integration
- Built-in hooks for distributed tracing and monitoring
- DevUI for visual debugging of multi-agent workflows

### 3.9 Hosting Channels

MAF has hosting packages for external platforms:
- `agent-framework-hosting-telegram`
- `agent-framework-hosting-mcp`
- `agent-framework-hosting-a2a`
- These maintain session state across channels

---

## 4. Mapping MAF Concepts to Agent Kernel

This is the critical analysis: how each MAF abstraction maps onto Agent Kernel's core.

### 4.1 Concept Mapping Table

| MAF Concept | AK Concept | Mapping Strategy |
|------------|------------|------------------|
| `Agent` / `ChatAgent` | Native agent passed to `MAFModule` | Wrapped by `MAFAgent(BaseAgent)` |
| `agent.run()` (non-streaming) | `MAFRunner.run()` | Call `await agent.run(prompt)`, return `AgentReplyText` |
| `agent.run(stream=True)` | `MAFRunner.stream()` | Iterate `AgentResponseUpdate`, yield AK `StreamEvent` |
| `@tool` functions | `MAFToolBuilder.bind()` | Wrap callables with MAF's `@tool` decorator |
| `FunctionInvocationContext` | `ToolContext` | AK sets `ToolContext` via contextvar; MAF tools use `FunctionInvocationContext` |
| `AgentSession` / `ChatMessageStore` | `MAFSession` stored in AK `Session` | AK session wraps MAF's session state |
| Agent Middleware | AK PreHook/PostHook + MAF middleware | Pass through; don't re-implement |
| `StateBag` | `framework_context` | Map to AK's `_load_framework_context` / `_store_framework_context` |
| Multi-agent Workflows | Handled by MAF natively | Wrap the top-level workflow agent |
| Structured output | `AgentReplyAny` | Use `AgentReplyAny.from_output()` |

### 4.2 Streaming Event Mapping

| MAF Event | AK StreamEvent |
|-----------|---------------|
| Text delta in `AgentResponseUpdate` | `TextDelta(message_id=..., content=...)` |
| Start of response | `MessageStart(message_id=...)` |
| End of response | `MessageEnd(message_id=...)` |
| Tool call information | `ToolCallStart` / `ToolCallArgs` / `ToolCallEnd` |
| Tool result | `ToolCallResult` |

> **Note**: MAF uses `agent.run(stream=True)` returning a `ResponseStream` that yields `AgentResponseUpdate` objects. The exact event-level granularity needs to be verified against the actual SDK — if updates are coarse-grained (full tool calls rather than argument deltas), the mapping will be simpler than OpenAI's or Pydantic AI's.

### 4.3 Session Mapping

MAF agents are stateless by default; session/history is managed via:
1. `ChatMessageStore` — persists chat messages
2. `AgentSession` — wraps a session context

AK's approach:
- Create `MAFSession` class that holds the MAF session/message-store state
- Store under `session.set("maf", MAFSession())`
- On each `run()`, restore the MAF session state before calling `agent.run()`

### 4.4 Framework Context Round-Trip

- **Injection mechanism**: MAF's `FunctionInvocationContext.kwargs` (or session state)
- **AK's mechanism**: `_load_framework_context(session)` → inject into agent run → `_store_framework_context(session, incoming, produced)` after success
- **Fidelity**: Full round-trip expected via `StateBag`; needs verification

### 4.5 Tool Binding

MAF uses the `@tool` decorator. AK's ToolBuilder needs to wrap plain Python functions:

```python
class MAFToolBuilder(ToolBuilder):
    @classmethod
    def bind(cls, funcs: list) -> list:
        from agent_framework import tool as maf_tool
        tools = []
        for func in funcs:
            if not callable(func):
                raise TypeError(f"Expected callable, got {type(func).__name__}")
            # MAF's @tool wraps functions similarly to OpenAI's function_tool
            tools.append(maf_tool(func))
        return tools
```

---

## 5. Comparison with Existing AK Adapters

### 5.1 Closest Existing Adapter: Pydantic AI

The Pydantic AI adapter is the most analogous because:
- Both MAF and Pydantic AI use an explicit `Agent` class with named agents
- Both support async execution
- Both have native streaming via async iterators
- Both use explicit session/history management
- Both support structured output

The MAF adapter should follow the PydanticAI adapter's structure closely.

### 5.2 Key Differences from OpenAI Adapter

| Aspect | OpenAI Adapter | MAF Adapter (planned) |
|--------|---------------|----------------------|
| SDK runner | `Runner.run()` (static class method) | `agent.run()` (instance method) |
| Streaming API | `Runner.run_streamed()` → `stream_events()` | `agent.run(stream=True)` → async iter |
| Session | `OpenAISession` with items list | `MAFSession` wrapping `ChatMessageStore` |
| Tool binding | `function_tool(func)` | `@tool` decorator |
| Structured output | `final_output` type inspection | Response type configuration |

---

## 6. Risk Analysis

### 6.1 Low Risk

- **Adapter pattern is well-established**: Six adapters already exist; the pattern is battle-tested
- **MAF supports async**: `asyncio` first-class, `await agent.run()` maps directly
- **Streaming support exists**: `agent.run(stream=True)` provides async iteration
- **Named agents**: MAF agents have explicit `name` property, no name-inference issues

### 6.2 Medium Risk

- **Streaming event granularity**: Need to verify whether `AgentResponseUpdate` provides delta-level events or coarse-grained updates. If coarse-grained, streaming will be simpler but less granular than OpenAI/PydanticAI
- **Tool context propagation**: MAF uses `FunctionInvocationContext` while AK uses `ToolContext`. Need to ensure both are accessible during tool execution
- **Framework context round-trip fidelity**: Need to test whether `StateBag` state survives the AK serialization path (picklability)

### 6.3 Higher Risk

- **SDK stability**: MAF 1.0 just reached GA in April 2026; API surface may still evolve
- **Multi-agent workflow state**: MAF workflows (HandoffBuilder, GroupChatBuilder) carry internal state that may not fit cleanly into AK's single-agent-per-Runtime-run model. Wrapping the top-level workflow agent should work, but deeper integration of workflow state is complex
- **Middleware interop**: MAF's middleware pipeline runs independently from AK's PreHook/PostHook pipeline. The two should not conflict, but the order of execution needs careful documentation

---

## 7. Open Questions

1. **Streaming event shape**: What exact fields does `AgentResponseUpdate` expose? Are text deltas per-token or per-chunk? Are tool call arguments streamed or delivered whole?
2. **Session serialization**: Is `ChatMessageStore` picklable? If not, what serialization path is needed for AK's session stores?
3. **Multi-agent wrapper**: When wrapping a MAF workflow (e.g., `HandoffBuilder.build()` result), does the workflow expose the same `run()` / `run(stream=True)` API as a single agent?
4. **Chat client flexibility**: MAF requires a `chat_client` — should AK auto-construct one from `AKConfig`, or require the user to pass it (consistent with AK's "wrap, don't abstract" principle)?
5. **Version pinning**: What minimum MAF version should AK require? (`>=1.0.0`?)

---

## 8. Useful Links

### Official Resources
- **GitHub**: https://github.com/microsoft/agent-framework
- **Samples**: https://github.com/microsoft/Agent-Framework-Samples
- **PyPI**: https://pypi.org/project/agent-framework/
- **Microsoft Learn**: https://learn.microsoft.com/en-us/python/api/agent-framework/

### Related Resources
- **Azure AI Foundry SDK**: https://pypi.org/project/azure-ai-projects/ (deployment/hosting)
- **AutoGen (predecessor)**: https://github.com/microsoft/autogen
- **Semantic Kernel (predecessor)**: https://github.com/microsoft/semantic-kernel

### Agent Kernel Internal References
- **Framework integration skill**: [ak-dev-new-framework-integration](../../.agents/skills/ak-dev-new-framework-integration/SKILL.md)
- **Architecture skill**: [ak-dev-architecture](../../.agents/skills/ak-dev-architecture/SKILL.md)
- **Pydantic AI spec (closest precedent)**: [531-introduce-pydanticai-framework](../531-introduce-pydanticai-framework/)
- **OpenAI adapter (canonical reference)**: [ak-py/src/agentkernel/framework/openai/openai.py](../../../ak-py/src/agentkernel/framework/openai/openai.py)
- **Pydantic AI adapter**: [ak-py/src/agentkernel/framework/pydanticai/pydanticai.py](../../../ak-py/src/agentkernel/framework/pydanticai/pydanticai.py)

---

## 9. Recommended Approach

Based on this research, the recommended integration approach is:

1. **Framework identifier**: `maf` (short for Microsoft Agent Framework; avoids confusion with `microsoft` being too generic)
2. **Follow PydanticAI adapter pattern**: The closest structural match
3. **Streaming**: Implement `supports_streaming = True`, map `AgentResponseUpdate` fields onto AK `StreamEvent` types
4. **Session**: Create `MAFSession` wrapping MAF's `ChatMessageStore` state, serialized as jsonable dicts (same pattern as PydanticAI)
5. **Framework context**: Map to MAF's `StateBag` or `FunctionInvocationContext.kwargs`
6. **Tool binding**: Wrap callables with MAF's `@tool` decorator
7. **PyPI extras**: `maf = ["agent-framework>=1.0.0"]`
8. **Wrap, don't abstract**: Pass MAF's native `chat_client`, `middleware`, etc. through unchanged; AK wraps at the boundary only
