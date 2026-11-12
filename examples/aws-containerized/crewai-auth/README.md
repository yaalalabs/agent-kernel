# Agent Kernel running CrewAI based agents with Authentication in AWS Containered (ECS)

This package contains a demo of Agent Kernel running agents built with CrewAI with authentication, running them in a containered configuration using AWS ECS.

## Authentication

Authentication is configuration, not code. The `identity` block in `config.yaml` names the identity
provider every REST route authenticates the bearer token with; the resulting principal travels with
the request. This example uses the `static` provider with one credential mapped to the principal
`demo-user`. The credential's value is not in the file: the key `DEMO_AUTH_TOKEN` names a secret the
secret capability resolves at startup, and Terraform passes it to the container as an environment
variable from `var.demo_auth_token`.

```bash
curl -X POST "$AGENT_INVOKE_URL" \
  -H "Authorization: Bearer <the demo_auth_token value>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2 + 2?", "session_id": "ses-1", "agent": "math"}'
```

A token, if sent, must be valid: one the provider refuses is a 401 with the generic detail
`Unauthorized` (the provider's reason stays in the logs). Without one, a request runs as the anonymous
principal, on the chat route and on the custom `/custom/version` route alike: chat stays open to
anonymous callers until the access gate lands, so do not rely on the token to keep callers out yet.
See [Identity and Access](https://kernel.yaala.ai/docs/next/advanced/identity-and-access). To
validate real tokens, swap the provider for `oidc` (Auth0, Keycloak, Okta or any other OIDC issuer), `cognito`,
`entra` or `firebase`; [`examples/aws-serverless/openai-auth`](../../aws-serverless/openai-auth/README.md)
spells out an Auth0 block, and the same block works here unchanged.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS ECS running the Agent Kernel implementation.
- API Gateway endpoint for the ECS service.

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.

## Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    export TF_VAR_demo_auth_token=<any secret string: the bearer token clients send>
    ```

2. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```
