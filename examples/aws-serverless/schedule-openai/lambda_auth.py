"""Authorizer Lambda: authenticates the bearer token of every request through the identity provider.

A scheduled task belongs to the principal whose request created it, so every route of this example
needs an authenticated caller: the chat route to register a task, the custom management routes to
read and change the caller's own. There is no code to write. config.yaml names the provider (the
static provider here, its one credential resolved from the DEMO_AUTH_TOKEN environment variable
deploy/main.tf passes in; an `oidc` block validates Auth0, Keycloak or Okta tokens instead). An
accepted token yields an Allow policy whose context carries the principal; the request-handler
Lambda puts it on the chat body and `Lambda.principal(event)` reads it in the custom routes.
"""

from agentkernel.aws import APIGatewayAuthorizer

handler = APIGatewayAuthorizer().handle
