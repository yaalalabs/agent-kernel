# Agent Kernel Slack Integration on AWS Lambda

This package deploys a Slack bot on AWS Lambda. Slack's Events API webhook reaches the
request-handler Lambda, which verifies, acknowledges and enqueues each message; the agent runs
behind the Input Queue; and the response-handler Lambda posts the reply back to Slack.

It is the serverless counterpart of [`examples/api/slack`](../../api/slack), which runs the same
`WebhookRESTRequestHandler` on the pipeline's FastAPI server.

## Architecture Overview

```
Slack --POST /api/v1/slack/events--> API Gateway --> Authorizer (bypass: method + path)
                                          |
                                          v
                               Request-handler Lambda
                               Lambda.register -> LambdaWebhookHost -> WebhookRESTRequestHandler
                               (verify signature, "thinking...", enqueue)
                                          |
                        integration=slack, reply_* attributes
                                          v
                Input Queue --> Agent-runner Lambda --> Output Queue --> Response-handler Lambda
                                                                                |
                                                          OutboundAdapter.deliver -> Slack
```

- **Request-handler Lambda**: the chat route plus `POST /api/v1/slack/events`, registered with
  `@Lambda.register("/slack/events", method="POST")` on a function that calls
  `LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter())).handle`.
- **Authorizer Lambda**: bearer-token auth for the chat route, with
  `bypass=WebhookRouteMatcher.for_integrations("slack")` for the webhook. Slack sends no bearer
  token; the adapter's signature check is the real authentication.
- **Agent-runner Lambda**: runs the agent. It keeps the message's return address (`integration`
  plus the `reply_*` context) on the reply.
- **Response-handler Lambda**: delivers the reply to Slack through the Slack outbound adapter.

## Declare the integration in three places

The three must agree, and a mismatch fails quietly from Agent Kernel's side:

| Where | What | Symptom when it is missing |
|---|---|---|
| `lambda_auth.py` | `WebhookRouteMatcher.for_integrations("slack")` | Slack gets 403: with no `Authorization` header the authorizer logs `Event validation failed` and denies without calling the validator |
| `lambda_request_handler.py` | `@Lambda.register("/slack/events", method="POST")` calling `LambdaWebhookHost(...).handle` | Slack gets 500: the router has no route |
| `deploy/main.tf` | `gateway_endpoints = [{ path = "/slack/events", method = "POST" }]` | API Gateway answers 403 before any Lambda runs |

**The authorizer's cache must be off** (`result_ttl_in_seconds = 0`, set in `deploy/main.tf`). With
a TTL, API Gateway answers a request that has no `Authorization` header with 401 before the
authorizer runs, so the bypass never gets a say, and Agent Kernel never logs it. The cost is one
authorizer call per request, chat included.

## Slack app setup

1. Create an app at <https://api.slack.com/apps>.
2. Under **OAuth & Permissions**, add the bot scopes `chat:write`, `channels:history` and
   `im:history` (plus `groups:history` and `mpim:history` for private channels and group DMs), then
   install the app and copy the **Bot User OAuth Token** (`xoxb-...`).
3. Under **Basic Information**, copy the **Signing Secret**.
4. Deploy (below), then under **Event Subscriptions** set the **Request URL** to the
   `slack_events_url` output and subscribe to the `message.channels` and `message.im` bot events
   (plus `message.groups` and `message.mpim` if you added their scopes). Slack sends a
   `url_verification` request, which Bolt answers.

   The adapter consumes Slack `message` events, not `app_mention`: a mention-only subscription gets
   Bolt's 404 for every mention. The bot answers messages in the channels it is a member of and in
   DMs, so invite it to a channel to use it there.

See the [Slack integration docs](https://kernel.yaala.ai/docs/integrations/slack) for the adapter
itself.

## Build

```bash
./build.sh          # from PyPI
./build.sh local    # from ../../../ak-py/dist
```

## Deploy

Create `deploy/terraform.tfvars` values (or `TF_VAR_*` variables) for `openai_api_key`,
`slack_bot_token`, `slack_signing_secret`, `demo_auth_token`, `vpc_id` and `private_subnet_ids`,
then:

```bash
cd deploy
./deploy.sh         # packages from PyPI
./deploy.sh local   # packages from ../../../ak-py/dist
```

Docker must be running: the agent runner deploys as a container image.

> Serving webhooks on Lambda needs an `agentkernel` and an `ak-serverless` module release that
> include messaging-integration support (#760). Until those are published, deploy with
> `./deploy.sh local` and point the module `source` at `../../../../ak-deployment/ak-aws/serverless`.

## Cold starts and Slack's 3 seconds

Slack expects its 200 within 3 seconds. On a cold start the request handler has to import Bolt and
FastAPI, and the authorizer is one more Lambda call in the budget. Keep the request-handler package
slim (no agent frameworks: that is why the agent runner has its own package), and use provisioned
concurrency or a warm-up schedule for the request-handler and authorizer Lambdas if cold starts
matter. A timeout retry from Slack is dropped at the edge, so the user still sees one "thinking..."
and one reply.

## Smoke test

```bash
export AK_TEST_ENDPOINT=<agent_invoke_url output>
export AK_TEST_TOKEN=<demo_auth_token>
export SLACK_SIGNING_SECRET=<signing secret>
uv run pytest lambda_test.py
```

The three checks need no Slack workspace: the chat route still requires a token, an unsigned
Slack delivery reaches Bolt (401 `{"error": "invalid request"}`, not API Gateway's
`{"message": "Unauthorized"}`), and a signed `url_verification` is answered with its challenge.
