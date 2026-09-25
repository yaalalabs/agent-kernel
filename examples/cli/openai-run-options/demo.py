import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent, RunConfig, RunHooks
from agents.run import CallModelData, ModelInputData

logger = logging.getLogger("ak.example.openai_run_options")

STATS_PREFIX = "Run stats:"
MAX_TURNS = 25  # the SDK default is 10; long tool loops need more
KEEP_LAST_ITEMS = 20  # what call_model_input_filter keeps of the input on every model call


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache.

    Native hooks run inside the Agent Kernel run, so Session.current() resolves here. The volatile
    cache is cleared after every run, which is what makes the counters per turn.
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


# The progress hook, in the SDK's own form: a RunHooks subclass. It is declared once at load time and
# reads the current AK session from inside its callbacks, so no per-request plumbing is needed.
class ProgressHooks(RunHooks):
    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        _bump("llm_calls")

    async def on_tool_start(self, context, agent, tool) -> None:
        _bump("tool_calls")


# The RunConfig option: a call_model_input_filter that trims the model input on every call. It also
# counts how often it ran, so the stats line shows it is really being invoked.
def trim_history(data: CallModelData) -> ModelInputData:
    _bump("filter_runs")
    model_data = data.model_data
    return ModelInputData(input=list(model_data.input)[-KEEP_LAST_ITEMS:], instructions=model_data.instructions)


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the hooks filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"filter_runs={cache.get('filter_runs') or 0}",
                f"max_turns={MAX_TURNS}",
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

# The declaration. Everything passed here is a keyword argument of the SDK's own Runner.run /
# Runner.run_streamed; Agent Kernel merges it into the call with its own keys (session, context) written last.
OpenAIModule([weather_agent]).run_options(
    weather_agent,
    max_turns=MAX_TURNS,
    hooks=ProgressHooks(),
    run_config=RunConfig(call_model_input_filter=trim_history),
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
