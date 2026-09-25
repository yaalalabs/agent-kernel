import logging

from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.langgraph import LangGraphModule, LangGraphToolBuilder
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

logger = logging.getLogger("ak.example.langgraph_run_options")

STATS_PREFIX = "Run stats:"
RECURSION_LIMIT = 50  # LangGraph's default is 25 super-steps; long tool loops need more


def _bump(key: str) -> None:
    """Increment a per-turn counter in the AK session's volatile cache (Session.current() resolves in the callback)."""
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


# The progress hook, in LangChain's own form: a callback handler. The async variant runs on the event
# loop the graph runs on, so the AK session context is available to it.
class ProgressCallbackHandler(AsyncCallbackHandler):
    async def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        _bump("llm_calls")

    async def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        _bump("tool_calls")


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the callbacks filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"recursion_limit={RECURSION_LIMIT}",
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        return "append_run_stats"


model = ChatOpenAI(model="gpt-4.1-mini", temperature=0.0)

weather_agent = create_react_agent(
    name="weather",
    tools=LangGraphToolBuilder.bind([get_weather]),
    model=model,
    prompt="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
)

# The declaration. `config` is LangGraph's RunnableConfig; Agent Kernel deep-merges it with the config it
# builds itself: `configurable.thread_id` stays the session id, `callbacks` lists concatenate (a tracing
# runner's handler first), everything else here is yours.
LangGraphModule([weather_agent]).run_options(
    weather_agent,
    config={"callbacks": [ProgressCallbackHandler()], "recursion_limit": RECURSION_LIMIT},
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
