# Native per-run options across the six framework adapters

Survey of what each supported framework accepts at run time, what the Agent Kernel adapter already
passes (and therefore owns), and where each framework's lifecycle/progress hooks live. This backs the
routing and reserved-key decisions in `../design.md`.

Verification status: signatures were read from the SDKs installed in `ak-py/.venv` on 2026-09-24
unless marked otherwise. Adapter line numbers are against `develop` at `348b8f6b`.

| SDK | Version inspected | How |
|---|---|---|
| openai-agents | 0.20.0 | `inspect.signature(Runner.run)`, `dataclasses.fields(RunConfig)`, `dir(RunHooks)` |
| langgraph | 1.2.11 | `inspect.signature(Pregel.ainvoke / astream_events)`, `RunnableConfig.__annotations__` |
| google-adk | 2.8.0 | `inspect.signature(Runner.__init__ / run_async)`, `RunConfig.model_fields` |
| pydantic-ai-slim | 2.13.0 | `inspect.signature(Agent.run / run_stream_events)` |
| smolagents | 1.26.0 | `inspect.signature(MultiStepAgent.run / __init__)` |
| crewai | not installed in this venv (`crewai>=1.15.0` extra) | **not verified**: Crew fields taken from the adapter's own `Crew(...)` call and the CrewAI docs |

## OpenAI Agents SDK

- Adapter call sites: `ak-py/src/agentkernel/framework/openai/openai.py:213` (`Runner.run`) and `:259`
  (`Runner.run_streamed`). Both pass exactly `agent.agent`, `input_data`, `session=`, `context=`.
- Native run signature (0.20.0):
  `Runner.run(starting_agent, input, *, context=None, max_turns=10, hooks=None, run_config=None,
  error_handlers=None, previous_response_id=None, auto_previous_response_id=False,
  conversation_id=None, session=None)`. `run_streamed` takes the same names (`error_handlers`
  keyword-only there).
- `RunConfig` fields: `model`, `model_provider`, `model_settings`, `handoff_input_filter`,
  `nest_handoff_history`, `handoff_history_mapper`, `input_guardrails`, `output_guardrails`,
  `tracing_disabled`, `tracing`, `trace_include_sensitive_data`, `workflow_name`, `trace_id`,
  `group_id`, `trace_metadata`, `session_input_callback`, `call_model_input_filter`,
  `tool_error_formatter`, `session_settings`, `reasoning_item_id_policy`, `sandbox`,
  `tool_execution`, `tool_not_found_behavior`, `tool_name_collision_policy`.
- Lifecycle hooks: `RunHooks` with `on_agent_start`, `on_agent_end`, `on_handoff`, `on_llm_start`,
  `on_llm_end`, `on_tool_start`, `on_tool_end`. Passed as `hooks=` on the run call. Callbacks are
  awaited inline by the run loop; `run_streamed` drives the loop from tasks it creates
  (`asyncio.create_task`, 4 sites in `agents/run.py`), which inherit a copy of the caller's
  contextvars.
- The user's two asks map directly: `run_config=RunConfig(call_model_input_filter=...)`,
  `max_turns=N`, `hooks=MyRunHooks()`.
- AK-owned (already passed): `starting_agent`, `input`, `session`, `context` (the framework-context
  seam, #526).

## LangGraph

- Adapter call sites: `framework/langgraph/langgraph.py:414` (`ainvoke(input=..., config=config)`)
  and `:469-472` (`astream_events(input=..., config=config, version="v2")`). `config` is built at
  `:368` as `{"configurable": {"thread_id": session.id}}` and nothing else.
- Native signatures (1.2.11):
  `Pregel.ainvoke(input, config=None, *, context=None, stream_mode="values", print_mode=(),
  output_keys=None, interrupt_before=None, interrupt_after=None, durability=None, control=None,
  version="v1", **kwargs)`;
  `Pregel.astream_events(input, config=None, *, version="v2", interrupt_before=None,
  interrupt_after=None, control=None, transformers=None, **kwargs)`.
- `RunnableConfig` keys: `tags`, `metadata`, `callbacks`, `run_name`, `max_concurrency`,
  `recursion_limit`, `configurable`, `run_id`.
- Lifecycle hooks: `config["callbacks"]` (LangChain `BaseCallbackHandler` instances). The
  "turn pressure" equivalent is `recursion_limit`, also inside `config`.
- Consequence: the user's object and AK's object are the same `config` dict, so this adapter needs a
  deep merge of `config` rather than a top-level override.
- Result-shape dependencies: the adapter reads `result.get("structured_response")` at `:424` and
  `result["messages"][-1]` at `:427`, so `output_keys`, `stream_mode` and `print_mode` would break the
  reply mapping if a caller changed them.

## Google ADK

- Adapter call sites: the ADK `Runner` is constructed **per run** at `framework/adk/adk.py:201`
  (`Runner(agent=..., app_name=..., session_service=...)`); `run_async(user_id=, session_id=,
  new_message=)` at `:220` (run) and `:299-303` (stream, adding `run_config=RunConfig(
  streaming_mode=StreamingMode.SSE)` built at `:292`).
- Native signatures (2.8.0):
  `Runner.__init__(*, app=None, app_name=None, agent=None, node=None, plugins=None,
  artifact_service=None, session_service, memory_service=None, credential_service=None,
  plugin_close_timeout=5.0, auto_create_session=False)`;
  `Runner.run_async(*, user_id, session_id, invocation_id=None, new_message=None,
  state_delta=None, run_config=None, yield_user_message=False)`.
- `RunConfig` fields of interest: `max_llm_calls` (the turn-pressure equivalent), `streaming_mode`
  (`NONE` / `SSE` / `BIDI`), `context_window_compression`, `custom_metadata`, `telemetry`.
- Lifecycle hooks: `plugins` (`BasePlugin`: before/after run, model, tool callbacks) on the
  **Runner constructor**, not the run call. Because AK builds that Runner itself, a caller has no
  way to attach plugins today. Per-agent callbacks (`before_model_callback` etc.) live on the
  user-built `LlmAgent` and are already reachable.
- Consequence: options for this adapter have two destinations (constructor vs `run_async`), and the
  stream path must keep `streaming_mode=SSE` whatever a caller's `RunConfig` says.
- AK-owned: `agent`, `app_name`, `session_service`, `user_id`, `session_id`, `new_message`;
  `state_delta` overlaps the framework-context seeding at `:196-199`.

## Pydantic AI

- Adapter call sites: `framework/pydanticai/pydanticai.py:171`
  (`agent.agent.run(content, message_history=history, deps=produced)`) and `:223`
  (`agent.agent.run_stream_events(content, message_history=history, deps=produced)`).
- Native signatures (2.13.0): `Agent.run(user_prompt=None, *, output_type=None,
  message_history=None, deferred_tool_results=None, conversation_id=None, model=None,
  instructions=None, deps=None, model_settings=None, usage_limits=None, usage=None,
  metadata=None, retries=None, infer_name=True, toolsets=None, event_stream_handler=None,
  capabilities=None, spec=None)`. `run_stream_events` accepts the same set **except**
  `event_stream_handler` (it is itself the event stream).
- Turn-pressure equivalent: `usage_limits=UsageLimits(request_limit=..., tool_calls_limit=...)`.
- Lifecycle hooks: `event_stream_handler` on `run`. In AK stream mode the adapter already consumes
  the same events and maps them to `StreamEvent`s.
- AK-owned: `user_prompt` (positional), `message_history`, `deps`.

## CrewAI (not verified against an installed SDK)

- Adapter call sites: the `Crew` is constructed **per run** at `framework/crewai/crewai.py:375-380`
  with `agents=`, `tasks=[task]`, `verbose=False`, `memory=memory`, then `kickoff_async(inputs={})`
  at `:386`. The `Task` is also built per run (`:368-374`) with the module-level
  `output_pydantic` / `output_json` maps (`:548-549`).
- Crew-level options per the CrewAI docs: `step_callback`, `task_callback`, `max_rpm`, `planning`,
  `process`, `manager_llm`, `before_kickoff_callbacks`, `after_kickoff_callbacks`. `kickoff(inputs=)`
  is template interpolation, not an options bag (`:381-382` comment in the adapter).
- Lifecycle hooks: `step_callback` / `task_callback` on `Crew`.
- AK-owned: `agents`, `tasks`, `memory`. `verbose=False` is a value AK chose, not something AK
  depends on.

## Smolagents

- Adapter call site: `framework/smolagents/smolagents.py:159-164` already builds a kwargs dict
  (`run_kwargs = {"reset": False}` plus `additional_args` when a framework context is present) and
  calls `agent.agent.run(prompt, **run_kwargs)` in a thread.
- Native signature (1.26.0): `MultiStepAgent.run(task, stream=False, reset=True, images=None,
  additional_args=None, max_steps=None, return_full_result=None)`.
- Turn-pressure equivalent: `max_steps` (also a constructor argument on the user-built agent).
- Lifecycle hooks: `step_callbacks` on the **agent constructor**, which the user owns, so progress
  hooks need nothing from AK here.
- AK-owned: `task` (positional), `reset`, `additional_args`. `stream` and `return_full_result`
  change the return type the adapter maps at `:176-180`.

## Cross-cutting findings

- Every adapter inlines a fixed kwarg set at its native call; smolagents is the only one with a
  kwargs dict already.
- Two adapters construct the native runner object per run (ADK `Runner`, CrewAI `Crew`), so
  constructor-level options are unreachable there and must route through AK.
- Every module picks exactly one runner: the `runner=` argument, else the trace runner, else the
  default (`openai.py:435-440`, `langgraph.py:649-652`, `adk.py:495-498`, `pydanticai.py:537-540`,
  `crewai.py:562-565`, `smolagents.py:321-324`). All 18 trace runners (`trace/langfuse/*`,
  `trace/logfire/*`, `trace/openllmetry/*`) call `super().run(agent, session, requests)`, so
  anything the base runner reads off the `Agent` flows through them unchanged.
- Every framework has both a hard cap on the loop (`max_turns`, `recursion_limit`, `max_llm_calls`,
  `usage_limits`, `max_steps`) and a lifecycle-hook mechanism; the names and destinations differ, the
  shape (a per-run options bag with some AK-owned keys) does not.
