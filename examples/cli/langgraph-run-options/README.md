# Agent Kernel: per-agent native run options (LangGraph)

This demo shows how to pass LangGraph's own **per-run `RunnableConfig`** to a graph through Agent
Kernel: a callback handler that reports progress and a higher `recursion_limit`. Neither is reachable
through the plain `LangGraphModule([...])` call; both are declared once, at load time, with
`Module.run_options`:

```python
LangGraphModule([weather_agent]).run_options(
    weather_agent,
    config={"callbacks": [ProgressCallbackHandler()], "recursion_limit": 50},
)
```

## How it works

1. **Declaration.** `run_options(graph, **options)` is chained like `pre_hook` / `post_hook`. The
   keywords are `ainvoke` / `astream_events`'s own arguments (`config`, `context`, `interrupt_before`,
   `interrupt_after`, `durability`, ...).
2. **The `config` merge.** Agent Kernel builds its own config with `configurable.thread_id` set to the
   session id. Your `config` is deep-merged under it: dict-valued keys merge with Agent Kernel's entries
   winning, list-valued keys (`callbacks`, `tags`) concatenate with Agent Kernel's entries first, and
   every other key is yours. With Langfuse tracing enabled, the graph therefore receives
   `[langfuse_handler, ProgressCallbackHandler()]`.
3. **Reserved keys.** `input`, `version`, `stream_mode`, `output_keys`, `print_mode` and the nested
   `config.configurable.thread_id` raise `ValueError` at declaration.
4. **Progress.** `ProgressCallbackHandler` is a plain LangChain `AsyncCallbackHandler`. It runs on the
   event loop the graph runs on, so `Session.current()` resolves and it increments per-turn counters
   in the session's volatile cache.
5. **Showing it.** `AppendRunStatsPostHook` appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: llm_calls=2, tool_calls=1, recursion_limit=50
```

## Two ways to see progress

| Path | Mode | What you get |
|---|---|---|
| Agent Kernel stream events (`PostHook.on_stream_event`) | `execution.mode: stream` only | framework-agnostic `ToolCallStart`, `TextDelta`, ... for what the adapter maps |
| Native callbacks through run options (this demo) | any mode, including `rest_sync` | LangChain's full callback surface: chain, chat model, tool, retriever events |

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s
