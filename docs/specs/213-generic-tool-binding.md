# Framework agnostic tooling

This feature introduces a way of writing tools for agents in a framework agnostic manner. Currently the different frameworks supported by Agent Kernel allows tool functions to be bound to agents, but these functions must be declared and are invoked in a framework specific manner. Also, access to the context from within the tool functions must work differently based on the framework used for building agents.

## Generic framework for writing tools

Tool functions are written as regular Python synchronous or asynchronous functions. These functions take only the parameters needed by the tool's business logic — they do **not** declare a `ToolContext` parameter.

To access the execution context from within a tool function, the tool calls the static method `ToolContext.get()`, which returns the `ToolContext` instance that was set by the framework runner before the agent was invoked.

```python
from agentkernel.core import ToolContext

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    # Access context if needed
    session = ToolContext.get().session
    runtime = ToolContext.get().runtime
    return f"Weather in {city}: sunny"
```

## `ToolContext` structure

`ToolContext` is a class defined in `src/agentkernel/core/tool.py` with the following properties:

```python
class ToolContext:
    id: str              # Unique identifier (uuid4 hex)
    runtime: Runtime     # The runtime instance under which the agent is executing
    agent: Agent         # The agent instance making the tool call
    session: Session     # The session associated with the current agent invocation
    requests: list[AgentRequest]  # The list of requests being processed
```

Each `ToolContext` instance receives a unique `id` (generated via `uuid.uuid4().hex`) at construction time. Properties are read-only (exposed via `@property` decorators).

### Context variable management

`ToolContext` uses Python's `contextvars.ContextVar` to make the current context available anywhere in the call stack:

- **`set() -> Self`** — Sets this instance as the current context and stores the reset token.
- **`reset()`** — Resets the context variable to its previous value using the stored token.
- **`get() -> Self`** (class method) — Retrieves the current `ToolContext` from the context variable; raises `RuntimeError` if none is set.

### Cache mechanism for ADK

Because Google ADK manages its own context and does not allow direct propagation of `contextvars`, `ToolContext` provides a class-level cache (`_cache: dict[str, Self]`) with context manager support:

- **`__enter__`** — Stores the instance in `_cache` keyed by its `id`.
- **`__exit__`** — Removes the instance from `_cache`.
- **`fetch(id: str) -> Self`** (class method) — Retrieves a cached instance by ID; raises `KeyError` if not found.

### `ToolBuilder` base class

The same file contains `ToolBuilder`, a base class for all framework-specific tool builders, with a single class method `bind(funcs: list[Callable]) -> list[Any]` that raises `NotImplementedError`.

Both `ToolContext` and `ToolBuilder` are exported from `src/agentkernel/core/__init__.py`.

## Framework specific context initialization

Each framework runner creates and manages a `ToolContext` instance during its `run()` method, before the agent is invoked. The approach differs by framework:

### OpenAI, CrewAI, and LangGraph runners

These runners use the `set()`/`reset()` pattern with a `try`/`finally` block:

```python
context = ToolContext(Runtime.current(), agent, session, requests).set()
try:
    # ... invoke the agent ...
finally:
    if context is not None:
        context.reset()
```

Tool functions access the context via `ToolContext.get()` during execution.

### Google ADK runner

ADK uses its own context management, so `contextvars` propagation is not reliable. Instead, the ADK runner uses the cache-based context manager pattern and passes the `ToolContext` ID through the ADK session state:

```python
ctx = AKToolContext(Runtime.current(), agent, session, requests)
with ctx:
    state = {"ak_tool_context": ctx.id}
    await adk_session.create_session(
        app_name=app_name, user_id=user_id,
        session_id=session.id, state=state
    )
    # ... invoke the agent ...
```

The `GoogleADKSession.create_session()` method accepts a `state: dict[str, Any]` parameter to pass through to the ADK session service.

## Tool function binding

Each supported framework implementation includes a `ToolBuilder` subclass that converts generic Python functions into framework-specific tool definitions via a `bind()` class method:

| Framework | Builder class | SDK mechanism | Output type |
|-----------|--------------|---------------|-------------|
| OpenAI Agents SDK | `OpenAIToolBuilder` | `function_tool(func)` | `FunctionTool` |
| Google ADK | `GoogleADKToolBuilder` | `FunctionTool(cls._wrap(func))` | `FunctionTool` |
| CrewAI | `CrewAIToolBuilder` | `crewai_tool(func)` | `BaseTool` |
| LangGraph | `LangGraphToolBuilder` | `StructuredTool.from_function(...)` | `StructuredTool` |

All builders validate that each item in the input list is callable, raising `TypeError` if not.

### OpenAIToolBuilder

Directly passes each function to `function_tool()` from the OpenAI Agents SDK. No wrapper is needed since `ToolContext` is accessed via `ToolContext.get()` within the tool function, and `OpenAIRunner` sets the context variable before invocation.

### GoogleADKToolBuilder

Has a custom `_wrap(func)` class method because ADK tools receive a `tool_context` parameter (of ADK's own `ToolContext` type) from the framework. The wrapper:

1. Augments the original function's signature by adding a `tool_context` keyword-only parameter (default `None`).
2. When invoked, retrieves the `AKToolContext` from the cache using `AKToolContext.fetch(tool_context.state["ak_tool_context"])`.
3. Calls `.set()` on the retrieved context so that `ToolContext.get()` works inside the tool function.
4. Delegates to the original function (excluding the `tool_context` parameter).
5. Calls `.reset()` in a `finally` block.

The wrapper preserves async/sync semantics via `asyncio.iscoroutinefunction` and uses `functools.wraps` plus `inspect.signature` to maintain function metadata.

### CrewAIToolBuilder

Directly passes each function to `crewai_tool()` (the `@tool` decorator from CrewAI's SDK). No wrapper is needed since `ToolContext` is accessed via `ToolContext.get()` and `CrewAIRunner` sets the context variable.

### LangGraphToolBuilder

Uses `StructuredTool.from_function()` from `langchain_core.tools`. Distinguishes between sync and async functions:

- **Async functions:** passed as `coroutine=func`
- **Sync functions:** passed as `func=func`

Both use `func.__doc__ or func.__name__` as the description and `func.__name__` as the tool name.

## Function signature compatibility

Generic tool functions may be asynchronous or synchronous. The tools emitted by the builders preserve these semantics:

- `OpenAIToolBuilder` and `CrewAIToolBuilder` pass functions directly; the underlying SDK handles sync/async.
- `GoogleADKToolBuilder._wrap()` produces a sync wrapper for sync functions and an async wrapper for async functions.
- `LangGraphToolBuilder` passes async functions as `coroutine` and sync functions as `func` to `StructuredTool.from_function()`.

## Tool registration flow

Developers call `.bind()` when defining agents, passing a list of tool functions. The bound tools are passed directly to the framework's agent constructor:

```python
# OpenAI
from agentkernel.openai import OpenAIToolBuilder
from agents import Agent

weather_agent = Agent(
    name="weather",
    instructions="You provide weather information upon request.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

# Google ADK
from agentkernel.adk import GoogleADKToolBuilder
from google.adk.agents import Agent

weather_agent = Agent(
    name="weather",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="You provide weather information upon request",
    instruction="Use the get_weather tool for weather-related questions.",
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

# CrewAI
from agentkernel.crewai import CrewAIToolBuilder
from crewai import Agent

weather_agent = Agent(
    role="weather",
    goal="You provide weather information upon request",
    backstory="Use the get_weather tool for weather-related questions.",
    tools=CrewAIToolBuilder.bind([get_weather]),
)

# LangGraph
from agentkernel.langgraph import LangGraphToolBuilder
from langgraph.prebuilt import create_react_agent

weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),
    model=model,
    prompt="Use the get_weather tool for weather-related questions.",
)
```

## Error handling

- Calling `bind()` on the base `ToolBuilder` raises `NotImplementedError`.
- Passing a non-callable to any framework's `bind()` raises `TypeError`.
- Calling `ToolContext.get()` when no context is set raises `RuntimeError`.
- Calling `ToolContext.fetch(id)` with an unknown ID raises `KeyError`.

## Implementation plan

### Task 1: Define `ToolContext` and `ToolBuilder` base class

**File:** `src/agentkernel/core/tool.py` (new)

1. Create a `ToolContext` class with:
   - Constructor accepting `runtime: Runtime`, `agent: Agent`, `session: Session`, `requests: list[AgentRequest]`.
   - A unique `id` property generated via `uuid.uuid4().hex`.
   - Read-only properties: `id`, `runtime`, `agent`, `session`, `requests`.
   - Class-level `contextvars.ContextVar[Self | None]` named `_context` for get/set/reset pattern.
   - `set() -> Self` — sets this instance in the context variable, stores the reset token.
   - `reset()` — resets the context variable using the stored token.
   - `get() -> Self` (class method) — returns the current instance; raises `RuntimeError` if none is set.
   - Class-level `_cache: dict[str, Self]` for the context manager pattern.
   - `__enter__` — stores `self` in `_cache[self.id]`.
   - `__exit__` — removes `self` from `_cache`.
   - `fetch(id: str) -> Self` (class method) — retrieves from `_cache`; raises `KeyError` if not found.
2. Create a `ToolBuilder` base class with:
   - A class method `bind(funcs: list[Callable]) -> list[Any]` that raises `NotImplementedError`.
3. Export `ToolContext` and `ToolBuilder` from `src/agentkernel/core/__init__.py`.

---

### Task 2: Implement `OpenAIToolBuilder`

**File:** `src/agentkernel/framework/openai/openai.py` (add to existing)

1. Create `OpenAIToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Iterates each function, validates it is callable (raises `TypeError` if not).
   - Wraps each function with `function_tool(func)` from the OpenAI Agents SDK.
   - Returns the list of `FunctionTool` instances.
3. Update `OpenAIRunner.run()` to create and set a `ToolContext` before agent invocation and reset it in a `finally` block.
4. Export `OpenAIToolBuilder` from `src/agentkernel/framework/openai/__init__.py`.

---

### Task 3: Implement `GoogleADKToolBuilder`

**File:** `src/agentkernel/framework/adk/adk.py` (add to existing)

1. Create `GoogleADKToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which wraps each function via `cls._wrap(func)` and passes the result to ADK's `FunctionTool`.
3. Implement `_wrap(cls, func)` class method which:
   - Validates the input is callable.
   - Creates a sync or async wrapper (based on `asyncio.iscoroutinefunction`) that accepts a `tool_context` keyword-only parameter.
   - In the wrapper: fetches the `AKToolContext` from the cache via `tool_context.state["ak_tool_context"]`, calls `.set()`, delegates to the original function, and calls `.reset()` in a `finally` block.
   - Augments the wrapper's `__signature__` to include a `tool_context` keyword-only parameter with default `None`.
   - Uses `functools.wraps` to preserve function metadata.
4. Update `GoogleADKRunner.run()` to:
   - Create an `AKToolContext` and enter it via `with ctx:`.
   - Pass `{"ak_tool_context": ctx.id}` as the `state` parameter to `adk_session.create_session()`.
5. Update `GoogleADKSession.create_session()` to accept a `state: dict[str, Any]` parameter.
6. Export `GoogleADKToolBuilder` from `src/agentkernel/framework/adk/__init__.py`.

---

### Task 4: Implement `CrewAIToolBuilder`

**File:** `src/agentkernel/framework/crewai/crewai.py` (add to existing)

1. Create `CrewAIToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Iterates each function, validates it is callable (raises `TypeError` if not).
   - Wraps each function with `crewai_tool(func)` (the `@tool` decorator from CrewAI).
   - Returns the list of CrewAI `BaseTool` instances.
3. Update `CrewAIRunner.run()` to create and set a `ToolContext` before agent invocation and reset it in a `finally` block.
4. Export `CrewAIToolBuilder` from `src/agentkernel/framework/crewai/__init__.py`.

---

### Task 5: Implement `LangGraphToolBuilder`

**File:** `src/agentkernel/framework/langgraph/langgraph.py` (add to existing)

1. Create `LangGraphToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Iterates each function, validates it is callable (raises `TypeError` if not).
   - For async functions: creates a `StructuredTool.from_function(coroutine=func, name=func.__name__, description=func.__doc__ or func.__name__)`.
   - For sync functions: creates a `StructuredTool.from_function(func=func, name=func.__name__, description=func.__doc__ or func.__name__)`.
   - Returns the list of `StructuredTool` instances.
3. Update `LangGraphRunner.run()` to create and set a `ToolContext` before agent invocation and reset it in a `finally` block.
4. Export `LangGraphToolBuilder` from `src/agentkernel/framework/langgraph/__init__.py`.

---

### Task 6: Unit tests for `ToolContext` and `ToolBuilder` base class

**File:** `tests/test_tool.py` (new, 25 tests)

1. **`ToolContext` properties tests:** verify `id`, `runtime`, `agent`, `session`, and `requests` return the values passed at construction.
2. **`id` uniqueness tests:** verify each `ToolContext` gets a unique `id`.
3. **`set()`/`get()`/`reset()` tests:**
   - Setting a context makes it retrievable via `get()`.
   - `get()` raises `RuntimeError` when no context is set.
   - `reset()` restores the previous state.
   - Two contexts can be set and reset independently.
4. **Context manager (`__enter__`/`__exit__`) tests:**
   - Entering stores the instance in the cache.
   - Exiting removes it from the cache.
   - `fetch(id)` works inside the context manager block.
   - `fetch(id)` raises `KeyError` after exit.
5. **`ToolBuilder.bind()` test:** calling `bind()` on the base class raises `NotImplementedError`.

---

### Task 7: Unit tests for `OpenAIToolBuilder`

**File:** `tests/test_tool_openai.py` (new, 37 tests)

1. **Bind basic:** bind sync/async functions, verify `FunctionTool` instances are returned with correct names and descriptions.
2. **Tool metadata:** verify parameter schemas are correctly extracted.
3. **Function invocation:** verify bound sync and async functions produce correct results.
4. **Mixed binding:** bind a list of sync and async tools together.
5. **Type validation:** verify `TypeError` on non-callable inputs.
6. **Edge cases:** lambdas, duplicate functions, `strict_json_schema` default.

---

### Task 8: Unit tests for `GoogleADKToolBuilder`

**File:** `tests/test_tool_adk.py` (new, 42 tests)

1. **Bind basic:** bind sync/async functions, verify ADK `FunctionTool` instances with correct names.
2. **`_wrap` metadata:** verify wrapped functions preserve name, docstring, and async semantics.
3. **`_wrap` signature augmentation:** verify the `tool_context` keyword-only parameter is added with default `None`, original parameters are preserved.
4. **`_wrap` invocation with context:** verify the wrapper fetches `AKToolContext` from ADK state, calls `set()`/`reset()`, and delegates correctly for both sync and async functions.
5. **Error propagation:** verify context is reset even when the wrapped function raises.
6. **Runner integration:** verify `GoogleADKRunner.run()` creates the `AKToolContext`, passes its ID in session state, makes it fetchable during execution, and cleans up after completion.

---

### Task 9: Unit tests for `CrewAIToolBuilder`

**File:** `tests/test_tool_crewai.py` (new, 24 tests)

1. **Bind basic:** bind sync functions, verify CrewAI `BaseTool` instances with correct names and descriptions.
2. **Tool metadata:** verify `args_schema` contains expected parameter properties.
3. **Tool invocation:** verify `tool.run()` produces correct results for various parameter configurations.
4. **Type validation:** verify `TypeError` on non-callable inputs.
5. **Edge cases:** lambdas, duplicate functions, independent tool instances.

---

### Task 10: Unit tests for `LangGraphToolBuilder`

**File:** `tests/test_tool_langgraph.py` (new, 37 tests)

1. **Bind basic:** bind sync/async functions, verify `StructuredTool` instances with correct names and descriptions.
2. **Tool metadata:** verify `args_schema` and description fallback to function name when no docstring.
3. **Sync invocation:** verify `tool.invoke()` produces correct results.
4. **Async invocation:** verify async tools have `coroutine` set and `tool.ainvoke()` produces correct results.
5. **Sync/async distinction:** verify sync tools have `coroutine=None`, async tools have `coroutine` set.
6. **Mixed binding:** bind sync and async tools together.
7. **Type validation:** verify `TypeError` on non-callable inputs.
8. **Edge cases:** lambdas, duplicate functions, independent instances, `return_direct` default.

---

### Task 11: Update demo examples

**Files:** `examples/cli/openai/demo.py`, `examples/cli/adk/demo.py`, `examples/cli/crewai/demo.py`, `examples/cli/langgraph/demo.py`

For each demo:
1. Add a `get_weather` tool function that returns weather for a given city.
2. Add a `weather_agent` that uses the framework's `ToolBuilder.bind([get_weather])` to register the tool.
3. Add the `weather_agent` to the triage/supervisor agent's sub-agents and to the module registration.
