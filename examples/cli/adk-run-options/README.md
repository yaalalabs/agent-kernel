# Agent Kernel: per-agent native run options (Google ADK)

This demo shows how to pass Google ADK's own **per-run options** to an agent through Agent Kernel: a
`plugins` list that reports progress and a `RunConfig` with `max_llm_calls`. Agent Kernel constructs
the ADK `Runner` per run, so a plugin cannot be attached any other way. Both are declared once, at load
time, with `Module.run_options`:

```python
GoogleADKModule([weather_agent]).run_options(
    weather_agent,
    plugins=[ProgressPlugin()],
    run_config=RunConfig(max_llm_calls=20),
)
```

## How it works

1. **Two destinations.** `plugins`, `memory_service`, `artifact_service`, `credential_service` and
   `plugin_close_timeout` go to the per-run `Runner(...)` constructor; `run_config` goes to
   `run_async`. Agent Kernel splits them for you and writes the keys it owns (`agent`, `app_name`,
   `session_service`, `user_id`, `session_id`, `new_message`, ...) last.
2. **Stream mode.** The adapter's stream mapping depends on ADK's partial (SSE) events, so in
   `execution.mode: stream` your `RunConfig` is copied with `streaming_mode=SSE`. One warning is
   logged per runner when your value differed; your object is never mutated. In run mode it is passed
   as is.
3. **Reserved keys.** `agent`, `app`, `app_name`, `node`, `session_service`, `auto_create_session`,
   `user_id`, `session_id`, `new_message`, `state_delta`, `invocation_id`, `yield_user_message` raise
   `ValueError` at declaration. State seeding belongs to `framework_context`.
4. **Progress.** `ProgressPlugin` is a plain ADK `BasePlugin`. Its callbacks run inside the Agent
   Kernel run, so `Session.current()` resolves and it increments per-turn counters in the session's
   volatile cache.
5. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, max_llm_calls=20
```

## Two ways to see progress

| Path | Mode | What you get |
|---|---|---|
| Agent Kernel stream events (`PostHook.on_stream_event`) | `execution.mode: stream` only | framework-agnostic `ToolCallStart`, `TextDelta`, ... for what the adapter maps |
| Native plugins through run options (this demo) | any mode, including `rest_sync` | ADK's full plugin surface: run, agent, model and tool callbacks |

Per-agent callbacks (`before_model_callback=` on the `Agent` itself) were always reachable; plugins are
what run options add.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
