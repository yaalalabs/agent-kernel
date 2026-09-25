# Agent Kernel: per-agent native run options (Pydantic AI)

This demo shows how to pass Pydantic AI's own **per-run options** to an agent through Agent Kernel: a
`UsageLimits` cap on model requests and an `event_stream_handler` that reports progress. Neither is
reachable through the plain `PydanticAIModule([...])` call; both are declared once, at load time, with
`Module.run_options`:

```python
PydanticAIModule([weather_agent]).run_options(
    weather_agent,
    usage_limits=UsageLimits(request_limit=10),
    event_stream_handler=count_events,
)
```

## How it works

1. **Declaration.** The keywords are `agent.run`'s own arguments (`usage_limits`, `model_settings`,
   `retries`, `metadata`, `toolsets`, `event_stream_handler`, ...). Agent Kernel copies them into the
   call and writes the keys it owns (`message_history`, `deps`) last.
2. **Reserved keys.** `user_prompt`, `message_history` and `deps` raise `ValueError` at declaration.
   Per-run state belongs to `framework_context`, which the adapter injects as `deps`.
3. **Stream mode.** `run_stream_events` does not accept `event_stream_handler` (it is itself the event
   stream), so in `execution.mode: stream` the handler is dropped with one warning per runner and the
   adapter's own stream events carry the same information. `usage_limits` applies in both modes.
4. **Progress.** `count_events` is a plain Pydantic AI `event_stream_handler`. The SDK calls it for
   every model request stream and every tool batch, inside the Agent Kernel run, so
   `Session.current()` resolves. It counts `FunctionToolCallEvent`s and records `ctx.usage.requests`.
5. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, request_limit=10
```

## Two ways to see progress

| Path | Mode | What you get |
|---|---|---|
| Agent Kernel stream events (`PostHook.on_stream_event`) | `execution.mode: stream` only | framework-agnostic `ToolCallStart`, `TextDelta`, ... for what the adapter maps |
| Native `event_stream_handler` through run options (this demo) | run mode (`rest_sync`, the CLI) | Pydantic AI's own event stream plus the run's `RunContext` and usage |

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
