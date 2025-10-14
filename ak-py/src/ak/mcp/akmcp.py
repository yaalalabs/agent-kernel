import logging
from typing import Any

from fastmcp import FastMCP, Context
from fastmcp.server.http import StarletteWithLifespan

from ..core import AgentService, Agent, Runtime
from ..core.config import AKConfig


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
    _executors: dict[str, 'MCP.Executor'] = {}
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
            service = AgentService()
            await ctx.info(f"Executing agent '{self.agent_name}' with prompt: {prompt} with session_id: {session_id}")
            service.select(session_id, self.agent_name)
            response = await service.run(prompt=prompt)
            await ctx.debug(f"Agent response '{response}'")
            return response

    @classmethod
    def get(cls) -> FastMCP:
        cls._build()
        return cls._fastmcp

    @classmethod
    def get_http_app(cls) -> StarletteWithLifespan:
        cls._build()
        return cls._fastmcp.http_app(path="/")

    @classmethod
    def _build(cls):
        if cls._built or not AKConfig.get().mcp.enabled:
            return
        if cls._fastmcp is None:
            cls._fastmcp = FastMCP("Agent Kernel FastMCP Instance")
        if AKConfig.get().mcp.expose_agents:
            agents: dict[str, Agent] = Runtime.instance().agents()
            for name, agent in agents.items():
                whitelisted = AKConfig.get().mcp.agents == ["*"] or name in AKConfig.get().mcp.agents
                if not whitelisted:
                    continue
                # Add executor
                cls._executors[name] = cls.Executor(name)
                cls._fastmcp.tool(
                    cls._executors[name].execute,
                    name=name,
                    description=agent.get_description()
                )
        cls._built = True
