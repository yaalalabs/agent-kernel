import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import FunctionToolCallEvent
from pydantic_ai.usage import UsageLimits

logger = logging.getLogger("ak.example.pydanticai_run_options")

STATS_PREFIX = "Run stats:"
MODEL = "openai:gpt-4.1-mini"
REQUEST_LIMIT = 10  # Pydantic AI's cap on model requests per run; the SDK default is 50


def _cache():
    """The AK session's volatile cache, or None outside a run (Session.current() resolves in the handler)."""
    session = Session.current()
    return None if session is None else session.get_volatile_cache()


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The progress hook, in Pydantic AI's own form: an event_stream_handler. The SDK calls it for every model
# request stream and every tool batch; the run's cumulative usage is on the RunContext.
async def count_events(ctx: RunContext, events) -> None:
    cache = _cache()
    async for event in events:
        if isinstance(event, FunctionToolCallEvent) and cache is not None:
            cache.set("tool_calls", (cache.get("tool_calls") or 0) + 1)
    if cache is not None:
        cache.set("llm_calls", ctx.usage.requests)


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the handler filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"request_limit={REQUEST_LIMIT}",
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = Agent(
    model=MODEL,
    name="weather",
    description="Weather assistant",
    instructions="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
    tools=PydanticAIToolBuilder.bind([get_weather]),
)

# The declaration. Both keywords are `agent.run`'s own arguments. In Agent Kernel stream mode
# `event_stream_handler` is dropped with one warning (the runner's own stream events carry the same
# information); `usage_limits` applies in both modes.
PydanticAIModule([weather_agent]).run_options(
    weather_agent,
    usage_limits=UsageLimits(request_limit=REQUEST_LIMIT),
    event_stream_handler=count_events,
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
