import logging

from agent_framework import Agent, ChatContext, FunctionInvocationContext, chat_middleware, function_middleware
from agent_framework.openai import OpenAIChatClient
from agentkernel.cli import CLI
from agentkernel.core import AgentReplyText, PostHook, Session
from agentkernel.maf import MAFModule, MAFToolBuilder

logger = logging.getLogger("ak.example.maf_run_options")

STATS_PREFIX = "Run stats:"
MAX_TOKENS = 300  # a ChatOptions key, declared inside MAF's own `options` mapping
TENANT = "acme"  # reaches every tool call through MAF's `function_invocation_kwargs`


def _cache():
    """The AK session's volatile cache, or None outside a run (Session.current() resolves in the handler)."""
    session = Session.current()
    return None if session is None else session.get_volatile_cache()


def get_weather(city: str) -> str:
    """Returns the weather for a given city (example stub)."""
    if city == "Tokyo":
        return "The weather in Tokyo is sunny."
    return f"Cannot find weather for {city}."


# The progress hooks, in MAF's own form: middleware on the agent. MAF has no per-run hook argument, so this part
# needs nothing from Agent Kernel. Both run inside the Agent Kernel run, so Session.current() resolves.
@chat_middleware
async def count_model_requests(context: ChatContext, call_next):
    """Count the attempted model request and cache its max_tokens option before awaiting the next middleware.

    Without an active session, skip recording statistics. Errors from the next middleware propagate.
    """
    cache = _cache()
    if cache is not None:
        cache.set("llm_calls", (cache.get("llm_calls") or 0) + 1)
        cache.set("max_tokens", (context.options or {}).get("max_tokens"))  # what the model call actually received
    await call_next()


@function_middleware
async def count_tool_calls(context: FunctionInvocationContext, call_next):
    """Count the attempted tool call and cache its tenant argument before awaiting the next middleware.

    Without an active session, skip recording statistics. Errors from the next middleware propagate.
    """
    cache = _cache()
    if cache is not None:
        cache.set("tool_calls", (cache.get("tool_calls") or 0) + 1)
        cache.set("tenant", context.kwargs.get("tenant"))  # what the tool call actually received
    await call_next()


class AppendRunStatsPostHook(PostHook):
    """Append a deterministic 'Run stats:' line to every reply, read from the volatile cache the middleware filled."""

    async def on_run(self, session, requests, agent, agent_reply):
        """Append cached run statistics to a text reply in place and return the same reply.

        Return the reply unchanged when no session is supplied or the reply is not text.
        """
        if session is None or not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        cache = session.get_volatile_cache()
        stats = ", ".join(
            [
                f"llm_calls={cache.get('llm_calls') or 0}",
                f"tool_calls={cache.get('tool_calls') or 0}",
                f"max_tokens={cache.get('max_tokens')}",  # received by the model call
                f"tenant={cache.get('tenant')}",  # received by the tool call
                f"declared_max_tokens={agent.run_options['options']['max_tokens']}",  # read back from the agent
            ]
        )
        agent_reply.response = f"{agent_reply.response}\n\n{STATS_PREFIX} {stats}"
        return agent_reply

    def name(self) -> str:
        """Return the fixed name identifying this post hook."""
        return "append_run_stats"


client = OpenAIChatClient(model="gpt-4.1-mini")

weather_agent = Agent(
    client,
    name="weather",
    description="Weather assistant",
    instructions="You provide weather information upon request. Use the get_weather tool for every weather question. "
    "Give short and direct answers.",
    tools=MAFToolBuilder.bind([get_weather]),
    middleware=[count_model_requests, count_tool_calls],
)

# The declaration. Both keywords are `agent.run`'s own arguments: model settings nest inside `options`, and
# `function_invocation_kwargs` is forwarded to every tool call. Agent Kernel copies them into the call and writes
# the keys it owns (`session`, `stream`) last; both apply in run mode and in stream mode.
MAFModule([weather_agent]).run_options(
    weather_agent,
    options={"max_tokens": MAX_TOKENS},
    function_invocation_kwargs={"tenant": TENANT},
).post_hook(weather_agent, [AppendRunStatsPostHook()])

if __name__ == "__main__":
    CLI.main()
