# Agent Kernel A2A and MCP on AWS Lambda

This package serves an agent over **A2A** (other agents call it) and **MCP** (AI tools call it) from AWS Lambda, next to
the usual chat route. A2A and MCP reach the agent through the same queue pipeline as chat: the request-handler Lambda
enqueues the call, the agent-runner Lambda runs the agent, and the reply is read back from the response store.

It is the serverless counterpart of [`examples/k8s/openai-queue-mode`](../../k8s/openai-queue-mode), which serves the same
two protocols from the pipeline's FastAPI server.

## Architecture Overview

```
A2A / MCP client --> API Gateway --> Authorizer Lambda
   /a2a/...  /mcp/...                 (bearer token for chat and A2A message routes;
                                       lets through /mcp, the agent cards and the catalog)
                                          |
                                          v
                               Request-handler Lambda
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
- **Authorizer Lambda**: `lambda_auth.py`, below.

The request handler imports the agents because the A2A cards and MCP tools are built from the agent registry when the host
is constructed (the default in-memory registry). That is why it deploys as a container image with 2 GB of memory, like the
agent runner, and why it carries the OpenAI Agents SDK. It never runs a model, and it holds no session: the agent runner
owns them in DynamoDB. Registering an agent builds the runtime's session store, and in queue mode the Terraform module gives
the request handler no session table, so `deploy/main.tf` sets `AK_SESSION__TYPE=in_memory` on it.

## Who may call what

| Route | Authenticated by | No token |
|---|---|---|
| Chat (`POST /api/v1/chat`) | the authorizer | 401 / 403 |
| A2A `message:send`, tasks, every other `/a2a/...` route | the authorizer | **401 / 403** |
| A2A agent card and catalog (`GET`) | nobody: public by design | **200** |
| MCP (`/mcp`) | FastMCP, in the request-handler Lambda | **401 from FastMCP** |

`ProtocolRouteMatcher` in `lambda_auth.py` lets `/mcp`, the agent cards and the catalog past the authorizer by method and
path, never by header. Every other A2A route has to stay behind it: the A2A app runs a call that carries no token as the
anonymous principal, so the authorizer is what keeps an unauthenticated caller away from the agent. MCP is let through
because its 401 has to carry the client's login metadata, which an authorizer cannot send; FastMCP refuses a missing or bad
token itself, using the same identity provider.

**The authorizer's cache must be off** (`result_ttl_in_seconds = 0`, set in `deploy/main.tf`). With a TTL, API Gateway answers
a request that has no `Authorization` header with 401 before the authorizer runs, so the bypass never gets a say. The cost
is one authorizer call per request, chat included.

## Declare the protocols in three places

They must agree:

| Where | What | Symptom when it is missing |
|---|---|---|
| `lambda_request_handler.py` | `Lambda.register(path, method=method)(protocol.handle)` for each `ProtocolPaths.ROUTES` | 500: the router has no route for the call |
| `deploy/main.tf` | `enable_a2a_server = true`, `enable_mcp_server = true` | API Gateway answers 403 before any Lambda runs: there is no `/a2a` or `/mcp` route |
| `lambda_auth.py` | `ProtocolRouteMatcher()` | MCP and the public cards are refused with 401 / 403 by the authorizer |

## The public URL, and the second apply

The agent card advertises `a2a.url`, and MCP names `mcp.url` in its login metadata. Both must be the API's **public URL**,
stage and base path included, for example `https://<id>.execute-api.<region>.amazonaws.com/agents/api/v1/a2a`. It contains
the API's id, which exists only after the API does, so `deploy.sh` runs `terraform apply` twice: the second apply passes the
first one's `public_base_url` output to the request handler as `AK_A2A__URL` and `AK_MCP__URL`. It changes that Lambda's
environment only. The value is kept in `deploy/public_url.auto.tfvars` (not committed), so a later plain `terraform apply`
keeps it. With a custom domain you know the URL up front: set `public_base_url` yourself.

Until `a2a.url` and `mcp.url` are public, the request handler refuses to start (they default to `localhost`), and the first
call fails with the guard's message in the CloudWatch log.

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

> `enable_a2a_server` and `enable_mcp_server` ship with the `ak-serverless` module release after 0.10.1. Until it is
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
| A2A `message:send` with no token / a wrong token | the **authorizer** refuses it (401 or 403) |
| A2A task route with no token | every non-public A2A route needs a token |
| `/mcp` with no token / a wrong token | FastMCP's own 401 (not the gateway's) |
| `/mcp` with a valid token | the agent is listed as a tool, and a call works |
| `GET /mcp` | 405: stateless MCP has no server push |

## Limits

- **29 seconds.** API Gateway stops waiting at 29 s, and a call waits for the agent's reply. `config.yaml` sets
  `retry_count: 10` and `delay: 2`, a wait of `(retry_count - 1) x delay` = 18 s, and the request handler refuses to start
  with a longer one. An agent run plus queue time over that fails with the executors' timeout error.
- **No task store.** `message:send` returns a plain message, so `tasks/{id}` across Lambda instances is out of scope.
- **Streaming** (`message:stream`, streamed MCP replies) is not supported on Lambda.
- **MCP login metadata** (OAuth, with an OpenID identity provider) needs a custom domain mapped at the root of the host: a
  default `execute-api` URL carries a stage prefix and cannot serve it. The `static` provider used here is bearer-only and is
  not affected.
- **Memory.** The request handler loads the agents, so give it far more than the 128 MB default.

## Cleanup

```bash
cd deploy
terraform destroy
aws ssm delete-parameter --name "/ak/<prefix>/openai_api_key"
```
