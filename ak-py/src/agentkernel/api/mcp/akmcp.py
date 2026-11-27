import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthCheck, AuthContext
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.tools import ToolResult
from mcp.server.auth.provider import AccessToken

from ...core.config import AKConfig
from ...core.model import AgentDescriptor, BaseRunRequest, Principal
from ...core.runtime import Runtime
from .auth import AKAccessToken, AKMCPAuthProvider

if TYPE_CHECKING:  # pragma: no cover: annotation only; api reaches pipeline lazily
    from ...pipeline.request_handler import RestHandler


class MCP:
    """
    Manages and builds an instance of FastMCP and provides tools using executors.

    This class provides a framework to manage and expose tools for
    interaction with Agent Kernel's FastMCP. Agent tools never run the agent here: each executor
    puts the request on the input queue and waits for the runner's whole reply in the response
    store (#780). One is registered per agent the registry knows, named by the agent's id and
    described by its descriptor's catalog text. Tools an application adds to ``MCP.get()`` are its
    own code and still run here.

    With an ``authorization`` block the agent tools are the caller's own (#603): each carries a
    check FastMCP runs per request, so a caller is listed, and can call, only the agents it may
    see, and a call the access gate refuses is answered ``Agent not available``.
    """

    PROTOCOL = "mcp"
    """
    Value of the queue message's ``protocol`` attribute for MCP requests
    """
    UNDESCRIBED_TOOL_TEXT = "Sends a prompt to the '{agent}' agent and returns its reply."
    """
    The text of an agent's tool when the agent's descriptor declares no description: what calling the
    tool does, and nothing about the agent, since the agent's instructions are never catalog text
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
    _client: Optional["RestHandler"] = None
    """
    The surface's one queue client (the pipeline's ``RestHandler``), built on first use
    """
    _log = logging.getLogger("ak.mcp")

    class Executor:
        ERROR_MESSAGE = "The agent could not process the request"
        TIMEOUT_MESSAGE = "Timed out waiting for the agent's reply"
        UNAVAILABLE_MESSAGE = "Agent not available"
        """
        What a caller is told when the agent is not its to run: no level on it, hidden from it, or
        gone. One text for all three, so the answer says nothing about which
        """
        REFUSED_STATUSES = (403, 404)
        """
        The reply statuses that are the access gate's refusal, made before the queue or by the runner
        """

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.log = logging.getLogger(f"ak.mcp.executor.{agent_name}")

        async def execute(self, session_id: str, prompt: str) -> Any:
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
            the details go to this executor's log only. A call the access gate refuses (the caller
            holds no level on the agent, or may not see it) raises ``ToolError("Agent not available")``.

            With ``identity.credentials`` the call keeps its token for the run it starts (#603), here
            rather than in the verifier, which FastMCP asks on every HTTP request: an initialize, a
            notification or a listing runs nothing and so keeps nothing. Once a reply is in, the token
            is deleted, which also covers a call refused before the queue; a call that timed out leaves
            it to the run, whose runner deletes it.
            """
            from ...pipeline.request_handler import ReplyTimeoutError

            self.log.debug(f"Executing agent '{self.agent_name}' for session_id={session_id}")
            # The principal the verifier put on this call's access token; a server built without
            # auth, or a token another verifier minted, authenticated nobody we know.
            access_token = get_access_token()
            principal = await self._retain_credential(AKAccessToken.principal_of(access_token), access_token)
            # The body names the surface it entered by: the runner serves the call the agents on `mcp`, whatever the
            # agent's descriptor says of `rest`.
            body = BaseRunRequest(prompt=prompt, agent=self.agent_name, session_id=session_id, principal=principal, surface="mcp")
            try:
                reply = await MCP.get_client().request(body, protocol=MCP.PROTOCOL)
            except ReplyTimeoutError as e:
                self.log.error(f"No reply within the wait budget: request_id={e.request_id}, retry_count={e.retry_count}, delay={e.delay}")
                raise ToolError(self.TIMEOUT_MESSAGE) from e
            except Exception as e:
                self.log.exception(f"Agent request failed: {e}")
                raise ToolError(self.ERROR_MESSAGE) from e
            # A reply is in, so the run is over or never started: the token goes (a second delete after the runner's is harmless).
            await self._release_credential(principal)

            if reply.status_code in self.REFUSED_STATUSES:
                # The policy's reason names the principal and the agent: it is the operator's to read, not the caller's.
                self.log.warning(f"Refused: request_id={reply.request_id}, status_code={reply.status_code}, reason={reply.error}")
                raise ToolError(self.UNAVAILABLE_MESSAGE)
            if reply.is_error or reply.result is None:
                self.log.error(f"Agent reply failed: request_id={reply.request_id}, status_code={reply.status_code}, error={reply.error}")
                raise ToolError(self.ERROR_MESSAGE)

            if reply.media_type:
                meta: dict[str, Any] = {"media_type": reply.media_type}
                if isinstance(reply.result, dict):
                    return ToolResult(structured_content=reply.result, meta=meta)
                meta["fastmcp"] = {"wrap_result": True}
                return ToolResult(structured_content={"result": reply.result}, meta=meta)
            return reply.result

        @staticmethod
        async def _retain_credential(principal: Principal, access_token: AccessToken | None) -> Principal:
            """
            Keeps the call's token for the run it starts, when ``identity.credentials`` is configured.

            :param principal: The call's principal.
            :param access_token: The access token FastMCP verified for this call, which carries the token.
            :return: The principal with a ``credential_ref``, or as it came when nothing is kept.
            """
            if principal.is_anonymous or access_token is None:
                return principal
            from ...identity.credential.manager import CredentialManager

            manager = CredentialManager.get()
            return principal if manager is None else await manager.retain(principal, access_token.token)

        @staticmethod
        async def _release_credential(principal: Principal) -> None:
            """Deletes the call's token once its reply is in. Never raises."""
            if not principal.credential_ref:
                return
            from ...identity.credential.manager import CredentialManager

            await asyncio.to_thread(CredentialManager.release_for, principal)

    @classmethod
    def get_client(cls) -> "RestHandler":
        """The surface's one queue client, built on first use: a ``RestHandler``, whose ``request`` is
        the REST chat route's "enqueue, then wait" without the HTTP.

        Imported here, not at module scope: ``api`` reaches ``pipeline`` lazily, as ``RESTAPI.run`` does.
        """
        if cls._client is None:
            from ...pipeline.request_handler import RestHandler

            cls._client = RestHandler()
        return cls._client

    @staticmethod
    def _visible_to_the_caller(descriptor: AgentDescriptor) -> AuthCheck:
        """The check an agent's tool is registered with: whether the caller of a request may see the agent.

        FastMCP runs it for every listing and every call, with that request's access token. A tool
        whose check fails is left out of ``tools/list`` and a call to it is answered like a call to
        a tool that does not exist, so a hidden agent is not told apart from an unknown one. Without
        an ``authorization`` block the check admits everyone. The access gate is read at each
        request, and a check that raises is FastMCP's denial: an authorizer that cannot answer
        hides the tool.

        Visibility is what lists a tool, not a level: an agent the caller sees and may not use is
        listed, and calling it is refused by the precheck before the queue (``Agent not available``).

        :param descriptor: The agent's descriptor as it was when the tool was registered.
        :return: The check to pass as the tool's ``auth``.
        """

        async def visible(context: AuthContext) -> bool:
            gate = Runtime.access_gate()
            if gate is None:
                return True
            return await gate.visible_async(AKAccessToken.principal_of(context.token), descriptor)

        return visible

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
            # None without an identity block: MCP stays open and every call runs anonymous.
            cls._fastmcp = FastMCP("Agent Kernel FastMCP Instance", auth=AKMCPAuthProvider.from_config())
        if AKConfig.get().mcp.expose_agents:
            # From the registry's descriptors, not the agents this process hosts: a tool needs only the agent's
            # id and catalog text, so a process over a shared registry exposes agents that run elsewhere. In id
            # order, so every process lists the same tools whatever order its registry answers in.
            descriptors = Runtime.current().registry.descriptors()
            for descriptor in sorted(descriptors, key=lambda descriptor: descriptor.id):
                if not descriptor.exposed_on("mcp"):
                    continue
                if not descriptor.description:
                    cls._log.warning(
                        f"Agent '{descriptor.id}' is exposed as an MCP tool with no description of its own, and a client chooses a "
                        f"tool by that text; declare one with Module.describe(agent, description=...) or "
                        f"registry.agents.{descriptor.id}.description"
                    )
                cls._executors[descriptor.id] = cls.Executor(descriptor.id)
                cls._fastmcp.tool(
                    cls._executors[descriptor.id].execute,
                    name=descriptor.id,
                    # Always given: left out, FastMCP would publish the executor's own docstring.
                    description=descriptor.description or cls.UNDESCRIBED_TOOL_TEXT.format(agent=descriptor.id),
                    auth=cls._visible_to_the_caller(descriptor),
                )
            if descriptors and not cls._executors:
                # Agents exist and none became a tool: without this the tool list just has no agents in it.
                # A registry that knows no agent at all is the host's to report (IOHandler).
                cls._log.warning(
                    f"MCP agent tools are enabled (mcp.expose_agents) but no agent became a tool: none of the {len(descriptors)} "
                    f"agents the registry knows is exposed on mcp. An agent is on every surface unless its descriptor's surfaces "
                    f"leave one out; add mcp to registry.agents.<id>.surfaces (or Module.describe(agent, surfaces=[...])) for "
                    f"the agents MCP should expose, or set mcp.expose_agents to false"
                )
        cls._built = True
