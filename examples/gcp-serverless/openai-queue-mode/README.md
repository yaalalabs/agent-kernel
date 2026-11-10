# Agent Kernel queue mode on GCP Cloud Run (OpenAI Agents SDK)

This example deploys Agent Kernel's queue mode to Google Cloud. One container image runs as two
Cloud Run services, connected by Pub/Sub:

```
client → API Gateway → edge (Cloud Run)  ──publish──▶ agent-input  ──push──▶ agent runner (Cloud Run, private)
                           ▲                                                      │
                           └──── pull ◀── agent-output ◀────── publish ───────────┘
                     replies are handed back through Memorystore (Redis)
```

- **Edge** (`main()` in `app.py`, `CloudRun.run()`): serves `/api/v1/chat`, publishes each request,
  and answers with the reply once the response handler has stored it.
- **Agent runner** (`runner()` in `app.py`, `CloudRunAgentRunner.run()`): Pub/Sub pushes each request
  to it; it runs the agents and publishes the reply. Only Pub/Sub can call it.
- **Both scale to zero.** The first request after a quiet spell waits for the services to start.
- A session's requests run one at a time, in order (the session id is the Pub/Sub ordering key).
- Pub/Sub waits at most 600 seconds for the runner to answer a push. An agent run that takes longer
  is redelivered while it is still going and runs a second time. The runner's own timeout is 60
  minutes, so a long run is never cut off.

`../openai` runs the same setup and adds custom endpoints beside the chat route.

## Prerequisites

- A GCP project with these APIs enabled: `run`, `artifactregistry`, `apigateway`,
  `servicecontrol`, `servicemanagement`, `vpcaccess`, `redis`, `compute`, and **`pubsub`**
- `gcloud auth application-default login`, Docker running, Terraform >= 1.9.5
- `OPENAI_API_KEY`

> The `pubsub` extra and the `agent_runner` module input ship with the release that introduces queue
> mode on GCP. Until then, deploy with `./deploy.sh local`, which builds `agentkernel` from this
> repository.

## Deploy

```bash
cd deploy
export TF_VAR_openai_api_key=sk-...
# set project_id, region and prefix in terraform.tfvars
./deploy.sh          # or ./deploy.sh local
```

Then call the agent:

```bash
curl -X POST "$(terraform output -raw agent_invoke_url)" \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Who won the 1996 cricket world cup?", "session_id": "s1", "agent": "triage"}'
```

## What makes it queue mode

- **`config.yaml`** declares the transport and the stores: `execution.queues.type: pubsub`,
  `execution.response_store.type: redis`, `session.type: redis`. Terraform injects only the
  coordinates (project, topics, subscription, Redis URL).
- **`deploy/main.tf`** gives the runner its own entry point:
  `agent_runner = { command = ["python", "-c", "from app import runner; runner()"] }`. Without it,
  the runner would start the edge's `CMD` instead.
- `queue_mode = true` is the module's default. It also creates Memorystore as the reply store.

## Tests

```bash
AK_TEST_ENDPOINT="$(cd deploy && terraform output -raw agent_invoke_url)" uv run pytest -s
```

`serverless_test.py` retries timeouts and 5xx answers, since a cold start of both services can
exceed the gateway's deadline on the first call. The weekly integration run deploys this example,
runs the test, and destroys it.

## Teardown

```bash
cd deploy && terraform destroy
```
