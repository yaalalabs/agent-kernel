import logging
from typing import TYPE_CHECKING, Any, Optional

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.tools.tool import ToolResult

from ...core import Agent
from ...core.config import AKConfig
from ...core.model import BaseRunRequest
from ...core.runtime import Runtime

if TYPE_CHECKING:  # pragma: no cover: annotation only; api reaches pipeline lazily
    from ...pipeline.request_client import QueueRequestClient


class MCP:
    """
    Manages and builds an instance of FastMCP and provides tools using executors.

    This class provides a framework to manage and expose tools for
    interaction with Agent Kernel's FastMCP. Agent tools never run the agent here: each executor
    puts the request on the input queue and waits for the runner's whole reply in the response
    store (#780). Tools an application adds to ``MCP.get()`` are its own code and still run here.
    """

    PROTOCOL = "mcp"
    """
    Value of the queue message's ``protocol`` attribute for MCP requests
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
    _client: Optional["QueueRequestClient"] = None
    """
    The surface's one queue client, built on first use
    """

    class Executor:
        ERROR_MESSAGE = "The agent could not process the request"
        TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.log = logging.getLogger(f"ak.mcp.executor.{agent_name}")

        async def execute(self, session_id: str, prompt: str, ctx: Context) -> Any:
            """Run the agent on the agent runner and return its reply in the richest shape MCP can carry.

            The reply is the body the runner stored, so a structured payload arrives as the object
            ``ResponseBuilder`` put in ``result`` rather than flattened to text.

            A reply carrying a media type becomes a ``ToolResult``: the payload travels as
            ``structuredContent`` and the format rides in ``_meta``, MCP's own slot for
            implementation metadata. The alternative — wrapping the payload in an Agent Kernel
            envelope — was rejected because it changes the shape a client receives.

            An array payload is the one exception, and it is MCP's constraint rather than a choice:
            ``structuredContent`` is an object by specification, and fastmcp refuses a list outright.
            Such a payload travels under ``result`` — fastmcp's own convention for a non-object
            return — with the ``fastmcp.wrap_result`` flag that makes a fastmcp client unwrap it
            again, so the caller still receives the array it was sent.

            Every reply without a media type returns the runner's ``result`` text: a text reply as
            is, an unlabelled structured reply as JSON text, and an image reply as its response
            naming the attached image.

            A failed run, a timeout or any other error raises ``ToolError`` with a fixed message;
            the details go to this executor's log only.
            """
            from ...pipeline.request_client import ReplyTimeoutError

            await ctx.info(f"Executing agent '{self.agent_name}' with prompt: {prompt} with session_id: {session_id}")
            body = BaseRunRequest(prompt=prompt, agent=self.agent_name, session_id=session_id)
            try:
                reply = await MCP.get_client().request(body, protocol=MCP.PROTOCOL)
            except ReplyTimeoutError as e:
                self.log.error(f"No reply within the wait budget: request_id={e.request_id}, retry_count={e.retry_count}, delay={e.delay}")
                raise ToolError(self.TIMEOUT_MESSAGE) from e
            except Exception as e:
                self.log.exception(f"Agent request failed: {e}")
                raise ToolError(self.ERROR_MESSAGE) from e

            if reply.is_error or reply.result is None:
                self.log.error(f"Agent reply failed: request_id={reply.request_id}, status_code={reply.status_code}, error={reply.error}")
                raise ToolError(self.ERROR_MESSAGE)

            await ctx.debug(f"Agent response '{reply.result}'")
            if reply.media_type:
                meta: dict[str, Any] = {"media_type": reply.media_type}
                if isinstance(reply.result, dict):
                    return ToolResult(structured_content=reply.result, meta=meta)
                meta["fastmcp"] = {"wrap_result": True}
                return ToolResult(structured_content={"result": reply.result}, meta=meta)
            return reply.result

    @classmethod
    def get_client(cls) -> "QueueRequestClient":
        """The surface's one queue client, built on first use.

        Imported here, not at module scope: ``api`` reaches ``pipeline`` lazily, as ``RESTAPI.run`` does.
        """
        if cls._client is None:
            from ...pipeline.request_client import QueueRequestClient

            cls._client = QueueRequestClient()
        return cls._client

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
