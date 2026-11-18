"""Authorizer Lambda: bearer-token auth for the chat route, and a bypass for Slack's webhook.

The chat route is authenticated through the identity provider named in config.yaml (the static
provider here, its one credential resolved from the DEMO_AUTH_TOKEN environment variable that
deploy/main.tf passes in; swap it for an `oidc`, `cognito`, `entra` or `firebase` block to validate
real tokens, after adding `auth` to the `authorizer` extra in pyproject.toml, since those providers
need PyJWT, cryptography and httpx).

Slack sends no bearer token: it signs the body, and the authorizer event carries no body. So the
bypass lets `POST /<api_base_path>/<api_version>/slack/events` through by method and path alone,
never by header, and the Slack adapter's signature check in the request-handler Lambda is the real
authentication.

The bypass only gets a say with authorizer caching off (`result_ttl_in_seconds = 0` in
deploy/main.tf): with a TTL, API Gateway answers a request that has no Authorization header with
401 before calling this Lambda.
"""

from agentkernel.aws import APIGatewayAuthorizer
from agentkernel.integration.adapter import WebhookRouteMatcher

handler = APIGatewayAuthorizer(bypass=WebhookRouteMatcher.for_integrations("slack")).handle
