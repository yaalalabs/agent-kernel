# Open Agent Kernel: per-agent native run options (Claude Agent SDK)

This demo shows how to pass the Claude Agent SDK's own **per-run options** to an agent through Agent
Kernel: a `max_turns` cap and a native `hooks` callback that reports progress. Neither is reachable
through the plain `ClaudeModule([...])` call; both are declared once, at load time, with
`Module.run_options`:

```python
ClaudeModule([weather_agent]).run_options(
    weather_agent,
    max_turns=10,
    hooks={"PostToolUse": [HookMatcher(hooks=[count_tool_calls])]},
)
```

## How it works

1. **Declaration.** The keywords are any field of `ClaudeAgentOptions` (`max_turns`, `max_budget_usd`,
   `model`, `hooks`, ...). Open Agent Kernel merges them over the agent's declared options and writes the
   keys it owns (`resume`, `session_id`, `session_store`, ...) last — declaring one of those raises
   `ValueError` naming the reason.
2. **Progress.** `count_tool_calls` is a plain Claude Agent SDK `PostToolUse` hook, registered through
   `hooks=`. The CLI calls it after every tool call in the run — built-in or OAK's own,
   because `matcher=None` matches any tool name — entirely inside the Claude Code subprocess, with no
   involvement from OAK's own hooks. It counts calls into the OAK session's volatile
   cache.
3. **Showing it.** `AppendRunStatsPostHook`, an ordinary OAK `PostHook`, reads that cache and
   the declared `max_turns` back off the agent, and appends a `Run stats:` line to every reply.

## Example session

```
(weather) >> What's the weather in Tokyo?
The weather in Tokyo is sunny.

Run stats: tool_calls=1, max_turns=10
```

## Two different "hook" mechanisms, side by side

| | OAK's `PostHook` | Claude's native `hooks=` |
|---|---|---|
| Runs | once per OAK run, after the reply | inside the Claude Code subprocess, as it runs |
| Sees | the final `AgentReply` | every matched tool call, as it happens |
| Declared via | `Module.post_hook(agent, [...])` | `Module.run_options(agent, hooks={...})` |
| Framework-agnostic | yes — the same `PostHook` works on any adapter | no — `HookMatcher`/`hooks=` is Claude's own shape |

This demo uses both together: the native hook counts, the OAK post-hook reports.

## Running

Install dependencies:

    ./build.sh

Install local `agentkernel` in development mode:

    ./build.sh local

Run the demo:

    python demo.py

Run the tests:

    uv run pytest -s

> Note: until a release of `agentkernel` that includes the `claude` extra is published to PyPI, build
> with `./build.sh local` against a locally built `ak-py/dist`.
