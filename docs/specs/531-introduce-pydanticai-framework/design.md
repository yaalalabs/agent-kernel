# #531: Evaluate and Integrate Pydantic AI as an Agentic Platform

Recommends integrating Pydantic AI as a sixth AK framework adapter (`framework/pydanticai/`),
mirroring the `Agent`/`Runner`/`Module`/`ToolBuilder` pattern used by openai/crewai/langgraph/adk/
smolagents. Pydantic AI's addition over every existing adapter is genuine multi-provider model
support and schema-validated, self-correcting structured output; its gaps (no session persistence,
no handoff primitive) are already covered by AK's own core or its existing tool-delegation pattern.

## Motivation

- AK's core design principle is a framework-agnostic core (`.agents/skills/ak-dev-architecture`);
  five adapters exist (`ak-py/src/agentkernel/framework/{openai,crewai,langgraph,adk,smolagents}/`),
  but each inherits its host framework's own model story:
  - OpenAI Agents SDK: OpenAI models first-class; other providers via LiteLLM/custom
    `ModelProvider`, with documented degradations off-OpenAI (tracing needs a separate OpenAI key,
    most providers fall back from the Responses API to Chat Completions, hosted tools don't work).
  - CrewAI / LangGraph / Google ADK / Smolagents: each anchored to its own ecosystem's model
    routing, with similar first/second-class splits.
  - None gives AK a model layer where switching, or failing over between, providers is a
    zero-degradation operation.
- `AgentReplyAny.from_output()` (`ak-py/src/agentkernel/core/model.py:148-163`) already accepts a
  `pydantic.BaseModel` and calls `model_dump(mode="json")` — written for the existing adapters'
  `output_type` results, but exactly the shape Pydantic AI's `agent.run().output` returns natively
  when `output_type` is a Pydantic model.
  - No core change is needed for structured output to flow through; only the adapter needs to
    write it.
- Pydantic AI is maintained by the Pydantic team, whose validation library AK's own `AKConfig`
  (`ak-py/src/agentkernel/core/config.py`) is built on — closer ecosystem overlap than the other
  four frameworks.
- Comparison against the framework AK's adapters and examples default to today (see table below).

| Dimension | OpenAI Agents SDK (`framework/openai/`) | Pydantic AI (proposed) |
|---|---|---|
| Version (2026-07-20) | v0.18.3, pre-1.0 after ~16 months | v2.13.0; stable v2.0 since 2026-06-23 |
| Maintainer / stars | OpenAI, ~28k | Pydantic team, ~18.7k |
| Model support | OpenAI first-class; others via LiteLLM, documented degradations | OpenAI/Anthropic/Google/Bedrock/Groq/Mistral/Cohere/xAI/Ollama all native; `FallbackModel` for failover |
| Structured output | `output_type`, strict JSON schema; malformed output raises | `output_type` + validators; malformed output triggers model self-correction via `ModelRetry` |
| Multi-agent | `handoffs=[...]` built-in primitive | Delegation via tool calls / plain code / `pydantic-graph`; no handoff primitive |
| Sessions | Built-in (`SQLiteSession`, `RedisSession`, ...) | None — stateless by default |
| Guardrails | `@input_guardrail`/`@output_guardrail`, first/last agent only | Output validators + `ModelRetry`; richer guardrails live in the separate, 0.x `pydantic-ai-harness` |
| Unique extras | Hosted web/file search, code interpreter, realtime voice, zero-config trace dashboard | Typed DI + fake models for tests, `UsageLimits`, `pydantic-evals`, OTel-native tracing, 4 durable-execution integrations |

Sources: pydantic.dev/docs/ai, openai.github.io/openai-agents-python, both projects' GitHub
release pages — retrieved 2026-07-20.

**Recommendation: integrate as a sixth adapter.** Its two weaknesses vs. the OpenAI SDK (no
  persistence, no handoffs) are already AK's job (session store, `Runtime`'s registry) or covered
  by AK's existing tool-delegation pattern; its two strengths (provider freedom, self-correcting
  structured output) are gaps in every adapter AK has today.

## Requirements

The existing OpenAI adapter (`framework/openai/openai.py`, 371 lines) is the structural template
throughout, per `.agents/skills/ak-dev-new-framework-integration`.

### Package layout and naming

- New adapter at `ak-py/src/agentkernel/framework/pydanticai/` (`__init__.py` + `pydanticai.py`);
  public alias `ak-py/src/agentkernel/pydanticai.py`.
- Classes: `PydanticAISession`, `PydanticAIRunner(Runner)`, `PydanticAIAgent(Agent)`,
  `PydanticAIModule(Module)`, `PydanticAIToolBuilder(ToolBuilder)`.
- `FRAMEWORK = "pydanticai"` constant, used as the session data key (mirrors `FRAMEWORK = "openai"`,
  `openai.py:28`; matches `Session.get`/`Session.set`, `core/base.py:124-168`).
- Naming follows AK's own shorthand rather than the upstream package name, matching existing
  precedent (`openai` for `agents`/`openai-agents`, `adk` for `google-adk`): settled as
  `pydanticai` — used consistently throughout this document for the directory, class prefixes,
  `FRAMEWORK` constant, and pyproject extra — not `pydantic_ai`, the upstream import name.

### Model and provider selection

- Model/provider choice — including configuring `FallbackModel` for automatic failover — is
  entirely the user's responsibility via the native `pydantic_ai.Agent(model=...)` constructor.
  AK adds no `AKConfig` surface for model or provider selection.
  - Matches every existing adapter: users build the native agent object with whatever model
    configuration they want (e.g. `Agent(name="math", instructions=...)` for the OpenAI SDK), and
    AK only wraps the resulting object — it never re-abstracts over model choice.
  - This is the mechanism behind the "zero-degradation provider switching" motivation: Pydantic
    AI's own model classes and `FallbackModel` make switching providers a one-line change in the
    user's own agent construction — AK doesn't mediate or add a second configuration surface for
    it.

### Session and message history

- `PydanticAISession` holds the running message history as its only state.
  - Simpler than `OpenAISession` (`openai.py:31-72`, an async `get_items`/`add_items`/`pop_item`/
    `clear_session` protocol) because Pydantic AI has no session protocol — history is a plain
    `list[ModelMessage]` passed as `message_history=` and read back via `result.all_messages()`.
- Retrieval must mirror `OpenAIRunner._session()` (`openai.py:86-95`):
  `session.get(FRAMEWORK) or session.set(FRAMEWORK, PydanticAISession())`.
- Serialization must account for a version-skew risk unique to this adapter:
  - AK's Redis/DynamoDB/Cosmos/Firestore session stores pickle the whole `Session` object via
    `BinarySerde` (`core/session/serde.py:6-38`).
  - Pydantic AI's own docs designate `ModelMessagesTypeAdapter`/`to_jsonable_python()` (JSON), not
    raw pickling of its message classes, as the supported history interchange format.
  - Pydantic AI's release cadence is fast (v2.6.0 → v2.13.0 in ten days in the sample this
    evaluation observed; the project's own version policy caps the no-breaking-change window at
    three months between majors), so a pickled session risks more version-skew than the OpenAI
    adapter's plain-dict `_items` ever did.
  - Requirement, confirmed: `PydanticAISession` stores the jsonable form
    (`to_jsonable_python(messages)`), not the raw object list, and reconstructs via
    `ModelMessagesTypeAdapter.validate_python()` before each run.

### `PydanticAIRunner.run()`

- Must follow the same lifecycle as `OpenAIRunner.run()` (`openai.py:166-195`): build and `set()` a
  `ToolContext(Runtime.current(), agent, session, requests)` in `try`/`finally`
  (`core/tool.py:22-142`).
- Must convert every `AgentRequest` variant to Pydantic AI's native input (mirrors
  `_process_requests()`, `openai.py:97-150`): `AgentRequestText` → prompt string;
  `AgentRequestImage`/`AgentRequestFile` → Pydantic AI's multi-modal content parts.
- Must update the session's message history from `result.all_messages()` after every run (the
  explicit-mutation equivalent of the OpenAI SDK's self-mutating `Session` object).
- Must route a `BaseModel`-typed `result.output` through `AgentReplyAny.from_output()` before
  falling back to `AgentReplyText` (mirrors the two-step fallback at `openai.py:185-190`, modulo
  the `text`→`response` rename from #500).
- Must preserve the existing catch-all error contract: any exception becomes
  `AgentReplyText(response=user_facing_error_message(e), prompt=prompt)` (`openai.py:191-192`).

### `PydanticAIRunner.stream()`

- Must implement real token streaming, not a `NotImplementedError` stub — Pydantic AI has native
  token streaming, unlike the frameworks that had to stub this method.
- Must yield plain text deltas from Pydantic AI's streaming result and update session history from
  the final result once the stream is exhausted.
- Must note one caveat for spec.md: Pydantic AI's streaming run treats the first `output_type`
  match as final and stops the run — no impact on AK's plain-text streaming contract
  (`core/base.py:235`), but a caller combining `output_type` with AK's streaming mode sees
  different truncation semantics than the non-streaming path.

### Tool binding — no framework-native dependency injection

- `PydanticAIToolBuilder.bind(funcs)` must wrap each plain function as a native Pydantic AI tool
  (mirrors `function_tool(func)` at `openai.py:357-371`).
- Must **not** adopt Pydantic AI's `deps_type`/`RunContext` dependency-injection pattern — a design
  decision, not left open:
  - Every existing adapter's tools reach execution context only via `ToolContext.get()`
    (`core/tool.py:89-100`), a contextvar, precisely so one tool function is portable across every
    adapter via `ToolBuilder.bind()`.
  - Threading `deps_type` through would make Pydantic-AI-bound tools incompatible with tools bound
    to any other adapter.
  - Users wanting native `RunContext` ergonomics remain free to construct native
    `Agent(tools=[...])` objects outside AK's involvement, as with any other adapter today.

### `PydanticAIAgent` wrapper

- Must implement all four abstract methods on `Agent` (`core/base.py:302-334`), not only the two
  the integration-skill's example code shows:
  - `get_description()` — the native agent's instructions (mirrors `openai.py:249-253`); exact
    attribute path to confirm in spec.md.
  - `override_system_prompt()` — required for the multimodal prompt suffix
    (`Agent._setup_system_prompt()`, `core/base.py:336-344`) to reach the agent at all (mirrors
    `openai.py:255-262`).
  - `attach_tool()` — required for the multimodal `AnalyzeAttachmentsTool`
    (`Agent._attach_system_tools()`, `core/base.py:346-353`) to register (mirrors
    `openai.py:264-276`).
  - `get_a2a_card()` — via `A2ACardBuilder.build(...)` (mirrors `openai.py:278-287`); exact
    tool-enumeration API to confirm in spec.md.
- Missing `override_system_prompt`/`attach_tool` means multimodal support silently degrades rather
  than erroring — needs a spec.md test case.

### `PydanticAIModule`

- Must mirror `OpenAIModule` (`openai.py:290-346`): constructor accepts native agent instances,
  resolves `self.runner` from an override, `Trace.get().pydanticai()` when tracing is enabled, else
  a plain `PydanticAIRunner()`; `_wrap()`/`pre_hook()`/`post_hook()` match the existing three-line
  bodies.

### Tracing

- Must add `pydanticai() -> Runner` through the existing per-framework trace factory pattern —
  mechanical, matching the existing five frameworks. Because the method is `@abstractmethod` on
  `BaseTrace`, it must be implemented in every concrete `BaseTrace` subclass (`Trace`, `LangFuse`,
  `OpenLLMetry`), not only `BaseTrace` itself; spec.md enumerates the exact files.
- Must add `trace/langfuse/pydanticai.py` and `trace/openllmetry/pydanticai.py`, following the
  established pattern (`trace/langfuse/openai.py:12-41`): instrument once in `__init__`, wrap
  `run()` in AK's span for session_id/tags/input-output — the instrumentation step itself is
  shaped differently from the OpenAI runner's single `OpenAIAgentsInstrumentor().instrument()`
  call, confirmed against `openinference-instrumentation-pydantic-ai` (Arize-ai, PyPI, v0.1.17,
  last released 2026-06-30 — matching the `crewai`/`adk` convention of bundling a companion
  OpenInference package):
  - Register `OpenInferenceSpanProcessor()` on the active OpenTelemetry `TracerProvider` — a span
    processor, not an `.instrument()`-style instrumentor object.
  - Enable Pydantic AI's own native instrumentation via the `Agent.instrument_all()` static method
    (a global, process-wide toggle, called once — matches the OpenAI runner's pattern of not
    requiring the user to change how they construct their own native agent), not the per-instance
    `agent.instrument = InstrumentationSettings(...)` property (there is no `instrument=`
    constructor keyword), since AK never constructs the user's native `Agent` object (see "Model
    and provider selection").

### Packaging (`ak-py/pyproject.toml`)

- Must add a `pydanticai` optional-dependency group:
  - `pydantic-ai-slim~=2.13.0` (patch-only within 2.13.x, i.e. `>=2.13.0,<2.14.0`, matching the
    LangGraph group's tightness) — confirmed, given Pydantic AI's fast release cadence; the
    ceiling moves forward deliberately as later versions are vetted, not automatically.
  - **`pydantic-ai-slim`, not the full `pydantic-ai` meta-package** (correction from the isolated-venv
    research this design was first written against): the repo resolves *all* extras into one shared
    `ak-py/uv.lock`, so every extra must co-resolve with every other. The full `pydantic-ai==2.13.0`
    always pulls `pydantic-ai-slim[…,mcp,…]` → `fastmcp-slim` → `py-key-value-aio>=0.4.4`, which is
    unsatisfiable alongside AK's existing `mcp` extra (`fastmcp>=2.14.2,<3.0.0` → `py-key-value-aio<0.4.0`).
    `pydantic-ai-slim` is the genuinely provider-agnostic core (no bundled providers, no `fastmcp`),
    so the lock resolves cleanly — and it fits this design's "model/provider choice is entirely the
    user's responsibility" principle better than the full package, which bundles a fixed provider set.
    Consequence: `agentkernel[pydanticai]` installs no model provider; the user adds their own
    (`pydantic-ai-slim[openai]`, `[anthropic]`, …), documented in the framework page and example.
  - `openinference-instrumentation-pydantic-ai>=0.1.17` — confirmed to exist (Arize-ai, PyPI, last
    released 2026-06-30), mirroring the `crewai`/`adk` groups' inclusion of their own
    instrumentation packages (see Tracing).
- `requires-python = ">=3.12,<3.14"` (`pyproject.toml:10`) already exceeds Pydantic AI's own
  `>=3.10` floor — no compatibility gate needed.

### Tests

- Must add `ak-py/tests/test_pydanticai_runner.py` and `test_tool_pydanticai.py`, matching the
  naming and `DummyRunner`/`DummyAgent`/`monkeypatch`/`@pytest.mark.asyncio` conventions of
  `test_openai_runner.py`/`test_tool_openai.py`.
- Must add one test beyond the standard adapter suite: a `BinarySerde` pickle round-trip of a
  `PydanticAISession` holding a non-trivial message history, asserting the messages survive intact
  — the serialization risk above has no analog in the other adapters (their session state is plain
  dicts/strings).

### Examples and docs

- Must add `examples/cli/pydanticai/demo.py`, mirroring `examples/cli/openai/demo.py`'s
  triage/math/weather shape, adapted to delegation-via-tool in place of `handoffs=[...]`.
- Must add `docs/docs/frameworks/pydantic-ai.md` + a `docs/sidebars.js` entry, following the
  `openai.md` template, and add Pydantic AI to the framework enumerations in
  `docs/docs/frameworks/overview.md` and the `ak-py/README.md` framework/session-key lists; spec.md
  enumerates the exact surfaces.

## Non-goals

- Replicating `handoffs=[...]` as a new AK-core primitive — multi-agent Pydantic AI setups use the
  framework's own delegation-via-tool-call pattern, which needs no `Module`/`Runtime` changes.
- Integrating `pydantic-ai-harness` (memory, guardrails, sandboxed execution, sub-agent
  delegation) — 0.x, explicitly unstable per its own README; revisit at 1.0. AK's guardrail/
  multimodal/thread subsystems already cover the overlapping ground.
- Wiring Temporal/DBOS/Prefect/Restate durable execution into AK core — these wrap the
  *invocation* of an agent (a workflow calls in, not the reverse), a materially different shape
  than `PydanticAIRunner.run()`; a distinct future ticket if ever needed.
- `pydantic-evals` wiring into AK's own test/observability tooling — orthogonal; no existing
  adapter has an evals surface to extend either.
- The AG-UI protocol integration — AK already has REST/WebSocket/MCP/A2A frontends; a second
  framework-specific UI protocol is redundant with "frontends depend on core, never the reverse."
- Touching any existing adapter, example, or doc page — purely additive.
