# SSE streaming with OpenAI Agents on AWS Lambda

This example streams an agent's reply as **Server-Sent Events (SSE)** from AWS Lambda: `execution.mode: rest_sync`
with `message_type: delta`. The caller sends one `POST` and keeps the connection open while the reply arrives as
`data:` frames.

## How it works

```
Client → API Gateway (STREAM) → Request-handler Lambda (Lambda Web Adapter + uvicorn)
                                  │ enqueue                        ▲ SSE frames
                                  ▼                                │ store.stream
                              SQS input → Agent runner → SQS output → Response handler → Redis
```

- **Request handler:** runs the same app the ECS deployment runs (`LambdaStreamServer`), behind the
  [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter). It enqueues the request and streams
  the chunks it reads from Redis.
- **Agent runner:** runs the agent and sends one SQS message per chunk.
- **Response handler:** writes each chunk to the Redis response store.
- **Authentication:** inside the app, through the `identity` block in `config.yaml`. There is no API Gateway
  authorizer in SSE mode.

## Limits

- A stream lasts up to **15 minutes**, and closes after **5 minutes with no data**.
- The **request-handler Lambda timeout** bounds the stream. This example sets 300 seconds.
- **Each open stream holds one request-handler instance** for the whole agent run, and counts against the function's
  concurrency.
- A client that disconnects does **not** stop the agent run, and the function is still billed.
- If the agent runner fails mid-run, SQS retries the whole run and the caller sees the reply start again.

## Prerequisites

- AWS CLI configured, Terraform `1.9.5` or higher, Docker (for the agent runner image), `uv`.
- An S3 bucket named `lambda-s3-packages-<account-id>-<region>-an` **with versioning enabled** (see the
  `scalable-openai` example for why).
- An existing VPC and private subnets: set `vpc_id` and `private_subnet_ids` in `deploy/terraform.tfvars`.

## Secrets

Create the OpenAI key as an SSM parameter under the prefix set in `deploy/terraform.tfvars`
(`/ak/<prefix>/<key lowercased>`):

```bash
aws ssm put-parameter --type SecureString --name /ak/<prefix>/openai_api_key --value <your OpenAI key>
```

Choose the bearer token callers send, and pass it to Terraform. It reaches the request handler as the
`DEMO_AUTH_TOKEN` environment variable that the `identity` block in `config.yaml` names:

```bash
export TF_VAR_demo_auth_token=$(openssl rand -hex 32)
```

Without an `identity` block every caller would be anonymous.

## Deploy

```bash
./build.sh
cd deploy
./deploy.sh
```

`LambdaStreamServer` is not in a released `agentkernel` yet. Until it is, build the wheel (`ak-py/dist`) and deploy from
the local source instead: `./build.sh local`, then `./deploy.sh local`.

The request handler is a zip package, so the adapter is a **layer**: `deploy/main.tf` pins
`LambdaAdapterLayerX86:30` in `request_handler.layers` and the module sets the adapter's environment variables. For an
image package, copy the adapter from `public.ecr.aws/awsguru/aws-lambda-adapter:<version>` in your Dockerfile instead.

## Try it

```bash
curl -N -X POST "$(terraform output -raw agent_invoke_url)" \
  -H "Authorization: Bearer $TF_VAR_demo_auth_token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Who won the 1996 cricket world cup?", "agent": "triage", "session_id": "'"$(uuidgen)"'"}'
```

`session_id` is required: the queue pipeline keys the reply stream on it. Any client-generated id works.

You should see `data: {...}` frames arrive one by one, and the last one carry `"done": true`.

## Test

```bash
AK_TEST_ENDPOINT="$(terraform output -raw agent_invoke_url)" AK_TEST_TOKEN="$TF_VAR_demo_auth_token" \
  uv run --no-sync pytest lambda_test.py
```

The test asserts several `data:` frames, a final `done: true`, and that frames arrive while the run is still going.
