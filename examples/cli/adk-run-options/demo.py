import logging

from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger("ak.example.adk_run_options")

STATS_PREFIX = "Run stats:"
MAX_LLM_CALLS = 20  # ADK's cap on model calls per run; the SDK default is 500


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache (Session.current() resolves in the plugin)."""
    session = Session.current()
    if session is None:
        return
    cache = session.get_volatile_cache()
    cache.set(key, (cache.get(key) or 0) + 1)


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub).

    Args:
        city: The city to look up.
    """
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The progress hook, in ADK's own form: a plugin. Plugins belong to the ADK Runner, which Agent Kernel
# constructs per run, so this is the only way to attach one. Returning None lets the call proceed.
class ProgressPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="progress")

    async def before_model_callback(self, *, callback_context, llm_request):
        _bump("llm_calls")
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        _bump("tool_calls")
        return None


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the plugin filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"max_llm_calls={MAX_LLM_CALLS}",
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


weather_agent = Agent(
    name="weather",
    model=LiteLlm(model="openai/gpt-4.1-mini"),
    description="Weather assistant",
    instruction="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

# The declaration. `plugins` goes to the per-run ADK Runner constructor; `run_config` goes to run_async.
# In Agent Kernel stream mode the RunConfig is copied with streaming_mode=SSE (logged once); in run mode
# it is passed as is.
GoogleADKModule([weather_agent]).run_options(
    weather_agent,
    plugins=[ProgressPlugin()],
    run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
