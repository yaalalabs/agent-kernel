# Agent Kernel Conversation Threads on AWS Lambda

This package deploys an OpenAI agent on AWS Lambda with Conversation Thread Support. The chat route
records each user message in a thread before it enqueues the request, the agent-runner Lambda
records the reply, and two read routes serve the threads back.

It is the serverless counterpart of [`examples/api/thread-openai`](../../api/thread-openai), which
mounts the same thread handler on the FastAPI server.

## Architecture Overview

```
Client --POST /api/v1/chat (bearer token)--> API Gateway --> Authorizer
                                                     |
                                                     v
                                          Request-handler Lambda
                              LambdaThreadHost -> ThreadRequestHandler.prepare_for_queue
                              (validate, record the user message, mark the request)
                                                     |
                                              thread=1 attribute
                                                     v
        Input Queue --> Agent-runner Lambda --> Output Queue --> Response-handler Lambda
                        (runs the agent, then records             (response store, for the
                         the reply in the thread)                  chat route's wait)

Client --GET /api/v1/threads[/{session_id}]--> API Gateway --> Authorizer --> Request-handler Lambda
                              Lambda.register -> LambdaThreadHost.list_threads / get_thread
```

- **Request-handler Lambda**: `LambdaThreadHost(ThreadRequestHandler())` takes over the built-in
  chat route; `@Lambda.register` functions delegate the two read routes to it. It does not
  import `agent.py`: in queue mode the agents live in the agent-runner Lambda only.
- **Authorizer Lambda**: `APIGatewayAuthorizer().handle`, authenticating the bearer token through
  the `identity` block in `config.yaml` and passing the principal on. See below.
- **Agent-runner Lambda**: runs the agent and records the reply of every marked request.
- **Response-handler Lambda**: writes the reply to the response store, unchanged.

Both the request handler and the agent runner read the same `thread` block in `config.yaml`, which
must name a shared store (`dynamodb` here; `in_memory` fails the request handler's cold start).

## Who owns a thread

The caller. One authorizer, `APIGatewayAuthorizer`, runs on every route and authenticates the bearer
token through the identity provider the `identity` block in `config.yaml` names. Its Allow policy
carries the principal; the request handler assigns it to the chat body, so the thread is recorded
under that principal's subject, and `LambdaThreadHost` scopes the read routes to it: a listing is
the caller's own threads, and another user's thread answers 403, to read or to chat on.

The block here selects the `static` provider with two principals, `alice` and `bob`. Their
credentials are never written in `config.yaml`: Terraform passes them as the `ALICE_TOKEN` and
`BOB_TOKEN` environment variables (from the `demo_auth_token` and `bob_auth_token` variables), which
the secret capability resolves at startup. To validate real tokens, swap the
provider for `oidc` (Auth0, Keycloak, Okta), `cognito`, `entra` or `firebase`, and add the `auth`
extra to the `authorizer` and `request_handler` dependency sets in `pyproject.toml`.

**The request handler needs the identity configuration too.** `ThreadRequestHandler()` requires an
`identity` block and builds its provider, so the request-handler Lambda gets the same credential
variables as the authorizer (`local.demo_credentials` in `deploy/main.tf`), even though only the
authorizer authenticates. Without them its cold start fails with a missing-secret error.

## Declare the read routes in two places

| Where | What | Symptom when it is missing |
|---|---|---|
| `lambda_request_handler.py` | `@Lambda.register("/threads", ...)` and `("/threads/{session_id}", ...)` | 500: the router has no route |
| `deploy/main.tf` | `gateway_endpoints` with `/threads` GET and `/threads/{session_id}` GET | API Gateway answers 403 before any Lambda runs |

The chat route needs no declaration: Terraform always creates it, and the host takes it over.

## What changes for the client

- Every request carries `Authorization: Bearer <token>`; the owner comes from it. A chat body
  naming a `user_id` answers 400 and records nothing.
- A missing prompt is answered 400 by the chat route, before anything is written.
- `GET /threads` lists the caller's threads; `group_id`, `limit` and `cursor` filter and page it.
- `GET /threads/{session_id}` returns the thread with a page of its messages; another user's thread
  answers 403, and a non-integer `limit` answers 400.

**Replace the static provider** with your identity provider before deploying anything you care
about: its credentials are static strings.

## Build

```bash
./build.sh          # from PyPI
./build.sh local    # from ../../../ak-py/dist
```

## Deploy

Create `deploy/terraform.tfvars` values (or `TF_VAR_*` variables) for `openai_api_key`,
`demo_auth_token` and `bob_auth_token` (two different values, for example `openssl rand -hex 32`
each), `vpc_id` and `private_subnet_ids`, then:

```bash
cd deploy
./deploy.sh         # packages from PyPI
./deploy.sh local   # packages from ../../../ak-py/dist
```

Docker must be running: the request handler and the agent runner deploy as container images, since
both load the OpenAI Agents SDK.

> Threads on Lambda need an `agentkernel` and an `ak-serverless` module release that include them
> (#879): the module must wire the thread table into the request handler in queue mode. Until those
> are published, deploy with `./deploy.sh local` and point the module `source` at
> `../../../../ak-deployment/ak-aws/serverless`.

The request handler also gets `OPENAI_API_KEY`, for thread naming through LiteLLM; without it a
thread is named after the start of its first prompt.

## Test

```bash
export AK_TEST_ENDPOINT=<agent_invoke_url output>
export AK_TEST_TOKEN=<demo_auth_token>
export AK_TEST_BOB_TOKEN=<bob_auth_token>
uv run pytest lambda_test.py
```

The tests chat twice as `alice`, then read the thread back (two user and two assistant messages, in
order) and find it in the listing; check that `bob` gets 403 reading or chatting on it and cannot
list it, that the read routes need a token, and the 400s for a chat naming a `user_id` and a
non-integer `limit`.
