# Research: Pydantic Logfire as a tracing provider

Supporting material for `design.md`. Backs the decision to model Logfire on the existing
Langfuse/OpenLLMetry providers and to reuse the framework extras' OpenInference instrumentors.

## What Logfire is

- Pydantic's observability platform, "an opinionated wrapper around OpenTelemetry" with full support
  for OTel traces, metrics, and logs. pip package: `logfire` (latest 4.x, `requires-python >=3.10`).
  [PyPI](https://pypi.org/project/logfire/), [GitHub](https://github.com/pydantic/logfire) — verified
  2026-07-23.
- `logfire.configure()` installs the global OpenTelemetry tracer provider and the Logfire OTLP
  exporter. Consequence: any OTel/OpenInference instrumentor active in the process emits spans into
  Logfire, with no per-instrumentor exporter wiring. This is the same model Langfuse 4.x uses — which
  is why AK's Langfuse runners can rely on the OpenInference instrumentors emitting to "the" provider.

## API surface used

- `logfire.configure(service_name=..., send_to_logfire=..., token=..., environment=..., console=...)`.
  Write token env var is `LOGFIRE_TOKEN`. `send_to_logfire` accepts `bool | "if-token-present"`;
  `"if-token-present"` ships only when a token is set, else runs locally without error. Verified from
  the configuration docs (redirects to `pydantic.dev/docs/logfire/manage/configuration/`), 2026-07-23.
- `logfire.span(msg_template, **attributes)` → a `LogfireSpan` context manager (wraps an OTel span);
  extra kwargs attach as span attributes, `span.set_attribute(key, value)` sets more. Direct analog of
  Langfuse's `client.start_as_current_observation(name=..., as_type="span")` + `span.update(...)`.
  Verified from the spans docs / API reference, 2026-07-23.
- `logfire.instrument_openai_agents()` — native instrumentation for the OpenAI Agents SDK; patches the
  SDK so each logical step (agent run, LLM call, tool call) becomes an OTel span. Confirmed present in
  Logfire 3.x+ (release notes / integration docs), 2026-07-23.

## Coverage decision per framework

Logfire has no native `instrument_crewai` / `instrument_adk` / `instrument_smolagents`. Rather than add
new dependencies to a `logfire` extra, reuse what the framework extras already ship (these emit to
whatever global OTel provider is active — under Logfire, that's Logfire):

| Framework | Instrumentor | Already in extra | Notes |
|---|---|---|---|
| OpenAI | `logfire.instrument_openai_agents()` | `logfire` | native, idiomatic |
| CrewAI | `CrewAIInstrumentor` + `LiteLLMInstrumentor` (OpenInference) | `crewai` | same as Langfuse (`trace/langfuse/crewai.py:5-6`) |
| Google ADK | `GoogleADKInstrumentor` (OpenInference) | `adk` | same as Langfuse (`trace/langfuse/adk.py:5`) |
| LangGraph | none (session span only) | — | Langfuse depth needs its own `CallbackHandler`; no OpenInference langchain instrumentor in the `langgraph` extra |
| Smolagents | none (session span only) | — | matches Langfuse (`trace/langfuse/smolagents.py` activates none) |

Deep LangGraph tracing under Logfire (e.g. adding `openinference-instrumentation-langchain`) is a
possible follow-up; left out to keep the `logfire` extra minimal and the change focused.

## Prior art in-repo

- Langfuse provider: `trace/langfuse/` — client + `propagate_attributes` + `start_as_current_observation`
  + OpenInference instrumentors.
- OpenLLMetry provider: `trace/openllmetry/` — global once-guarded `Traceloop.init()`
  (`openllmetry.py:43-55`) + no-arg runners wrapping `super().run()`.
- Logfire borrows the once-guarded global init from OpenLLMetry and the span-with-io-attributes
  wrapping from Langfuse.
