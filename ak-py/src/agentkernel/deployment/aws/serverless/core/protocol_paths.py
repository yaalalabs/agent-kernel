class ProtocolPaths:
    """The paths the request Lambda hosts for the agent protocols, A2A and MCP (#932).

    The one definition of the hosted prefixes, as ``BUILTIN_WEBHOOK_ROUTES`` is for the webhooks. It
    imports nothing, so the API Gateway authorizer and the host can both read it without FastAPI.

    Paths here are *app paths*: with the ``/<API_BASE_PATH>/<API_VERSION>`` prefix already removed,
    as the app serves them (``/a2a/<agent>/message:send``, ``/mcp``).
    """

    PREFIXES = ("/a2a", "/mcp")

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
