"""Authorizer Lambda: bearer-token auth for the chat route.

The chat route is authenticated through the identity provider named in config.yaml (the static provider here, its one
credential resolved from the DEMO_AUTH_TOKEN environment variable that deploy/main.tf passes in; swap it for an `oidc`,
`cognito`, `entra` or `firebase` block to validate real tokens, after adding `auth` to the `authorizer` extra in
pyproject.toml, since those providers need PyJWT, cryptography and httpx).

The A2A and MCP routes are not behind this authorizer: the request-handler Lambda authenticates them itself with the same
provider (see config.yaml), as the ECS deployment does.
"""

from agentkernel.aws import APIGatewayAuthorizer

handler = APIGatewayAuthorizer().handle
