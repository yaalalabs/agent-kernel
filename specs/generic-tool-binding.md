# Framework agnostic tooling

This feature introduces a way of writing tools for agents in a framework agnostic manner. Currently the different frameworks supported by Agent Kernel allows tool functions to be bound to agents, but these functions must be declared and are invoked in a framework specific manner. Also, access to the context from within the tool functions must work differently based on the framework used for building agents.

## Generic framework for writing tools

It should be possible to write tool functions as Python asynchronous or synchornous functions. These functions would take parameters as needed by the tool function implementation.

Optionally, these functions may take a parameter of a new type `ToolContext` which exposes different attributes of the context in which the tool function in being invoked. For starters, `ToolContext` should have a parameter called `runtime` of type `Runtime` that resolve to the runtime instance under which the tool function invoking agent is being executed, and it should also have a parameter called `session` of type `Session` that resolve to the agent invocation session making the tool function call.

## Framework specific context initialization

In general, the tool context members can be intialized as follows.

- `session` can be initialized to the current session via `Session.current()`
- `runtime` can be initialized to the current runtime via `Runtime.current()`

Depending on the agent framework, it may be required to initialize the context used for tools before the agent is invoked by the framework specific runner. For example, for Google ADK, tool functions may not be able to get the current session via `Session.current()` as ADK uses a different approach to context management. Therefore the `ADKRunner` may have to access the ADK specific context via `get_current_context()` and then set its `state` dictionary to contain the runtime, session, etc.

## Tool function binding

Each supported framework implementation (in `src/agentkernel/framework/*`) should include a class that wrap a given tool function set and emit a framework specific set of tool functions that initialize the tool context for that given agent framework. These classes should have the same naming and implementation pattern and can be named as `OpenAIToolBuilder`, `ADKToolBuilder`, etc. They can have a `bind()` function that takes an array of generic tool functions and return an array of framework specific tool functions.

## `ToolContext` structure

```python
def ToolContext:
    runtime: Runtime
    session: Session
```

When passed on to a tool function, the `ToolContext` should be immutable. It can be defined in `src/agentkernel/core/tool.py`. The same file can have a `ToolBuilder` class that act as a base class for all framework specific tool builders and implement common functionality.

## Context detection mechanism

Binding a `ToolContext` to a tool function and passing it should only happen if the function declares a parameter of type `ToolContext`. It should not depend on the parameter name.

## Function signature compatibility

Genereic tool functions may be asynchronous or synchronous. The functiona emitted by the tool builders should match these semantics.

Generic tool functions are assumed to be of `**kwargs` type.

Type hint usage and validation is not required, except for detecting the presence of a `ToolContext` parameter.

## Tool registration flow

Developers would call `.bind()` when defining the agents. As part of the agent definition, developers would have to pass the list of tool exposed to each agent. Binding would happen at this point.

For example, with OpenAI one would do something similar to the following.

```python
weather_agent = Agent(
    name="WeatherAgent",
    instructions="You provide weather information upon request. Use the get_weather tool for all weather-related questions.",
    tools=OpenAIToolBuilder.bind([get_weather, get_forecast]),
)
```

## Error handling

If a framework does not support a given feature, then invoking it should be either not possible, or it should raise a suitable exception.

If binding fails it should raise a suitable exception.

## Implementation plan

### Task 1: Define `ToolContext` and `ToolBuilder` base class

**File:** `src/agentkernel/core/tool.py` (new)

1. Create a `ToolContext` dataclass (frozen/immutable) with two fields:
   - `runtime: Runtime` — the runtime instance under which the agent is executing.
   - `session: Session` — the session associated with the current agent invocation.
2. Create a `ToolBuilder` abstract base class with:
   - A static/class method `bind(funcs: list[Callable]) -> list[Callable]` that subclasses must implement.
   - A helper method `_needs_tool_context(func: Callable) -> bool` that inspects the function signature (via `inspect.signature` and `typing.get_type_hints`) to detect whether any parameter is annotated with `ToolContext`, regardless of parameter name.
   - A helper method `_build_tool_context() -> ToolContext` that constructs a `ToolContext` using `Runtime.current()` and `Session.current()` as defaults. Framework-specific subclasses may override this.
   - A helper method `_wrap(func: Callable) -> Callable` that wraps a generic tool function so that when invoked, it builds a `ToolContext` (if requested by the signature), injects it as the appropriate kwarg, and delegates to the original function. Must preserve async/sync semantics using `asyncio.iscoroutinefunction`.
3. Export `ToolContext` and `ToolBuilder` from `src/agentkernel/core/__init__.py`.

---

### Task 2: Implement `OpenAIToolBuilder`

**File:** `src/agentkernel/framework/openai/openai.py` (add to existing)

1. Create `OpenAIToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Iterates each generic tool function.
   - Calls `_wrap(func)` to produce a context-injecting wrapper.
   - Wraps the result into an OpenAI-compatible tool definition (using `agents.function_tool` or the appropriate SDK mechanism to convert a plain Python function into an OpenAI tool).
   - Returns the list of framework-specific tools.
3. Context initialization: use the default `_build_tool_context()` (relies on `Session.current()` and `Runtime.current()` set by `OpenAIRunner`).
4. Export `OpenAIToolBuilder` from `src/agentkernel/framework/openai/__init__.py` and from `src/agentkernel/openai.py`.

---

### Task 3: Implement `ADKToolBuilder`

**File:** `src/agentkernel/framework/adk/adk.py` (add to existing)

1. Create `ADKToolBuilder(ToolBuilder)` class.
2. Override `_build_tool_context()` to handle ADK's custom context management:
   - Attempt to retrieve the session and runtime from the ADK context state (via `google.adk.agents.get_current_context()` and its `state` dict) as the primary source.
   - Fall back to `Session.current()` / `Runtime.current()` if the ADK context is unavailable.
3. Implement `bind(funcs)` which:
   - Wraps each function with context injection via `_wrap(func)`.
   - Converts the wrapped function into an ADK-compatible `FunctionTool`.
   - Returns the list of ADK tools.
4. Update `GoogleADKRunner.run()` to store `runtime` and `session` in the ADK context state dict so that `_build_tool_context` can retrieve them.
5. Export `ADKToolBuilder` from `src/agentkernel/framework/adk/__init__.py` and from `src/agentkernel/adk.py`.

---

### Task 4: Implement `CrewAIToolBuilder`

**File:** `src/agentkernel/framework/crewai/crewai.py` (add to existing)

1. Create `CrewAIToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Wraps each function with context injection via `_wrap(func)`.
   - Converts the wrapped function into a CrewAI-compatible tool (e.g., wrapping with `crewai.tools.tool` or the equivalent SDK mechanism).
   - Returns the list of CrewAI tools.
3. Context initialization: use the default `_build_tool_context()`.
4. Export `CrewAIToolBuilder` from `src/agentkernel/framework/crewai/__init__.py` and from `src/agentkernel/crewai.py`.

---

### Task 5: Implement `LangGraphToolBuilder`

**File:** `src/agentkernel/framework/langgraph/langgraph.py` (add to existing)

1. Create `LangGraphToolBuilder(ToolBuilder)` class.
2. Implement `bind(funcs)` which:
   - Wraps each function with context injection via `_wrap(func)`.
   - Converts the wrapped function into a LangGraph-compatible tool (e.g., using `langchain_core.tools.tool` decorator or `StructuredTool.from_function`).
   - Returns the list of LangGraph tools.
3. Context initialization: use the default `_build_tool_context()`.
4. Export `LangGraphToolBuilder` from `src/agentkernel/framework/langgraph/__init__.py` and from `src/agentkernel/langgraph.py`.

---

### Task 6: Unit tests for `ToolContext` and `ToolBuilder` base class

**File:** `tests/test_tool.py` (new)

1. **`ToolContext` immutability test:** verify that a `ToolContext` instance cannot be mutated after creation.
2. **`_needs_tool_context` detection tests:**
   - A function with no `ToolContext` parameter → returns `False`.
   - A sync function with a `ToolContext` parameter (any name) → returns `True`.
   - An async function with a `ToolContext` parameter → returns `True`.
   - A function with multiple params including `ToolContext` → returns `True` and the non-context params are unaffected.
3. **`_wrap` sync function tests:**
   - Wrapping a sync function without `ToolContext` passes through kwargs unchanged.
   - Wrapping a sync function with `ToolContext` injects the context as the correct kwarg.
4. **`_wrap` async function tests:**
   - Wrapping an async function without `ToolContext` returns an async function and passes through kwargs.
   - Wrapping an async function with `ToolContext` returns an async function and injects the context.
5. **Error handling test:** calling `bind()` on the base `ToolBuilder` raises `NotImplementedError` or an appropriate exception.

---

### Task 7: Unit tests for `OpenAIToolBuilder`

**File:** `tests/test_tool_openai.py` (new)

1. **Bind sync tool:** bind a sync generic tool function and verify the result is a valid OpenAI tool definition that, when invoked, calls the original function with correct arguments.
2. **Bind async tool:** bind an async generic tool function and verify async semantics are preserved.
3. **Bind with `ToolContext`:** bind a tool that declares `ToolContext` and verify the context is injected on invocation (mock `Session.current()` and `Runtime.current()`).
4. **Bind without `ToolContext`:** bind a tool without `ToolContext` and verify it is called without any context injection.
5. **Bind multiple tools:** bind a list of multiple tools and verify all are correctly converted.
6. **Bind failure:** verify that binding an invalid object (e.g., a non-callable) raises an appropriate exception.

---

### Task 8: Unit tests for `ADKToolBuilder`

**File:** `tests/test_tool_adk.py` (new)

1. **Bind sync tool:** bind a sync function and verify it produces a valid ADK `FunctionTool`.
2. **Bind async tool:** bind an async function and verify async semantics.
3. **Bind with `ToolContext` via ADK context state:** mock the ADK context with runtime/session in its state dict, bind a tool with `ToolContext`, invoke it, and verify the injected context has the correct runtime and session.
4. **Bind with `ToolContext` fallback:** when ADK context is unavailable, verify fallback to `Session.current()` / `Runtime.current()`.
5. **Bind without `ToolContext`:** verify no context injection occurs.
6. **Bind multiple tools:** verify a list of tools is correctly bound.

---

### Task 9: Unit tests for `CrewAIToolBuilder`

**File:** `tests/test_tool_crewai.py` (new)

1. **Bind sync tool:** bind a sync function and verify it produces a valid CrewAI tool.
2. **Bind async tool:** bind an async function and verify async semantics.
3. **Bind with `ToolContext`:** bind a tool with `ToolContext`, invoke it, and verify context injection.
4. **Bind without `ToolContext`:** verify no context injection.
5. **Bind multiple tools:** verify correct handling of multiple tools.
6. **Bind failure:** verify exception on invalid input.

---

### Task 10: Unit tests for `LangGraphToolBuilder`

**File:** `tests/test_tool_langgraph.py` (new)

1. **Bind sync tool:** bind a sync function and verify it produces a valid LangGraph/LangChain tool.
2. **Bind async tool:** bind an async function and verify async semantics.
3. **Bind with `ToolContext`:** bind a tool with `ToolContext`, invoke it, and verify context injection.
4. **Bind without `ToolContext`:** verify no context injection.
5. **Bind multiple tools:** verify correct handling of multiple tools.
6. **Bind failure:** verify exception on invalid input.
