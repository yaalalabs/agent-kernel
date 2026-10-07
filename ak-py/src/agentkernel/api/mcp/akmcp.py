import logging
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.tools.tool import ToolResult

from ...core import Agent, AgentService
from ...core.config import AKConfig
from ...core.model import AgentReplyAny, AgentRequestText
from ...core.runtime import Runtime


class MCP:
    """
    Manages and builds an instance of FastMCP and provides tools using executors.

    This class provides a framework to manage and expose tools for
    interaction with Agent Kernel's FastMCP. It supports asynchronous
    execution of agents through an internal executor mechanism.
    """

    _fastmcp = None
    """
    FastMCP instance
    """
    _executors: dict[str, "MCP.Executor"] = {}
    """
    MCP executors to expose as tools.
    """
    _built = False
    """
    Tool built flag
    """

    class Executor:
        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.log = logging.getLogger(f"ak.mcp.executor.{agent_name}")

        async def execute(self, session_id: str, prompt: str, ctx: Context) -> Any:
            """Run the agent and return its reply in the richest shape MCP can carry.

            Goes through ``run_multi`` rather than ``run`` because ``run`` stringifies the reply
            before this method ever sees it, so a structured payload would arrive already flattened.

            A reply carrying a media type becomes a ``ToolResult``: the payload travels as
            ``structuredContent`` and the format rides in ``_meta``, MCP's own slot for
            implementation metadata. The alternative — wrapping the payload in an Agent Kernel
            envelope — was rejected because it changes the shape a client receives. Every other
            reply, including a structured one with no media type, still returns exactly the string
            it did before.
            """
            service = AgentService()
            await ctx.info(f"Executing agent '{self.agent_name}' with prompt: {prompt} with session_id: {session_id}")
            service.select(session_id, self.agent_name)
            reply = await service.run_multi([AgentRequestText(prompt=prompt)])
            await ctx.debug(f"Agent response '{reply}'")
            if isinstance(reply, AgentReplyAny) and reply.media_type:
                return ToolResult(structured_content=reply.content, meta={"media_type": reply.media_type})
            return str(reply)

    @classmethod
    def get(cls) -> FastMCP:
        cls._build()
        return cls._fastmcp

    @classmethod
    def get_http_app(cls) -> StarletteWithLifespan:
        cls._build()
        return cls._fastmcp.http_app(path="/", stateless_http=AKConfig.get().mcp.stateless_http)

    @classmethod
    def _build(cls):
        if cls._built or not AKConfig.get().mcp.enabled:
            return
        if cls._fastmcp is None:
            cls._fastmcp = FastMCP("Agent Kernel FastMCP Instance")
        if AKConfig.get().mcp.expose_agents:
            agents: dict[str, Agent] = Runtime.current().agents()
            for name, agent in agents.items():
                whitelisted = AKConfig.get().mcp.agents == ["*"] or name in AKConfig.get().mcp.agents
                if not whitelisted:
                    continue
                # Add executor
                cls._executors[name] = cls.Executor(name)
                cls._fastmcp.tool(
                    cls._executors[name].execute,
                    name=name,
                    description=agent.get_description(),
                )
        cls._built = True
