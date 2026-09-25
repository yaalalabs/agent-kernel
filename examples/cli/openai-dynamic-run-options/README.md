# Agent Kernel: per-run computed native run options (OpenAI Agents SDK)

This demo shows the callable form of `Module.run_options`: a **factory** that computes the OpenAI Agents
SDK's per-run options on every run, declared in the same call as the static keywords it complements. The
static part is what [`openai-run-options`](../openai-run-options) shows (a higher `max_turns`, a `RunHooks`
progress hook); the factory adds what only the run knows, such as the session id:

```python
def options_for(agent, session, requests):
    options = {"run_config": RunConfig(trace_metadata={"session_id": session.id})}
    if session.id.startswith("guest"):
        options["max_turns"] = 10  # a tighter budget for guest sessions, over the static 25
    return options

OpenAIModule([weather_agent]).run_options(
    weather_agent,
    options_for,  # computed per run
    max_turns=25,  # static, every run
    hooks=ProgressHooks(),
)
```

## How it works

1. **The factory contract.** The positional argument before the keywords is a callable
   `(agent, session, requests) -> mapping`, sync or async. Agent Kernel calls it exactly once per run, after
   the pre-hooks (so it sees the request list the run will actually use) and before the native call.
   `ToolContext.get()`, `Session.current()` and `Agent.current()` resolve inside it.
2. **Merge order.** The result is validated against the adapter's reserved keys, then merged over the static
   keywords at the top level: a key the factory returns wins, a key it does not name keeps its static value,
   and a dict-valued option it returns replaces the static one wholesale. Agent Kernel then writes the keys
   it owns (`session`, `context`) last, as for static options.
3. **One shared instance.** The factory is one object shared by every concurrent run of the agent. Keep
   per-run state in the session, not on the factory: this demo counts its runs and records the effective
   `max_turns` in the session's volatile cache, which is cleared after every run.
4. **The guest switch.** For a session whose id starts with `guest`, the factory returns `max_turns=10` over
   the static 25; any other session keeps 25 and gets only the trace metadata. The CLI session id is a UUID,
   so the `Run stats:` line below shows the static limit.
5. **Errors.** A factory that raises, returns a non-mapping, or names a reserved key fails that run the way a
   framework error does: a user-facing error reply in `rest_sync`, a propagated exception in `stream`.
   Nothing is cached, so the failure repeats on every run until the factory is fixed.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, factory_runs=1, max_turns=25
```

## Notes

- The static declaration still works unchanged: `run_options(agent, max_turns=25)` with no factory resolves
  to exactly the static dict on every run.
- A later `run_options(agent, other_factory)` call replaces the factory; keyword calls keep merging.
- The parameter is positional-only, so a native option that happens to be called `factory` is still declared
  as a keyword.
- Options compose with tracing: the traced runners delegate to the base runner, so the factory is resolved
  there too.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
