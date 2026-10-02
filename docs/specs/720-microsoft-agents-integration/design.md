# #720: Microsoft Agent Framework Integration

Recommends integrating Microsoft Agent Framework (MAF) as a seventh AK framework adapter (`framework/maf/`), mirroring the `Agent`/`Runner`/`Module`/`ToolBuilder` pattern used by openai/crewai/langgraph/adk/smolagents/pydanticai. MAF provides a robust, production-ready backend that unifies AutoGen and Semantic Kernel, bringing strong native multi-modal arrays and structured outputs to AK.

## Motivation

- Microsoft Agent Framework 1.0 (GA) consolidates AutoGen and Semantic Kernel into a single unified platform.
- Integrating MAF makes Agent Kernel the first multi-framework orchestrator to support all seven major agent SDKs.
- Like Pydantic AI and OpenAI, MAF supports native streaming (via async iterators) and strongly-typed objects for memory management and payload formatting.
- See the full supporting landscape survey at [`research/maf-framework-survey.md`](file:///home/pulindu/yaala/agent-kernel/docs/specs/720-microsoft-agents-integration/research/maf-framework-survey.md).

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

### `MAFRunner.run()`

- Must build and `set()` a `ToolContext(Runtime.current(), agent, session, requests)` in a `try`/`finally` block.
- Must convert every `AgentRequest` variant to MAF's native multi-modal shape (`agent_framework.Content.from_data()` or `Content.from_uri()`).
- Must supply a fallback to a raw string payload (`payload = inputs if inputs else prompt`) to prevent crashes on empty content arrays.
- Must extract the text result from MAF's complex `Result` object via `getattr(result, "text", str(result))`.
- Must route structured output through `AgentReplyAny.from_output()` before falling back to `AgentReplyText`.

### `MAFRunner.stream()`

- Must implement `supports_streaming = True`.
- Must implement real token streaming natively yielding AK's `StreamEvent` objects (`MessageStart`, `TextDelta`, `ReasoningDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult`, `MessageEnd`).

### Tool binding

- `MAFToolBuilder.bind(funcs)` must wrap each plain function as a native MAF tool using MAF's `@tool` decorator (`from agent_framework import tool as maf_tool`).
- Must extract function properties gracefully falling back to standard python `__name__` and `__doc__`.

### `MAFAgent` wrapper

- Must implement all four abstract methods on `Agent`:
  - `get_description()` — via `agent.system_message` or `agent.instructions`.
  - `override_system_prompt()` — required to append system prompts.
  - `attach_tool()` — required for tools to register via `MAFToolBuilder.bind()`.
  - `get_a2a_card()` — via `A2ACardBuilder.build(...)`.

### `MAFModule`

- Must mirror `OpenAIModule`: constructor accepts native agent instances, resolves `self.runner` via override or `Trace.get().maf()`, else falls back to plain `MAFRunner()`.

### Tracing

- Must add `maf()` tracing provider implementation to `BaseTrace`.
- Must add `trace/langfuse/maf.py` and `trace/openllmetry/maf.py` following the established instrumentation pattern.

### Packaging (`ak-py/pyproject.toml`)

- Must add a `maf` optional-dependency group depending on `agent-framework>=1.0.0`.
