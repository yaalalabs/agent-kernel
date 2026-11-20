from collections.abc import Mapping
from typing import Any

from .....integration.adapter.route_matcher import WebhookRouteMatcher


class ProtocolPaths:
    """The paths the request Lambda hosts for the agent protocols, A2A and MCP (#932).

    The one definition of the hosted prefixes, as ``BUILTIN_WEBHOOK_ROUTES`` is for the webhooks. This
    module imports no FastAPI, so the API Gateway authorizer and the host can both read it.

    Paths here are *app paths*: with the ``/<API_BASE_PATH>/<API_VERSION>`` prefix already removed,
    as the app serves them (``/a2a/<agent>/message:send``, ``/mcp``).
    """

    A2A_PREFIX = "/a2a"
    MCP_PREFIX = "/mcp"
    PREFIXES = (A2A_PREFIX, MCP_PREFIX)
    # The two A2A routes that are public by design: the catalog, and each agent's card.
    CATALOG_PATH = "/a2a/catalog"
    AGENT_CARD_SUFFIX = "/.well-known/agent-card.json"

    # The (path, method) pairs the application registers with ``Lambda.register``: the API Gateway resource templates the
    # Terraform ``proxy_routes`` create (``/a2a``, ``/a2a/{proxy+}``, ``/mcp``, ``/mcp/{proxy+}``), each for the methods
    # the protocols use. ``{proxy+}`` stays literal: the router looks a route up by the template API Gateway matched.
    ROUTES = (
        ("/a2a", "GET"),
        ("/a2a", "POST"),
        ("/a2a", "DELETE"),
        ("/a2a/{proxy+}", "GET"),
        ("/a2a/{proxy+}", "POST"),
        ("/a2a/{proxy+}", "DELETE"),
        ("/mcp", "GET"),
        ("/mcp", "POST"),
        ("/mcp", "DELETE"),
        ("/mcp/{proxy+}", "GET"),
        ("/mcp/{proxy+}", "POST"),
        ("/mcp/{proxy+}", "DELETE"),
    )

    @classmethod
    def matches(cls, app_path: str) -> bool:
        """Whether an app path belongs to a hosted protocol: the prefix itself, or the prefix and a ``/``.

        ``/a2ax`` is not ``/a2a``: a prefix must end at a path segment.

        :param app_path: The request path with the base path removed.
        :return: True when the A2A or MCP routes serve it.
        """
        return any(app_path == prefix or app_path.startswith(f"{prefix}/") for prefix in cls.PREFIXES)


class ProtocolRouteMatcher(WebhookRouteMatcher):
    """The ``APIGatewayAuthorizer`` bypass for the A2A and MCP routes (#932).

    The request-handler Lambda serves A2A and MCP behind the same API Gateway authorizer as the chat route. Three things
    must get past it without a token, and nothing else may:

    - ``/mcp`` and everything under it, any method: MCP's 401 has to carry the client's login metadata (RFC 9728), which
      the authorizer cannot send, and FastMCP refuses a missing or bad token itself. Returns ``"mcp"``.
    - ``GET /a2a/catalog`` and ``GET /a2a/<agent>/.well-known/agent-card.json``: public by design. Returns ``"a2a"``.

    Every other ``/a2a/...`` route stays behind the authorizer: the app lets a call with no token through as anonymous, so
    the authorizer is what keeps an unauthenticated caller away from the agent.

    Like its parent it matches the method and the path and nothing else: the event has no body, and a header test could be
    spoofed onto a protected request. It derives the base path as the parent does, so with ``API_BASE_PATH`` or
    ``API_VERSION`` unset the gateway path keeps its prefix, matches nothing, and the request goes to the identity provider.
    It does not normalize the request path, so ``/a2a/catalog/`` is not the catalog and is not let through. Only a path
    that carries a ``..`` segment is refused outright. It keeps no state and is safe to share.

    The bypass runs only with authorizer caching off (``result_ttl_in_seconds = 0``), which applies to every route.

    It subclasses ``WebhookRouteMatcher`` because it shares that matcher's base-path rule and its bypass contract
    (``APIGatewayAuthorizer`` calls it with the authorizer event and reads the name it returns), and only the route test is
    its own. The inherited ``for_integrations`` builds a matcher from webhook routes, which this one has none of, so it is
    disabled on purpose and raises ``TypeError``.
    """

    MCP = "mcp"
    A2A = "a2a"

    def __init__(self, base_path: str | None = None):
        """
        :param base_path: The prefix API Gateway serves the routes under, e.g. "/api/v1". None derives it from
            API_BASE_PATH and API_VERSION, which the ak-serverless module sets on the authorizer Lambda.
        """
        super().__init__([], base_path=base_path)

    @classmethod
    def for_integrations(cls, *names: str, base_path: str | None = None) -> "WebhookRouteMatcher":
        """Not applicable: this matcher is for the A2A and MCP routes, not for messaging integrations.

        :raises TypeError: Always. Use ``ProtocolRouteMatcher()``, or ``WebhookRouteMatcher.for_integrations`` for webhooks.
        """
        raise TypeError("ProtocolRouteMatcher matches the A2A and MCP routes: build it with ProtocolRouteMatcher()")

    def __call__(self, event: Mapping[str, Any]) -> str | None:
        """``"mcp"`` or ``"a2a"`` for a route that needs no token, else None (the authorizer decides).

        The method is upper-cased and the base path removed with ``str.removeprefix``, as the router does. No header or
        query parameter is read.
        """
        method = str(event.get("httpMethod") or "").upper()
        path = str(event.get("path") or "").removeprefix(self._base_path)
        if ".." in path.split("/"):
            return None
        if path == ProtocolPaths.MCP_PREFIX or path.startswith(f"{ProtocolPaths.MCP_PREFIX}/"):
            return self.MCP
        if method == "GET" and self._is_public_a2a(path):
            return self.A2A
        return None

    @staticmethod
    def _is_public_a2a(path: str) -> bool:
        """The catalog, or one agent's card: ``/a2a/<agent>/.well-known/agent-card.json`` with one non-empty segment for the agent."""
        if path == ProtocolPaths.CATALOG_PATH:
            return True
        agent_prefix = f"{ProtocolPaths.A2A_PREFIX}/"
        if not (path.startswith(agent_prefix) and path.endswith(ProtocolPaths.AGENT_CARD_SUFFIX)):
            return False
        agent = path[len(agent_prefix) : -len(ProtocolPaths.AGENT_CARD_SUFFIX)]
        return bool(agent) and "/" not in agent
