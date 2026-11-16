# Agent Kernel running OpenAI Agents SDK with Authentication in AWS Serverless (Lambda)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK with authentication support, running them in a serverless configuration using AWS Lambda.

## Authentication

Authentication is configuration, not code. `lambda_auth.py` is one line, `APIGatewayAuthorizer().handle`:
the API Gateway authorizer Lambda authenticates every request's bearer token through the identity
provider named by the `identity` block in `config.yaml`, and an accepted token yields an Allow policy
whose context carries the principal (subject, groups, claims). The request-handler Lambda puts that
principal on the request, so the agent, the tools and the hooks know who is calling. A refused,
expired or malformed token gets a 401 (API Gateway's answer when the authorizer raises `Unauthorized`,
the status an OAuth client refreshes its token on); a request with no token is a Deny (403). Either way
the provider's reason stays in the authorizer's logs and nothing is in the response.

### The static provider (default)

`config.yaml` ships with the `static` provider: one credential mapped to the principal `demo-user`. The
credential's value is not in the file. The key `DEMO_AUTH_TOKEN` names a secret the secret capability
resolves when the authorizer starts, and `deploy/main.tf` passes it to that Lambda as an environment
variable from `var.demo_auth_token`. Clients send the same value as the bearer token:

```bash
curl -X POST "$(terraform output -raw agent_invoke_url)" \
  -H "Authorization: Bearer <the demo_auth_token value>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2 + 2?", "session_id": "ses-1", "agent": "triage"}'
```

### Auth0 (or any OIDC issuer)

Auth0 is served by the `oidc` provider; so are Keycloak, Okta and any other OpenID Connect issuer
(Cognito, Entra ID and Firebase have providers of their own, `cognito`, `entra` and `firebase`). Replace
the `identity` block in `config.yaml` with the tenant's issuer and the API identifier, and the authorizer
validates the token's signature against the tenant's JWKS, its issuer, audience and expiry:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<tenant>.<region>.auth0.com/   # or the custom domain; trailing slash included, as Auth0 issues it
    audience: <the API identifier of your Auth0 API>
    claims:
      groups: https://<your namespace>/roles       # the namespaced claim an Auth0 Action sets; omit if you set none
```

The principal's `subject` is the token's `sub`, its `namespace` the issuer, its `groups` the claim above,
and every other claim (`permissions`, `org_id`, ...) arrives in `claims` for the role mapper and the tools.
No variable is needed for this block, so `demo_auth_token` can be left at any value. The authorizer
package already carries the `auth` extra (PyJWT, cryptography and httpx), which `oidc` needs.

Get a token to test with from the tenant's token endpoint, for example through the client-credentials
flow of a machine-to-machine application authorised for the API:

```bash
curl -s --request POST https://<tenant>.<region>.auth0.com/oauth/token \
  -H 'content-type: application/json' \
  -d '{"client_id": "...", "client_secret": "...", "audience": "<API identifier>", "grant_type": "client_credentials"}'
```

and send its `access_token` as the bearer token.

## Deployed Resources

This demo deploys the following AWS resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- Redis Cluster: Session storage (shared with openai example)
- VPC: Private networking for Lambda functions (shared with openai example)

## Prerequisites

- AWS CLI configured with appropriate credentials.
- Terraform (`1.9.5` or higher) installed.
- The openai example must be deployed first to create the shared Redis cluster and VPC resources

## Deployment Steps

1. Deploy the openai example first to create the shared infrastructure:
    ```bash
    cd ../openai/deploy && ./deploy.sh
    ```

2. Get the VPC ID, private subnet IDs, and request handler security group ID from the openai deployment:
    ```bash
    cd ../openai/deploy && terraform output vpc_id
    cd ../openai/deploy && terraform output private_subnet_ids
    cd ../openai/deploy && terraform output request_handler_security_group_id
    ```

3. Store the OpenAI API key in SSM Parameter Store (`<prefix>` is `prefix` in `deploy/terraform.tfvars`) and configure the deployment:
    ```bash
    aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
        --type SecureString --value "$OPENAI_API_KEY" --overwrite
    export TF_VAR_demo_auth_token=<any secret string: the bearer token clients send>
    export TF_VAR_vpc_id=<VPC_ID_FROM_OPENAI>
    export TF_VAR_private_subnet_ids='["<SUBNET_ID_1>", "<SUBNET_ID_2>"]'
    export TF_VAR_request_handler_security_group_id=<SG_FROM_OPENAI> # optional, reuses the openai deployment's security group
    ```
    The deployment sets `ssm_enabled = true` and `config.yaml` selects the `aws_ssm` secret provider, so the app reads the key from SSM at startup; no secret passes through Terraform.

4. Navigate to the deployment directory and run the deployment script:
    ```bash
    cd deploy && ./deploy.sh #./deploy.sh local if dependencies are built locally
    ```

## Running the tests

```bash
export AK_TEST_ENDPOINT="$(cd deploy && terraform output -raw agent_invoke_url)"
export AK_TEST_TOKEN=<the demo_auth_token value, or an Auth0 access token with the oidc block>
uv run pytest lambda_test.py
```
