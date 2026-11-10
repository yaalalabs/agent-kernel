# Agent Kernel Conversation Threads on AWS Lambda

This package deploys an OpenAI agent on AWS Lambda with Conversation Thread Support. The chat route
records each user message in a thread before it enqueues the request, the agent-runner Lambda
records the reply, and two read routes serve the threads back.

It is the serverless counterpart of [`examples/api/thread-openai`](../../api/thread-openai), which
mounts the same thread handler on the FastAPI server.

## Architecture Overview

```
Client --POST /api/v1/chat (user_id required)--> API Gateway --> Authorizer
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
- **Authorizer Lambda**: a demo validator whose subject is the user the token names
  (`alice-token` → `alice`, `bob-token` → `bob`, `guest-token` → `guest`). See below.
- **Agent-runner Lambda**: runs the agent and records the reply of every marked request.
- **Response-handler Lambda**: writes the reply to the response store, unchanged.

Both the request handler and the agent runner read the same `thread` block in `config.yaml`, which
must name a shared store (`dynamodb` here; `in_memory` fails the request handler's cold start).

## Authorizing the read routes

There is one authorizer, the existing `APIGatewayAuthorizer`, on every route; no second authorizer
and no Terraform change. The read routes are protected in two layers:

1. **Route rules, in your `AuthValidator`.** `validate` receives the request path and method in its
   `ValidationContext`, so it decides who may call which route. The demo lets `guest` chat but
   denies it `GET .../threads*`; API Gateway then answers 403 before any Lambda runs.
2. **Principal scoping, in `LambdaThreadHost`.** The validator's `subject` becomes the request's
   `principalId`, and the read routes are limited to it: a listing is forced to that user, and
   another user's thread answers 403.

Build `ThreadRequestHandler()` without an `Authoriser`: on Lambda the gateway authorizes, and the
host fails at cold start if one is passed.

## Declare the read routes in two places

| Where | What | Symptom when it is missing |
|---|---|---|
| `lambda_request_handler.py` | `@Lambda.register("/threads", ...)` and `("/threads/{session_id}", ...)` | 500: the router has no route |
| `deploy/main.tf` | `gateway_endpoints` with `/threads` GET and `/threads/{session_id}` GET | API Gateway answers 403 before any Lambda runs |

The chat route needs no declaration: Terraform always creates it, and the host takes it over.

## What changes for the client

- `user_id` is required on every chat request: without it the chat route answers 400 and records
  nothing.
- A missing prompt is answered 400 by the chat route, before anything is written.
- `GET /threads` lists the caller's threads (a `user_id` query parameter is overridden by the
  authorized user); `group_id`, `limit` and `cursor` page it.
- `GET /threads/{session_id}` returns the thread with a page of its messages; another user's thread
  answers 403, and a non-integer `limit` answers 400.

**Replace the demo authorizer** (`lambda_auth.py`) with your identity provider's token check before
deploying anything you care about: its tokens are static strings.

## Build

```bash
./build.sh          # from PyPI
./build.sh local    # from ../../../ak-py/dist
```

## Deploy

Create `deploy/terraform.tfvars` values (or `TF_VAR_*` variables) for `openai_api_key`, `vpc_id` and
`private_subnet_ids`, then:

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
uv run pytest lambda_test.py
```

The tests chat twice as `alice`, then read the thread back (two user and two assistant messages, in
order) and find it in the listing; check that `bob` gets 403 on it and cannot list it, that `guest`
can chat but gets 403 on both read routes, and the 400s for a chat without `user_id` and a
non-integer `limit`.
