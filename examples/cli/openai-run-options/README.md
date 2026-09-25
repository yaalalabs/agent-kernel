# Agent Kernel: per-agent native run options (OpenAI Agents SDK)

This demo shows how to pass the OpenAI Agents SDK's own **per-run options** to an agent through Agent
Kernel: a higher `max_turns`, a `RunHooks` instance that reports progress, and a `RunConfig` carrying a
`call_model_input_filter`. None of these is reachable through the plain `OpenAIModule([...])` call; all
three are declared once, at load time, with `Module.run_options`:

```python
OpenAIModule([weather_agent]).run_options(
    weather_agent,
    max_turns=25,
    hooks=ProgressHooks(),
    run_config=RunConfig(call_model_input_filter=trim_history),
)
```

Every keyword is one of `Runner.run` / `Runner.run_streamed`'s own arguments. Agent Kernel copies the
declared options into the native call and writes the keys it owns (`session`, `context`) last.

## How it works

1. **Declaration.** `run_options(agent, **options)` is chained like `pre_hook` / `post_hook`. Repeated
   calls merge, the later call winning per key. A key the adapter reserves (`starting_agent`, `input`,
   `session`, `context`) raises `ValueError` at declaration, never per request.
2. **Progress.** `ProgressHooks` is a plain SDK `RunHooks` subclass. Its callbacks run inside the Agent
   Kernel run, so `Session.current()` resolves and the hook increments counters in the session's
   volatile cache. Nothing per request is threaded through; the hook instance is declared once.
3. **Turn pressure.** `max_turns=25` raises the SDK's default of 10, and `trim_history` (the
   `call_model_input_filter`) keeps only the last 20 input items on every model call. It bumps a
   `filter_runs` counter so you can see it run.
4. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply. Post-hooks run
   before the volatile cache is cleared, so they see the counters the native hooks filled.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, filter_runs=2, max_turns=25
```

## Two ways to see progress

| Path | Mode | What you get |
|---|---|---|
| Agent Kernel stream events (`PostHook.on_stream_event`) | `execution.mode: stream` only | framework-agnostic `ToolCallStart`, `TextDelta`, ... for what the adapter maps |
| Native hooks through run options (this demo) | any mode, including `rest_sync` | the SDK's full lifecycle: `on_agent_start`, `on_llm_start`, `on_tool_start`, handoffs |

## Notes

- A hook instance in `run_options` is shared by every concurrent run of that agent. Keep per-run state
  in the session (as this demo does), not on the hook.
- `trim_history` drops a leading `function_call_output` whose call fell outside the kept window, so a
  tool call and its output are never split (the Responses API rejects an orphan output). A real filter
  would more likely trim at message boundaries; the demo keeps it short to show the mechanism.
- The `Run stats:` line reads the limit back from `agent.run_options`, so it reflects what was
  declared rather than echoing a constant; the counters are what prove the options reached the SDK.
- Options compose with tracing: the Langfuse, Logfire and OpenLLMetry runners delegate to the base
  runner, so a declared `hooks=` still reaches the SDK when tracing is enabled.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
