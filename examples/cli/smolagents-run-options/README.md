# Agent Kernel: per-agent native run options (smolagents)

This demo shows how to pass smolagents' own **`agent.run` argument** `max_steps` to an agent through
Agent Kernel, declared once, at load time, with `Module.run_options`:

```python
SmolagentsModule([weather_agent]).run_options(weather_agent, max_steps=6)
```

It also shows a progress hook, but that one needs nothing from Agent Kernel: smolagents takes
`step_callbacks` on the agent constructor, which you already own.

## How it works

1. **Declaration.** The keywords are `agent.run`'s own arguments (`max_steps`, `images`). Agent Kernel
   merges them into the call and writes the keys it owns (`reset`, `additional_args`) last.
2. **Reserved keys.** `task`, `reset`, `additional_args`, `stream` and `return_full_result` raise
   `ValueError` at declaration: the first three are populated by the adapter, the last two change the
   return type the adapter maps.
3. **Progress.** `record_step` is passed as `step_callbacks=[record_step]` on the `CodeAgent`. Agent
   Kernel runs `agent.run` through `asyncio.to_thread`, which carries the context variables, so
   `Session.current()` resolves inside the callback and it increments a per-turn counter in the
   session's volatile cache.
4. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: steps=2, max_steps=6
```

## Progress paths

smolagents has no token stream in Agent Kernel (`supports_streaming` is `False`), so the native
`step_callbacks` on the agent constructor is the progress path for this framework.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
