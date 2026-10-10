# Trace Formats per Tracing Provider in AK

What the raw OpenTelemetry spans actually look like for each AK tracing provider, and what that means
for storing traces and normalising them into one AK trace model.
Companion to [provider-read-apis.md](provider-read-apis.md). Written while the direction was still "export spans to an AK-owned store" (§6); the per-span conventions it documents apply unchanged to spans fetched back from the providers.

**How this was researched (2026-10-07):**
- Read every AK traced runner in `ak-py/src/agentkernel/trace/{langfuse,logfire,openllmetry}/*.py` to see
  which instrumentation each provider × framework combination switches on.
- **Captured real spans offline** for 2 frameworks × 3 providers. Setup: a fake OpenAI-compatible LLM
  server (one tool call, then a final answer), the exact instrumentation and wrapper span from each AK
  runner, and an in-memory OTel exporter. No API keys, nothing sent to any cloud.
  - The capture scripts and raw span dumps were kept in a local scratch directory and are not committed.
- SDK versions (`ak-py/.venv`): langfuse 4.15.1, logfire 4.41.0, traceloop-sdk 0.62.3, pydantic-ai 2.13.0,
  openinference-instrumentation-openai-agents 2.1.2.
- Not captured (frameworks not installed in the venv): LangGraph, CrewAI, ADK, Smolagents. Their rows
  below come from reading the AK runner code only.

---

## 1. Key insight: the format depends on the instrumentation library, not the provider

"Provider" (Langfuse / Logfire / Traceloop) is where the traces get **sent**. The span **format** comes
from **which instrumentation library creates the spans**, and AK's runners mix several:

```
                    ┌──────────────── what creates the spans ────────────────┐
 AK runner  ──────▶ │ OpenInference (Arize)    → llm.*, input.value, ...     │
                    │ Logfire native           → logfire.*, input/output      │
                    │ Traceloop native         → gen_ai.* (new OTel GenAI)    │
                    │ Pydantic AI native       → gen_ai.* (new OTel GenAI)    │
                    │ Langfuse SDK / callback  → langfuse.observation.*       │
                    └────────────────────────────────────────────────────────┘
                                      │
                    provider's exporter (only decides where spans go)
```

There are effectively **5 attribute conventions**. The same provider can produce different formats
for different frameworks.

## 2. Which convention each AK runner produces (from AK runner code)

| Framework | Langfuse runner | Logfire runner | Traceloop runner |
|---|---|---|---|
| **OpenAI Agents** | OpenInference (`OpenAIAgentsInstrumentor`) ✅ captured | Logfire native (`logfire.instrument_openai_agents()`) ✅ captured | Traceloop native (auto-instrumented by `Traceloop.init`) ✅ captured |
| **Pydantic AI** | Pydantic AI native gen_ai **+** OpenInference attrs added by `OpenInferenceSpanProcessor` ✅ captured | Pydantic AI native gen_ai (`logfire.instrument_pydantic_ai()`) ✅ captured | Pydantic AI native gen_ai (`Agent.instrument_all()`) **+** Traceloop `openai.chat` spans ✅ captured |
| **LangGraph** | Langfuse native (`langfuse.langchain.CallbackHandler`) | ⚠️ **only AK's wrapper span**: no LLM/tool spans | Traceloop native (auto-instrumented, assumed) |
| **CrewAI** | OpenInference (`CrewAIInstrumentor` + `LiteLLMInstrumentor`) | OpenInference (same instrumentors) | Traceloop native (auto, assumed) |
| **Google ADK** | OpenInference (`GoogleADKInstrumentor`) | OpenInference (same) | Traceloop native (auto, assumed) |
| **Smolagents** | ⚠️ **only AK's wrapper span** | ⚠️ **only AK's wrapper span** | Traceloop auto: unknown which spans |

"Assumed" = `Traceloop.init()` auto-instruments whatever supported libraries are installed; not captured.

**Gap found:** Logfire + LangGraph, and Langfuse/Logfire + Smolagents, record **only the outer AK span**
(input/output text). There are no LLM-call or tool-call spans, so trace-level evals work but
agent/LLM/tool-level evals don't.

---

## 3. Captured: same agent run, three different span trees (OpenAI Agents SDK)

Run: `weather-agent`, prompt "What's the weather in Colombo?", one `get_weather` tool call, then a
final answer. All three produced **one trace** with the full content.

```
LANGFUSE (OpenInference)                 LOGFIRE (native)                          TRACELOOP (gen_ai)
────────────────────────                 ────────────────                          ──────────────────
Agent Kernel OpenAI   [langfuse-sdk]     Agent Kernel OpenAI        [logfire]      (no AK wrapper span!)
└ Agent workflow                         └ OpenAI Agents trace: {name}             Agent Workflow
  └ Agent workflow   (duplicated)          └ Task: Agent workflow                  └ weather-agent.agent
    └ weather-agent        AGENT             └ Agent run: {name!r}                   ├ openai.response
      ├ turn                                   ├ Turn {turn} for agent ...           │ └ openai.chat     LLM
      │ ├ generation       LLM                 │ └ Chat completion with ...  LLM     ├ get_weather.tool  TOOL
      │ └ get_weather      TOOL                └ Turn {turn} for agent ...           └ openai.response
      └ turn                                     ├ Function: {name}          TOOL      └ openai.chat     LLM
        └ generation       LLM                   └ Chat completion with ...  LLM
```

Differences in **structure**:
- Depth and grouping differ: Langfuse/Logfire have "turn" spans, Traceloop doesn't; Traceloop nests the
  LLM call under `openai.response`.
- Logfire span **names are templates** (`Agent run: {name!r}`). The real values are in `logfire.msg` and
  in attributes.
- **Traceloop has no AK wrapper span.** `TraceloopContext` only sets association properties, so there's
  no root span holding the trace's input/output. It has to be derived from the LLM spans.

### How the same facts are stored (OpenAI Agents SDK, captured)

| Fact | Langfuse (OpenInference) | Logfire (native) | Traceloop (gen_ai) |
|---|---|---|---|
| **Span type** | `openinference.span.kind` = `AGENT` / `LLM` / `TOOL` | none: infer from name/`logfire.msg_template`; LLM has `logfire.tags=["LLM"]` | `traceloop.span.kind` = `workflow`/`agent`/`tool`; LLM via `gen_ai.operation.name=chat` |
| **Trace input / output** | AK wrapper: `langfuse.observation.input` / `.output` | AK wrapper: `input` / `output` | ❌ no wrapper; derive from first/last LLM span |
| **LLM input messages** | **flattened**: `llm.input_messages.0.message.role`, `...content`, `...tool_calls.0.tool_call.function.name`; also `input.value` (JSON) | `input` (JSON array) and `request_data` (JSON) | `gen_ai.input.messages` (JSON, **"parts" format**: `{"role","parts":[{"type","content"}]}`) |
| **LLM output** | `llm.output_messages.0.message.content`; `output.value` (JSON) | `output` (JSON array) | `gen_ai.output.messages` (JSON, parts format) |
| **Model** | `llm.model_name` | `gen_ai.request.model`, `gen_ai.response.model` | `gen_ai.request.model`, `gen_ai.response.model` |
| **Tokens** | `llm.token_count.prompt` / `.completion` | `gen_ai.usage.input_tokens` / `output_tokens`; `usage` (JSON) | `gen_ai.usage.input_tokens` / `output_tokens` / `total_tokens` |
| **Tool name** | `tool.name` | `name` | `gen_ai.tool.name` |
| **Tool args / result** | `input.value` / `output.value` | `input` / `output` | `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result` |
| **Agent name** | `agent.name` (+ `graph.node.id`) | `name` on "Agent run" span | `gen_ai.agent.name` |
| **Session id** | `session.id` on **every** span (via `propagate_attributes`) | `session_id` on wrapper only, and ⚠️ **scrubbed** (see §5) | `traceloop.association.properties.session_id` on every span |
| **Tool definitions** | `tool.description`, `tool.parameters` on tool span | `tools` (names) on agent span | `gen_ai.tool.definitions` (JSON) on LLM span |

---

## 4. Captured: Pydantic AI (framework-native instrumentation)

Pydantic AI emits its **own** OTel GenAI-convention spans (`chat gpt-4o-mini`, `execute_tool get_weather`,
`invoke_agent weather-agent`) whichever provider is used. So the formats converge here:

- All three: `gen_ai.input.messages` / `gen_ai.output.messages` (parts JSON), `gen_ai.tool.call.arguments`
  / `.result`, `gen_ai.usage.*`, `gen_ai.agent.name`, `gen_ai.conversation.id`, `pydantic_ai.all_messages`
  and `final_result` on the agent span.
- **Langfuse** additionally gets OpenInference attributes (`openinference.span.kind`, `input.value`,
  `output.value`, `tool.name`…) **on the same spans**, added by `OpenInferenceSpanProcessor`. These were
  present whether our capture processor was registered before or after it.
- **Traceloop** gets **duplicate LLM spans.** For each LLM call there's Pydantic AI's `chat gpt-4o-mini`
  **and** a child `openai.chat` from Traceloop's auto-instrumentation of the OpenAI client. A naive
  normaliser would count every LLM call twice (tokens, cost, LLM-level evaluator runs).

---

## 5. Gotchas found (each affects the store/normaliser design)

1. **Logfire scrubs AK's session id.** AK does `logfire.span("Agent Kernel …", session_id=session.id)`.
   Logfire's default scrubber matches the word "session" and replaces the value with
   `"[Scrubbed due to 'session']"`. Our extra processor receives the **already-scrubbed** span, so the
   session id is lost for **both** Logfire's cloud and our store. Child spans don't carry a session id at
   all. This is **an existing AK bug** for Logfire users too. Fix options: rename the attribute, or pass
   a `logfire.ScrubbingOptions(callback=...)` that allows it.
2. **Traceloop: no root span with input/output** (OpenAI Agents path). The trace's input/output must be
   reconstructed from LLM spans, or AK's Traceloop runners should add a wrapper span like the others.
3. **Traceloop + Pydantic AI: duplicate LLM spans.** Must dedupe (e.g. drop `openai.chat` when its
   parent is a gen_ai `chat` span).
4. **Missing inner spans** for Logfire+LangGraph and Langfuse/Logfire+Smolagents (only the wrapper span).
5. **Langfuse OpenAI Agents: duplicated "Agent workflow" span** (two nested). Harmless, but the
   normaliser should collapse it.
6. **Attribute values are often JSON strings** (`input.value`, `gen_ai.input.messages`, Logfire's
   `input`/`output`). OTel attributes can only be primitives or arrays, so structured data gets
   stringified. The store must keep them and the normaliser must `json.loads` them.
7. **Two message formats for gen_ai:** the new OTel GenAI "parts" format
   (`{"role":"user","parts":[{"type":"text","content":...}]}`) vs OpenAI-style
   `{"role","content","tool_calls"}` (Logfire, OpenInference `input.value`).
8. **Langfuse's default export filter** only exports Langfuse/gen_ai/known-LLM-instrumentor spans. Our
   own processor sees all spans regardless (captured), so this only matters for what Langfuse Cloud gets.
9. **Langfuse media handling:** with media in spans, Langfuse's exporter uploads base64 media to Langfuse
   (`LangfuseTransformingSpanExporter`), which is a network path to watch in store-only mode.

---

## 6. What this means for storing traces

**Storing is easy and format-independent. Normalising is where the per-format work goes.**

```
 any provider/framework
        │  raw OTel spans
        ▼
 ┌──────────────────────────┐    Store RAW spans as-is (generic OTel shape):
 │ AK span processor        │    trace_id, span_id, parent_id, name, scope,
 │ (one implementation)     │    start/end, status, attributes (JSON), events,
 └────────────┬─────────────┘    resource, + ak_provider, ak_framework tags
              ▼
 ┌──────────────────────────┐
 │ TraceStore (raw spans)   │  ← never lossy; re-normalise later if mappers improve
 └────────────┬─────────────┘
              ▼  on read / at eval time
 ┌──────────────────────────────────────────────────┐
 │ Normaliser: detect convention PER SPAN, map it   │
 │  • openinference.span.kind present → OpenInference│
 │  • gen_ai.operation.name present    → GenAI       │
 │  • langfuse.observation.type        → Langfuse    │
 │  • scope == "logfire.openai_agents" → Logfire     │
 │  + dedupe, rebuild root input/output, session id  │
 └────────────┬─────────────────────────────────────┘
              ▼
   AK Trace model → Trace / AgentRun / LLMCall / ToolCall → evaluators
```

Recommendations:
- **Store raw spans, normalise later.** The span envelope (ids, parent, times, attributes) is identical
  across all providers, so one storage implementation works for all of them. Keep the raw attributes
  so the normaliser can be fixed or extended without losing data.
- **Detect the convention per span, not per provider.** One trace can mix conventions (Langfuse +
  Pydantic AI has gen_ai and OpenInference on the same span; Traceloop + Pydantic AI mixes Pydantic AI
  and Traceloop spans). Map by instrumentation scope / marker attribute.
- **Prefer the OTel GenAI convention (`gen_ai.*`) as AK's internal target.** It's the emerging
  standard; Traceloop and Pydantic AI already emit it, and Logfire partly does. That leaves roughly
  4 mappers: GenAI (near pass-through), OpenInference, Logfire-native, Langfuse-native.
- **Tag each stored trace with AK's own metadata** (provider, framework, agent name, session id) from
  the AK runner itself. This avoids relying on each provider's session attribute and sidesteps the
  Logfire scrubbing problem.
- **Fix AK-side gaps first:** add a wrapper span to the Traceloop runners, fix Logfire session
  scrubbing, and add instrumentation for Logfire+LangGraph and Smolagents.

## 7. Still to verify
- [ ] Capture LangGraph, CrewAI, ADK, Smolagents (install the extras into a throwaway venv and reuse
      the capture scripts).
- [ ] Streaming runs (`run_streamed`): do the spans or attributes differ?
- [ ] Multi-agent handoffs: how each convention represents agent → agent delegation.
- [ ] Multimodal inputs (images/files): how each convention stores them (and Langfuse media upload).
- [ ] Errors: how a failing tool/LLM call appears (status, events, exception attributes).
