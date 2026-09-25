# Agent Kernel: per-agent native run options (CrewAI)

This demo shows how to pass CrewAI's own **`Crew` options** to an agent through Agent Kernel: a
`step_callback` that reports progress and a `max_rpm` throttle. Agent Kernel builds one `Crew` per run,
so these cannot be set any other way. Both are declared once, at load time, with `Module.run_options`:

```python
CrewAIModule([weather_agent]).run_options(
    weather_agent,
    step_callback=record_step,
    max_rpm=30,
)
```

## How it works

1. **Declaration.** The keywords are the `Crew(...)` constructor's own arguments (`step_callback`,
   `task_callback`, `max_rpm`, `planning`, ...). Agent Kernel copies them into the constructor and
   writes the keys it owns (`agents`, `tasks`, `memory`) last. `verbose=False` is a default you may
   override. `max_rpm` is a requests-per-minute rate limit, not a loop cap: the cap on iterations is
   `max_iter` on the native `Agent`, which you already own (shown on the constructor in `demo.py`).
2. **Resolution by role.** CrewAI agents are registered under their `role`, so `run_options` resolves
   the wrapped agent by `role` too.
3. **Reserved keys.** `agents`, `tasks` and `memory` raise `ValueError` at declaration. Task-level
   options (`output_pydantic`, `output_json`) stay on the `CrewAIModule` constructor.
4. **Progress.** `record_step` is a plain CrewAI `step_callback`. CrewAI runs the crew in a worker
   thread through `asyncio.to_thread`, which carries the context variables, so `Session.current()`
   resolves and the callback increments a per-turn counter in the session's volatile cache.
5. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: steps=2, max_rpm=30
```

## Progress paths

CrewAI has no token stream in Agent Kernel (`supports_streaming` is `False`), so the native
`step_callback` / `task_callback` through run options is the progress path for this framework.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
