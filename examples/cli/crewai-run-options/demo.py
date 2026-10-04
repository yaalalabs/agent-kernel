import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.crewai import CrewAIModule, CrewAIToolBuilder
from crewai import Agent

logger = logging.getLogger("ak.example.crewai_run_options")

STATS_PREFIX = "Run stats:"
MAX_RPM = 30  # CrewAI's requests-per-minute throttle for the crew (a rate limit, not a loop cap)
MAX_ITER = 5  # the loop cap lives on the native Agent, which you own; it needs nothing from Agent Kernel


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache.

    CrewAI runs the crew in a worker thread through asyncio.to_thread, which carries the context
    variables, so Session.current() resolves inside the callback.
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


# The progress hook, in CrewAI's own form: a Crew step_callback, invoked after every agent step (a thought,
# a tool action, or the final answer).
def record_step(step) -> None:
    _bump("steps")


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the callback filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [f"steps={cache.get('steps') or 0}", f"max_rpm={agent.run_options['max_rpm']}"]
        )  # read back from the agent
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = Agent(
    role="weather",
    goal="Provide weather information upon request",
    backstory="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
    tools=CrewAIToolBuilder.bind([get_weather]),
    max_iter=MAX_ITER,
    verbose=False,
    llm="openai/gpt-4.1-mini",
)

# The declaration. The keywords are the Crew(...) constructor's own arguments: Agent Kernel builds one Crew
# per run and writes the keys it owns (agents, tasks, memory) last. `verbose=False` is a default you may
# override here. CrewAI agents are registered by `role`, so that is what resolves the wrapped agent.
CrewAIModule([weather_agent]).run_options(
    weather_agent,
    step_callback=record_step,
    max_rpm=MAX_RPM,
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
