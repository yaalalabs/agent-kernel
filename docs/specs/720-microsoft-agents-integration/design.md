# #720: Microsoft Agent Framework Integration

Recommends integrating Microsoft Agent Framework (MAF) as a seventh AK framework adapter (`framework/maf/`), mirroring the `Agent`/`Runner`/`Module`/`ToolBuilder` pattern used by openai/crewai/langgraph/adk/smolagents/pydanticai. MAF unifies AutoGen and Semantic Kernel, and brings native streaming, typed structured output and tool approval to AK.

This document was written alongside the implementation in the same PR rather than reviewed ahead of it; it records the design the adapter follows, so the next adapter PR can be checked against it.

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

- `MAFSession` holds the serialized native session under the `FRAMEWORK` key, retrieved get-or-create (as `OpenAIRunner._session()` does).
- MAF requires its own `AgentSession` object, while the AK session store persists plain picklable data: the runner restores the native session from its serialized form before each run and stores it back in serialized form after a successful run, so history survives process and serverless boundaries.
- The native session snapshot is persisted **before** the framework context: a context that cannot be stored (an unpicklable value) must not lose a turn the model completed — on a resume, a tool call that already ran.

### Framework context

- Inject a deep copy of the AK framework context into the native session state under `ak_context` before each run; tools reach it via `FunctionInvocationContext.session.state["ak_context"]`.
- After a successful run only, take `ak_context` out of the native state and merge it back via `_store_framework_context()`; the MAF snapshot must not keep a second copy.
- Declared fidelity: full round-trip, including tool-added keys.

### `MAFRunner.run()`

- Must build and `set()` a `ToolContext(Runtime.current(), agent, session, requests)` in a `try`/`finally` block.
- Must convert every `AgentRequest` variant to MAF's native multi-modal shape (`agent_framework.Content.from_data()` or `Content.from_uri()`).
- Must send text and attachments as one user `Message`, so they reach the model as a single turn; a request list with no usable content returns a "no valid content" text reply without calling MAF.
- Must route structured output through `AgentReplyAny.from_output()`, and otherwise return the response text as an `AgentReplyText`.

### `MAFRunner.stream()`

- Must implement `supports_streaming = True`.
- Must implement real token streaming natively yielding AK's `StreamEvent` objects (`MessageStart`, `TextDelta`, `ReasoningDelta`, `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult`, `MessageEnd`).
- Must correlate tool events by MAF's own call id, never a generated one, including streamed argument chunks that arrive without an id (Chat Completions-style clients).
- Must release the provider stream when a streamed turn is interrupted (an error or a client disconnect); session write-back happens only after the stream drains normally.

### Human in the loop

- `supports_pause = True`: a tool declared with `approval_mode="always_require"` (natively, or via `MAFToolBuilder.bind(..., approval_mode=...)`) pauses the run.
- Pause detection reads the final response's `function_approval_request` items, before the reply mapping, identically in `run()` and `stream()`; `stream()` ends with `RunPaused`.
- The record (`PausedRunState.add`, after `clear_for_runner` — one conversation per session) carries the serialized `AgentSession` and the pending requests, so a resume needs nothing else and works on any replica.
- `resume()` / `resume_stream()` send one user message of approval responses: `approved` approves; `denied` and `cancelled` reject. They share the reply/stream helpers with `run()` / `stream()`, and clear the record once the native call succeeded and the conversation holding its outcome is stored — before the framework context, whose write-back can fail on its own — so a failed native call stays retryable and an approved tool can never run twice.
- Refused above the `try`, naming the cause: a partial resume, a decision payload, a prompt beside the decisions, and a new prompt while a pause is outstanding (MAF would drop the pending calls).

### Native run options

- `MAFAgent.RESERVED_RUN_OPTIONS`: `messages`, `stream` and `session` — the runner sets each itself; declaring one raises `ValueError` at declaration.
- `run()`, `stream()`, `resume()` and `resume_stream()` each resolve the options once with `await agent.resolve_run_options(session, requests)`, after the early returns, and build the native call with `_native_kwargs(options, session=...)`, so the AK-owned keys are written last.
- Model settings nest inside MAF's own `options` mapping (`temperature`, `max_tokens`, `response_format`); `function_invocation_kwargs` reaches every tool call. `Agent.run` takes no `**kwargs`, so an unknown key raises `TypeError` on the first run.
- Progress hooks are MAF middleware on the agent, not run options; `examples/cli/maf-run-options` demonstrates both.

### Tool binding

- `MAFToolBuilder.bind(funcs, **options)` must wrap each plain function as a native MAF tool with MAF's `tool()`, which takes the tool's name and description from the function's `__name__` and `__doc__`.
- Keyword options are forwarded to `tool()` unchanged (e.g. `approval_mode="always_require"`).

### `MAFAgent` wrapper

- Must implement all four abstract methods on `Agent`:
  - `get_description()` — via the native `description`, falling back to `default_options["instructions"]`.
  - `override_system_prompt()` — required to append system prompts.
  - `attach_tool()` — required for tools to register via `MAFToolBuilder.bind()`.
  - `get_a2a_card()` — via `A2ACardBuilder.build(...)`.

### `MAFModule`

- Must mirror `OpenAIModule`: constructor accepts native agent instances, resolves `self.runner` via override or `Trace.get().maf()`, else falls back to plain `MAFRunner()`.

### Tracing

- Must add `maf()` to `BaseTrace` as an `@abstractmethod`, like the six existing framework methods (the precedent `pydanticai()` set in #539), and the matching `Trace.maf()`. A custom tracer must implement it.
- Must add traced runners for all four built-in backends: `trace/langfuse/maf.py`, `trace/openllmetry/maf.py`, `trace/logfire/maf.py` and `trace/cloudwatch/maf.py` (registered in `CloudWatch.maf()`).
- MAF emits OpenTelemetry spans by default (`ENABLE_INSTRUMENTATION`), so the traced runners add the outer AK span only and must not force-enable MAF instrumentation over a user's opt-out. Span content is metadata-only unless the user sets MAF's `ENABLE_SENSITIVE_DATA`.

### Packaging (`ak-py/pyproject.toml`)

- Must add a `maf` optional-dependency group depending on `agent-framework-core` only (not the `agent-framework` meta-package, which installs every MAF integration): the adapter imports MAF core only. The application installs its model provider package (e.g. `agent-framework-openai`), mirroring the `pydanticai` extra.

### Configuration

- No new configuration. The adapter reuses the existing `AKConfig` sections every adapter reads (`trace`, `session`, `execution`) and adds no fields, flags or type selectors.
- Model and provider settings stay on the MAF chat client the application constructs; per-agent run settings go through `Module.run_options`.

### Examples

- `examples/cli/maf` (CLI with a bound tool), `examples/cli/maf_context` (framework context through `FunctionInvocationContext`), `examples/cli/maf-run-options` (`options` and `function_invocation_kwargs`), `examples/api/maf` (REST) and `examples/api/maf-streaming` (SSE token streaming).
- All five run in the e2e matrix (`.github/test-config.yaml`).

### Documentation and skills

- Framework page `docs/docs/frameworks/microsoft-agents.md`, with the sections the other framework pages carry, and the sidebar entry.
- Every framework inventory: landing marquee tile, architecture chip, feature explorer, features page (SDK count), intro What's New, FrameworkSelector, FAQ, persona pages, and the streaming, AG-UI, tracing, session-handle and Human in the Loop lists.
- Bundled user skills (`ak-build`, `ak-init`, `ak-test`, `ak-add-capabilities`) and developer skills, with eval cases.

### Testing

- Unit tests in `ak-py/tests/test_maf_runner.py` and `test_tool_maf.py`: request mapping, session round-trip, framework context, structured output, streaming event mapping (including chunked tool-call ids and a client disconnect), the run-options checklist of the framework-integration skill, and Human in the loop on a real MAF `Agent` driven by a fake chat client (pause, approve/deny, refusals, retry after a failed resume, the replica round trip through pickle, and dispatch through `Runtime`).
- Trace runner tests alongside the existing tracing tests.

## Non-goals

- Free-text human questions (`input_required`): MAF agents have no native equivalent; only tool approvals pause.
- Hosted-service requests MAF can return, such as an OAuth consent request from a hosted MCP tool: not surfaced as a pause.
- MAF workflows (`Workflow` / `workflow.as_agent()`): not wrapped or validated by this adapter; supporting them needs a design for workflow pauses (`request_info`) and checkpoint storage.
- Background continuation tokens: not exposed; AK's queue-based asynchronous execution is separate.
- Tracing `resume()`: no traced runner wraps it for any framework today; tracked separately for all adapters that pause.

## Open questions

- A MAF pause blocks every MAF agent that shares the session, because pause records are scoped by runner (`maf`), not by agent — the same as Pydantic AI. For MAF this is also protective: all MAF agents in one session share a single native session snapshot, which holds the pending calls. Should records, and the native snapshot, be scoped per agent instead?
- Two MAF agents in one session share the snapshot's `service_session_id`, so agents whose clients keep the conversation on the provider's side continue one thread id. Is a per-agent native session needed, or is "use separate sessions" (as documented) enough?
