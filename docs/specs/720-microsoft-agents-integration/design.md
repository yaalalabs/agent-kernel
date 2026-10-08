# #720: Microsoft Agent Framework Integration

Recommends integrating Microsoft Agent Framework (MAF) as a seventh AK framework adapter (`framework/maf/`), mirroring the `Agent`/`Runner`/`Module`/`ToolBuilder` pattern used by openai/crewai/langgraph/adk/smolagents/pydanticai. MAF provides a robust, production-ready backend that unifies AutoGen and Semantic Kernel, bringing strong native multi-modal arrays and structured outputs to AK.

## Motivation

- Microsoft Agent Framework 1.0 (GA) consolidates AutoGen and Semantic Kernel into a single unified platform.
- Adds MAF as a seventh supported agent SDK alongside the existing six adapters.
- Like Pydantic AI and OpenAI, MAF supports native streaming (via async iterators) and strongly-typed objects for memory management and payload formatting.

## Requirements

The existing Pydantic AI and OpenAI adapters (`framework/pydanticai/pydanticai.py`, `framework/openai/openai.py`) are the structural templates throughout, per `.agents/skills/ak-dev-new-framework-integration`.

### Package layout and naming

- New adapter at `ak-py/src/agentkernel/framework/maf/` (`__init__.py` + `maf.py`); public alias `ak-py/src/agentkernel/maf.py`.
- Classes: `MAFSession`, `MAFRunner(Runner)`, `MAFAgent(Agent)`, `MAFModule(Module)`, `MAFToolBuilder(ToolBuilder)`.
- `FRAMEWORK = "maf"` constant, used as the session data key (mirrors `FRAMEWORK = "openai"`).

### Session and message history

- `MAFSession` holds the running session state.
- Retrieval must mirror `OpenAIRunner._session()`: `session.get(FRAMEWORK) or session.set(FRAMEWORK, MAFSession())`.
- Serialization must account for MAF's strict native object typing:
  - Agent Kernel session stores JSON dictionaries natively.
  - Microsoft SDK strictly requires its own `AgentSession` class.
  - Requirement: The runner must construct an `AgentSession.from_dict()` before execution, and extract the state back out into a dictionary via `kwargs["session"].to_dict()` afterwards to persist across serverless boundaries.

### Framework context

- Inject a deep copy of the AK framework context into the native session state under `ak_context` before each run; tools reach it via `FunctionInvocationContext.session.state["ak_context"]`.
- After a successful run only, pop `ak_context` from the native state and merge it back via `_store_framework_context()`; the MAF snapshot must not keep a second copy.
- Declared fidelity: full round-trip, including tool-added keys.

### `MAFRunner.run()`

- Must build and `set()` a `ToolContext(Runtime.current(), agent, session, requests)` in a `try`/`finally` block.
- Must convert every `AgentRequest` variant to MAF's native multi-modal shape (`agent_framework.Content.from_data()` or `Content.from_uri()`).
- Must send text and attachments as one user `Message`, so they reach the model as a single turn; a request list with no usable content returns a "no valid content" text reply without calling MAF.
- Must extract the text result from MAF's complex `Result` object via `getattr(result, "text", str(result))`.
- Must route structured output through `AgentReplyAny.from_output()` before falling back to `AgentReplyText`.

### `MAFRunner.stream()`

- Must implement `supports_streaming = True`.
- Must implement real token streaming natively yielding AK's `StreamEvent` objects (`MessageStart`, `TextDelta`, `ReasoningDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult`, `MessageEnd`).
- Must correlate tool events by MAF's own `call_id`, never a generated id; argument chunks that arrive without an id (Chat Completions-style clients) are tied to their call through `tool_call_index`.

### Tool binding

- `MAFToolBuilder.bind(funcs)` must wrap each plain function as a native MAF tool using MAF's `@tool` decorator (`from agent_framework import tool as maf_tool`).
- Must extract function properties gracefully falling back to standard python `__name__` and `__doc__`.

### `MAFAgent` wrapper

- Must implement all four abstract methods on `Agent`:
  - `get_description()` — via the native `description`, falling back to `default_options["instructions"]`.
  - `override_system_prompt()` — required to append system prompts.
  - `attach_tool()` — required for tools to register via `MAFToolBuilder.bind()`.
  - `get_a2a_card()` — via `A2ACardBuilder.build(...)`.

### `MAFModule`

- Must mirror `OpenAIModule`: constructor accepts native agent instances, resolves `self.runner` via override or `Trace.get().maf()`, else falls back to plain `MAFRunner()`.

### Tracing

- Must add `maf()` tracing provider implementation to `BaseTrace`.
- Must add `trace/langfuse/maf.py`, `trace/openllmetry/maf.py`, and `trace/logfire/maf.py` following the established instrumentation pattern.
- MAF emits OpenTelemetry spans by default (`ENABLE_INSTRUMENTATION`), so the traced runners add the outer AK span only and must not force-enable MAF instrumentation over a user's opt-out.

### Packaging (`ak-py/pyproject.toml`)

- Must add a `maf` optional-dependency group depending on `agent-framework-core` only (not the `agent-framework` meta-package, which installs every MAF integration): the adapter imports MAF core only. The application installs its model provider package (e.g. `agent-framework-openai`), mirroring the `pydanticai` extra.
