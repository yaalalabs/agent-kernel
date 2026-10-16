# Agent Kernel: per-agent native run options (Microsoft Agent Framework)

This demo shows how to pass Microsoft Agent Framework's own **per-run options** to an agent through Agent
Kernel: a model setting (`max_tokens`) inside MAF's `options` mapping, and `function_invocation_kwargs`, which
MAF forwards to every tool call. Neither is reachable through the plain `MAFModule([...])` call; both are
declared once, at load time, with `Module.run_options`:

```python
MAFModule([weather_agent]).run_options(
    weather_agent,
    options={"max_tokens": 300},
    function_invocation_kwargs={"tenant": "acme"},
)
```

## How it works

1. **Declaration.** The keywords are `Agent.run`'s own arguments (`options`, `function_invocation_kwargs`,
   `client_kwargs`, `tools`, `compaction_strategy`, ...). Model settings such as `temperature` and
   `response_format` nest inside `options`. Agent Kernel copies the keywords into the call and writes the keys
   it owns (`session`, `stream`) last.
2. **Reserved keys.** `messages`, `stream` and `session` raise `ValueError` at declaration. Per-run state
   belongs to `framework_context`, which the adapter injects as `session.state["ak_context"]`.
3. **Both modes.** The same keywords apply in run mode and in `execution.mode: stream`.
4. **Progress.** MAF has no per-run hook argument; its lifecycle hooks are **middleware on the agent**, so
   `count_model_requests` (a chat middleware) and `count_tool_calls` (a function middleware) need nothing from
   Agent Kernel. They run inside the Agent Kernel run, so `Session.current()` resolves, and they record what
   the native calls actually received: the model call's `options` and the tool call's keyword arguments.
5. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, max_tokens=300, tenant=acme, declared_max_tokens=300
```

`max_tokens` and `tenant` are read inside the native calls; `declared_max_tokens` is read back from the agent.
Seeing the same value in all of them shows the declaration reached MAF.

## Running

Install dependencies:

    ./build.sh

> Note: until a release of `agentkernel` that includes the `maf` extra is published to PyPI,
> build with `./build.sh local` against a locally built `ak-py/dist`; a plain `./build.sh` installs a
> PyPI release without `agentkernel.maf`.

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    uv run python demo.py

Run the tests:

    uv run pytest -s
