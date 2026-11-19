"""Authorizer Lambda: bearer-token auth for every route, except the three things that need no token.

The chat route and every A2A message or task route are authenticated through the identity provider named in
config.yaml (the static provider here, its one credential resolved from the DEMO_AUTH_TOKEN environment variable that
deploy/main.tf passes in; swap it for an `oidc`, `cognito`, `entra` or `firebase` block to validate real tokens, after
adding `auth` to the `authorizer` extra in pyproject.toml, since those providers need PyJWT, cryptography and httpx).

ProtocolRouteMatcher lets these through by method and path alone, never by header:

- `/mcp` and everything under it, any method: MCP's 401 has to carry the client's login metadata, which this
  authorizer cannot send, and FastMCP refuses a missing or bad token itself, in the request-handler Lambda;
- `GET /a2a/catalog` and `GET /a2a/<agent>/.well-known/agent-card.json`: public by design.

Every other A2A route stays behind this authorizer, and that matters: the A2A app runs a call that carries no token as
the anonymous principal, so this authorizer is what keeps an unauthenticated caller away from the agent.

The bypass only gets a say with authorizer caching off (`result_ttl_in_seconds = 0` in deploy/main.tf): with a TTL,
API Gateway answers a request that has no Authorization header with 401 before calling this Lambda.
"""

from agentkernel.aws import APIGatewayAuthorizer, ProtocolRouteMatcher

handler = APIGatewayAuthorizer(bypass=ProtocolRouteMatcher()).handle
