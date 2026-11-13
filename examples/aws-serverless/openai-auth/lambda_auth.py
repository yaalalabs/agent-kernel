"""Authorizer Lambda: authenticates the bearer token of every request through the identity provider.

There is no code to write. `config.yaml` names the provider (`identity.provider`): the static
provider here, with its one credential resolved from the DEMO_AUTH_TOKEN environment variable that
deploy/main.tf passes in, or an `oidc` block for Auth0, Keycloak, Okta or any other OIDC issuer (see
the README). An accepted token yields an Allow policy whose context carries the principal, which the
request-handler Lambda puts on the request; anything else is a Deny.
"""

from agentkernel.aws import APIGatewayAuthorizer

handler = APIGatewayAuthorizer().handle
