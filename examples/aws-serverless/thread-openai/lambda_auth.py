"""Authorizer Lambda: authenticates the bearer token of every request through the identity provider.

There is no code to write. config.yaml names the provider (the static provider here, its two
credentials resolved from the ALICE_TOKEN and BOB_TOKEN environment variables deploy/main.tf passes
in; an `oidc` block validates Auth0, Keycloak or Okta tokens instead). An accepted token yields an
Allow policy whose context carries the principal; the request handler assigns it to the chat body,
and LambdaThreadHost scopes the read routes to it.
"""

from agentkernel.aws import APIGatewayAuthorizer

handler = APIGatewayAuthorizer().handle
