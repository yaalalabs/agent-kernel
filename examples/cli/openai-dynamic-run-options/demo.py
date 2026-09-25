import logging
from typing import Any

from agentkernel.cli import CLI
from agentkernel.core import Agent as AKAgent
from agentkernel.core import AgentReplyText, AgentRequest, PostHook, Session
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent, RunConfig, RunHooks

logger = logging.getLogger("ak.example.openai_dynamic_run_options")

STATS_PREFIX = "Run stats:"
MAX_TURNS = 25  # the static limit: the SDK default is 10, long tool loops need more
GUEST_MAX_TURNS = 10  # the per-run limit the factory applies to guest sessions


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache.

    Native hooks and the run-options factory both run inside the Agent Kernel run, so Session.current()
    resolves here. The volatile cache is cleared after every run, which is what makes the counters per turn.
    """
    session = Session.current()
    if session is None:
        return
    cache = session.get_volatile_cache()
    cache.set(key, (cache.get(key) or 0) + 1)


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The static progress hook, in the SDK's own form: a RunHooks subclass declared once at load time.
class ProgressHooks(RunHooks):
    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        _bump("llm_calls")

    async def on_tool_start(self, context, agent, tool) -> None:
        _bump("tool_calls")


# The factory. Agent Kernel calls it on every run, after the pre-hooks, with the AK agent, the session and the
# request list the run will use, and merges the mapping it returns over the static keywords declared beside it
# (a factory key wins). It is one object shared by every concurrent run of the agent, so it keeps no state on
# itself: what it wants to show later goes into the session's volatile cache, like the hooks above.
def options_for(agent: AKAgent, session: Session, requests: list[AgentRequest]) -> dict[str, Any]:
    _bump("factory_runs")
    logger.debug("computing run options for session %s with %d request(s)", session.id, len(requests))
    # Per-run knowledge the static declaration cannot have: the session id, stamped onto the SDK trace.
    options: dict[str, Any] = {"run_config": RunConfig(trace_metadata={"session_id": session.id})}
    # A per-run override of a static keyword: guest sessions get a tighter turn budget.
    if session.id.startswith("guest"):
        options["max_turns"] = GUEST_MAX_TURNS
    # Record the limit this run will actually use, so the stats line can show which one applied.
    effective = options.get("max_turns", agent.run_options.get("max_turns"))
    session.get_volatile_cache().set("max_turns", effective)
    return options


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the cache the hooks and the factory filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"factory_runs={cache.get('factory_runs') or 0}",  # once per run: the options are resolved exactly once
                f"max_turns={cache.get('max_turns') or 0}",  # the effective limit the factory recorded for this run
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = Agent(
    name="weather",
    instructions="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
    tools=OpenAIToolBuilder.bind([get_weather]),
    model="openai/gpt-4.1-mini",
)

# The declaration: a factory beside static keywords, in one call. `max_turns` and `hooks` are declared once and
# apply to every run; `options_for` runs per call and its keys are merged over them. Agent Kernel then writes the
# keys it owns (session, context) last, exactly as for static options.
OpenAIModule([weather_agent]).run_options(
    weather_agent,
    options_for,
    max_turns=MAX_TURNS,
    hooks=ProgressHooks(),
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
