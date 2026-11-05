from agentkernel.claude import ClaudeAgentSpec, ClaudeModule, ClaudeToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

STATS_PREFIX = "Run stats:"
MODEL = "sonnet"
MAX_TURNS = 10  # ClaudeAgentOptions' own turn limit for this run


def _cache():
    """The AK session's volatile cache, or None outside a run (Session.current() resolves in the hook)."""
    session = Session.current()
    return None if session is None else session.get_volatile_cache()


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The progress hook, in Claude's own form: a native PostToolUse hook. The CLI calls it after every tool call in
# the run (matcher=None means every tool, built-in or Agent Kernel's own), with no involvement from Agent Kernel's
# post-hooks. Returning {} makes no decision for the tool that already ran — this hook only observes.
async def count_tool_calls(input_data, tool_use_id, context) -> dict:
    cache = _cache()
    if cache is not None:
        cache.set("tool_calls", (cache.get("tool_calls") or 0) + 1)
    return {}


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the hook filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"max_turns={agent.run_options['max_turns']}",  # read back from the agent
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = ClaudeAgentSpec(
    name="weather",
    description="Weather assistant",
    options=ClaudeAgentOptions(
        model=MODEL,
        tools=[],
        setting_sources=[],
        permission_mode="dontAsk",
        system_prompt="You provide weather information upon request. Use the get_weather tool for every weather "
        "question. Give short and direct answers.",
    ),
    tools=ClaudeToolBuilder.bind([get_weather]),
)

# The declaration. Both keywords are ClaudeAgentOptions' own fields, merged over the agent's static options for
# every run. `hooks` fires inside the Claude Code CLI as it runs, independent of Agent Kernel's own hooks.
ClaudeModule([weather_agent]).run_options(
    weather_agent,
    max_turns=MAX_TURNS,
    hooks={"PostToolUse": [HookMatcher(hooks=[count_tool_calls])]},
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
