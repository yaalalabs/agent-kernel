# Framework usage capture survey

> **Note 2026-11-17:** in-process capture is superseded; the gateway-first `../design.md` reads usage from the gateway, not from adapters. This survey stays as a record of what each framework reports natively.

Where each adapter gets its native result and what token usage it currently discards. Checked against
the `ak-py/uv.lock` versions: openai-agents 0.20.0, langchain-core 1.6.1 / langgraph 1.2.20,
google-adk 2.8.0 / google-genai 2.34.0, pydantic-ai-slim 2.13.0, smolagents 1.26.0,
agent-framework-core 1.24.0, crewai 1.15.18, claude-agent-sdk 0.2.179, openai-guardrails 0.3.6,
litellm 1.95.1.

- The first survey ran on `ak-py/.venv`, which was behind the lock for langgraph (1.2.11), google-genai
  (2.21.0), agent-framework-core (1.20.0) and litellm (1.89.7), and had no CrewAI or Claude Agent SDK.
- On 2026-11-17 those, plus CrewAI, Claude and openai-guardrails, were re-checked at the locked versions
  in throwaway environments (`uv run --no-project --with <pkg>==<version>`).
- Every check is introspection of types and source. No agent was run and no model was called, so what a
  provider actually fills in at run time is still for the capture PR's tests.

No adapter reads usage today. Paths relative to `ak-py/src/agentkernel/framework/`.

| Adapter | run() | stream() | Native usage | Granularity | Stream path |
|---|---|---|---|---|---|
| openai | `openai/openai.py:250` `Runner.run` | `:521` `run_streamed` | `result.context_wrapper.usage` (`Usage`: requests, input_tokens, input_tokens_details.cached_tokens, output_tokens, output_tokens_details.reasoning_tokens, total_tokens, request_usage_entries) | run total + per call | yes, after `stream_events()` drains |
| langgraph | `langgraph/langgraph.py:623` `ainvoke` | `:838` `astream_events` | `AIMessage.usage_metadata` per message (input/output/total, input_token_details.cache_read/cache_creation, output_token_details.reasoning); model in `response_metadata` (provider-dependent key) | per call only | yes, `on_chat_model_end` (`:965`) — the event's `output` is the message (see Risks) |
| adk | `adk/adk.py:488` `run_async` | `:767` | `Event.usage_metadata` (prompt/candidates/cached_content/thoughts/total_token_count), model `event.model_version` | per LLM event | yes; sum only `partial != True` events |
| pydanticai | `pydanticai/pydanticai.py:202` | `:497` | `result.usage` **property** → `RunUsage` (requests, tool_calls, input/output, cache_read/cache_write, details); per call `ModelResponse.usage` + `model_name` | run total + per call | yes, from `agent_run_result` event |
| crewai | `crewai/crewai.py:384` `kickoff_async` | NotImplementedError | `CrewOutput.token_usage` (`UsageMetrics`: total_tokens, prompt_tokens, cached_prompt_tokens, cache_creation_tokens, completion_tokens, reasoning_tokens, successful_requests); **no model field** | run total | n/a |
| smolagents | `smolagents/smolagents.py:170` | NotImplementedError | `monitor.get_total_token_counts()` or `memory.steps[i].token_usage`; model `agent.model.model_id` | per step | n/a |
| maf | `maf/maf.py:240` | `:405` | `AgentResponse.usage_details` (input/output/total, cache_creation/cache_read, reasoning); **no model field** | run total | yes, `get_final_response()` |
| claude | `claude/claude.py:676` | `:811` | `ResultMessage.model_usage` (`dict[str, ModelUsage]` keyed by model: inputTokens, outputTokens, cacheReadInputTokens, cacheCreationInputTokens, **costUSD**), plus run-level `usage` (dict) and **`total_cost_usd`**; all three optional | per-model run total | yes, ResultMessage arrives in stream |

## Risks

- **smolagents counts are cumulative**: `reset=False` means the monitor grows across runs and sessions on a shared agent object — per-run usage needs a before/after delta.
- **Model per call is not universal**: MAF, smolagents, CrewAI expose only an agent-level model (or none). A handoff run can mix models, so usage should be per-model entries, not one run total.
- **Claude reports its own cost** — a native cost vs the configured pricing source needs a precedence rule.
- Realtime runners (`openai.py:700`, ADK `run_live`): AK pre/post hooks do not run on the native realtime path.
  - OpenAI (openai-agents 0.20.0): `RealtimeSession` adds each `usage` model event to the cumulative `Usage` on its context wrapper (`agents/realtime/session.py:596-598`); every session event exposes that same wrapper as `info.context` (`session.py:214`, `agents/realtime/events.py:15-16`). Cumulative, so a turn's usage is a delta.
  - ADK (google-adk 2.8.0): the live connection converts live `UsageMetadata` (`response_token_count`) into the standard `usage_metadata` (`google/adk/models/gemini_llm_connection.py:290-312`) and yields it on an `LlmResponse` with `model_version` (`:343-349`); `Event` is an `LlmResponse` subclass (`google/adk/events/event.py:91`).
- **langgraph stream path**: in langchain-core 1.6.1 the `on_chat_model_end` event's `output` is the chat message (`langchain_core/tracers/event_stream.py:505-513`), whose `usage_metadata` has input_tokens, output_tokens, total_tokens, input_token_details (cache_read, cache_creation) and output_token_details (reasoning).

## Agent Kernel's own LLM calls (unmetered)

- `core/multimodal/hooks.py:73,94` (litellm, description), `core/multimodal/tools.py:78` (analyze_attachments)
- `integration/thread/naming.py:120` (thread naming)
- `guardrail/openai.py:103,185` (OpenAI guardrails)
  - openai-guardrails 0.3.6: `GuardrailsResponse.guardrail_results.total_token_usage` aggregates the checks' usage as prompt_tokens, completion_tokens, total_tokens (also `guardrails.total_guardrail_token_usage(response)`); no model and no cache or reasoning breakdown. `GuardrailsResponse.__getattr__` delegates to the wrapped OpenAI response, so the completion's own usage is `response.usage`.
- Evaluators (`test/core/evaluator/deepeval.py:39`, `jev.py:82` — JEV already records usage at `:96-97`)

## Existing pieces

- `trace/fetch.py:108-130` `SpanUsage` (input/output/total tokens, cost USD) — read side, one model call per span.
- `core/model.py` reply types (`:111`, `:128`, `:216`) carry no usage field.
- `docs/specs/754-native-run-options/design.md:320` puts #525 (usage) out of scope.

## Gateway attribution seam (per-run headers)

Native per-run ways to attach attribution to model calls, reachable through the #758 `run_options` factory:

- openai-agents: `ModelSettings.extra_headers` / `metadata` / `extra_body` (`agents/model_settings.py:140,174,178`) via `run_config`
- pydantic_ai: `ModelSettings.extra_headers` / `extra_body` (`pydantic_ai/settings.py:279,332`)
- adk: `RunConfig.http_options` (`google/adk/agents/run_config.py:86`); LiteLlm `extra_headers` (`models/lite_llm.py:3149`)
- langgraph, maf, crewai, smolagents, claude: not verified — typically fixed at model construction.
