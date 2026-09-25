import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder
from smolagents import CodeAgent, LiteLLMModel

logger = logging.getLogger("ak.example.smolagents_run_options")

STATS_PREFIX = "Run stats:"
MAX_STEPS = 6  # the cap on agent steps per run, passed to agent.run; the constructor default is 20


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache.

    Agent Kernel runs agent.run through asyncio.to_thread, which carries the context variables, so
    Session.current() resolves inside the step callback.
    """
    session = Session.current()
    if session is None:
        return
    cache = session.get_volatile_cache()
    cache.set(key, (cache.get(key) or 0) + 1)


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub).

    Args:
        city: The string name of the city.
    """
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The progress hook needs nothing from Agent Kernel here: smolagents takes step_callbacks on the agent
# constructor, which you own. It is shown for completeness next to the run option below.
def record_step(memory_step, agent=None) -> None:
    _bump("steps")


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the callback filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join([f"steps={cache.get('steps') or 0}", f"max_steps={MAX_STEPS}"])
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = CodeAgent(
    tools=SmolagentsToolBuilder.bind([get_weather]),
    model=LiteLLMModel(model_id="openai/gpt-4.1-mini"),
    name="weather",
    description="Weather assistant. Use the get_weather tool for every weather question and give short, direct answers.",
    step_callbacks=[record_step],
    use_structured_outputs_internally=True,
)

# The declaration. `max_steps` is agent.run's own argument; Agent Kernel merges it into the call and writes
# the keys it owns (reset, additional_args) last.
SmolagentsModule([weather_agent]).run_options(weather_agent, max_steps=MAX_STEPS).post_hook(
    weather_agent, [AppendRunStatsPostHook()]
)

if __name__ == "__main__":
    CLI.main()
