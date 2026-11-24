# Agent Kernel A2A and MCP on AWS Lambda

This package serves an agent over **A2A** (other agents call it) and **MCP** (AI tools call it) from AWS Lambda, next to
the usual chat route. A2A and MCP reach the agent through the same queue pipeline as chat: the request-handler Lambda
enqueues the call, the agent-runner Lambda runs the agent, and the reply is read back from the response store.

It is the serverless counterpart of [`examples/k8s/openai-queue-mode`](../../k8s/openai-queue-mode), which serves the same
two protocols from the pipeline's FastAPI server.

## Architecture Overview

```
A2A / MCP client --> API Gateway (no authorizer on these routes)
   /a2a/...  /mcp/...                     |
                                          v
                               Request-handler Lambda (authenticates the bearer token)
                               Lambda.register -> LambdaProtocolHost -> the A2A routes + the MCP mount
                               (builds the cards and tools from the agents registered in this Lambda)
                                          |  enqueue, protocol = a2a | mcp
                                          v
                Input Queue --> Agent-runner Lambda --> Output Queue --> Response-handler Lambda
                                                                                |
                                  the request handler reads the reply  <--  response store
```

- **Request-handler Lambda**: the chat route, plus every `/a2a` and `/mcp` call. `lambda_request_handler.py` registers the
  agents, builds `LambdaProtocolHost()`, and registers its `handle` for every route in `ProtocolPaths.ROUTES`. The host runs
  the same FastAPI app the pipeline's `IOHandler` serves, so the A2A and MCP code is not copied.
- **Agent-runner Lambda**: runs the agent. Nothing in it mentions A2A or MCP.
- **Response-handler Lambda**: stores each reply for the caller waiting on it.
- **Authorizer Lambda**: `lambda_auth.py`, for the chat route only; A2A and MCP are authenticated in the request handler.

The request handler imports the agents because the A2A cards and MCP tools are built from the agent registry when the host
is constructed (the default in-memory registry). That is why it deploys as a container image with 2 GB of memory, like the
agent runner, and why it carries the OpenAI Agents SDK. It never runs a model, and it holds no session: the agent runner
owns them in DynamoDB. Registering an agent builds the runtime's session store, and in queue mode the Terraform module gives
the request handler no session table, so `deploy/main.tf` sets `AK_SESSION__TYPE=in_memory` on it.

## Who may call what

| Route | Authenticated by | No token |
|---|---|---|
| Chat (`POST /api/v1/chat`) | the authorizer | 401 / 403 |
| A2A (every `/a2a/...` route) | the request-handler Lambda, through `config.yaml` `identity` | **runs as the anonymous principal** (200), as on ECS |
| MCP (`/mcp`) | FastMCP, in the request-handler Lambda | **401 from FastMCP** |

The A2A and MCP routes carry **no API Gateway authorizer**, the same as ECS. The request-handler Lambda authenticates the bearer
token itself, so **the `config.yaml` that Lambda carries must have the `identity` block** (this example's does). Without it every
caller is anonymous. A call that presents a bad token gets a 401 from the app. A2A accepts a call with no token as the anonymous
principal; requiring a token on every A2A call is an Open Agent Kernel feature for both deployments, not a Lambda setting.

## Declare the protocols in two places

They must agree:

| Where | What | Symptom when it is missing |
|---|---|---|
| `lambda_request_handler.py` | `Lambda.register(path, method=method)(protocol.handle)` for each `ProtocolPaths.ROUTES` | 500: the router has no route for the call |
| `deploy/main.tf` | `enable_a2a_server = true`, `enable_mcp_server = true` | API Gateway answers 403 before any Lambda runs: there is no `/a2a` or `/mcp` route |

## The public URL, and the second apply

The agent card advertises `a2a.url`, and MCP names `mcp.url` in its login metadata. Both must be the API's **public URL**,
stage and base path included, for example `https://<id>.execute-api.<region>.amazonaws.com/agents/api/v1/a2a`. It contains
the API's id, which exists only after the API does, so `deploy.sh` runs `terraform apply` twice: the second apply passes the
first one's `public_base_url` output to the request handler as `AK_A2A__URL` and `AK_MCP__URL`. It changes that Lambda's
environment only. The value is kept in `deploy/public_url.auto.tfvars` (not committed), so a later plain `terraform apply`
keeps it. With a custom domain you know the URL up front: set `public_base_url` yourself.

Until `a2a.url` and `mcp.url` are public (they default to `localhost`), the agent card advertises an address no client can reach. Nothing checks them.

## Build

```bash
./build.sh          # from PyPI
./build.sh local    # from ../../../ak-py/dist
```

## Deploy

Store your OpenAI key in SSM Parameter Store, where `<prefix>` is `prefix` in `deploy/terraform.tfvars`:

```bash
aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" --type SecureString --value "$OPENAI_API_KEY" --overwrite
```

The deployment sets `ssm_enabled = true`, which grants the Lambdas `ssm:GetParameter` on `/ak/<prefix>/*` and injects
`AK_SECRET__PREFIX`; `config.yaml` selects the `aws_ssm` secret provider. The agent runner resolves `OPENAI_API_KEY` from it.

Then set `demo_auth_token`, `vpc_id` and `private_subnet_ids` (in `deploy/terraform.tfvars` or as `TF_VAR_*` variables), and
deploy. Docker must be running: the request handler and the agent runner deploy as container images.

```bash
cd deploy
./deploy.sh         # packages from PyPI, Terraform module from the registry
./deploy.sh local   # packages from ../../../ak-py/dist, Terraform module from this checkout
```

> `enable_a2a_server` and `enable_mcp_server` ship with the `ak-serverless` module release after 0.10.2. Until it is
> published the registry module has no such input, so deploy with `./deploy.sh local`: it writes `deploy/zz_local_module_override.tf`
> (not committed), which points the module at `../../../../ak-deployment/ak-aws/serverless` for that deployment.

`demo_auth_token` is the one credential the static identity provider in `config.yaml` accepts. It reaches the authorizer and
the request-handler Lambda as an environment variable (this is a demo; use `oidc`, `cognito`, `entra` or `firebase` for real
tokens, and keep the secret in SSM). `../openai-auth` shows the Auth0 block, and the
[Identity and Access](https://kernel.yaala.ai/docs/next/advanced/identity-and-access) page covers every provider.

## Test on the real deployment

`lambda_test.py` runs against the stack. It needs the chat URL and the token the stack was deployed with:

```bash
cd deploy
export AK_TEST_ENDPOINT=$(terraform output -raw agent_invoke_url)
export AK_TEST_TOKEN=<the demo_auth_token you deployed with>
cd ..
./build.sh
uv run --no-sync pytest -s lambda_test.py
```

With `-s` every test prints the real status it got, which is the record that the design holds on AWS:

| Test | Proves |
|---|---|
| two A2A messages, one session | A2A works through the queue and the session holds across Lambda invocations |
| two MCP tool calls, one session | the same for MCP |
| agent card with no token | 200, and the card advertises the public `a2a.url` |
| catalog with no token | 200 |
| A2A `message:send` with no token | runs as the anonymous principal (200), as on ECS |
| A2A `message:send` / task route with a wrong token | the app's own 401 (not the gateway's) |
| `/mcp` with no token / a wrong token | FastMCP's own 401 (not the gateway's) |
| `/mcp` with a valid token | the agent is listed as a tool, and a call works |
| `GET /mcp` | 405: stateless MCP has no server push |

## Limits

- **29 seconds.** API Gateway stops waiting at 29 s, and a call waits for the agent's reply. `config.yaml` sets
  `retry_count: 10` and `delay: 2`, a wait of `(retry_count - 1) x delay` = 18 s, and the request handler refuses to start
  with a longer one. An agent run plus queue time over that fails with the executors' timeout error.
- **A2A tasks.** `tasks/get` across Lambda instances is not supported (nor on ECS): both `a2a.task_store_type` values keep tasks in the memory of one process.
- **Streaming** (`message:stream`, streamed MCP replies) is not supported on Lambda.
- **MCP login metadata** (RFC 9728, with an OpenID identity provider) is served at the root of the host, a path neither this
  deployment nor ECS routes, so that OAuth discovery is not supported. The `static` provider used here is bearer-only and is
  not affected.
- **Memory.** The request handler loads the agents, so give it far more than the 128 MB default.

## Cleanup

```bash
cd deploy
terraform destroy
aws ssm delete-parameter --name "/ak/<prefix>/openai_api_key"
```
