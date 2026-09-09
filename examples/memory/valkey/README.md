# Agent Kernel running OpenAI Agents SDK-based agents in AWS Lambda with Valkey as agent memory

This package contains a demo of Agent Kernel running agents built with the OpenAI Agents SDK,
running them in a serverless configuration using AWS Lambda with [Valkey](https://valkey.io/) as
agent memory (session storage).

Valkey is the open-source, Linux Foundation-governed fork of Redis. It is wire-compatible with
Redis and available on AWS ElastiCache as a native engine. Agent Kernel selects it with
`session.type: valkey` (see `config.yaml`).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed.
- An OpenAI API key.
- For AWS deployment: AWS CLI configured with appropriate credentials and Terraform (`1.9.5` or higher).

## Run locally

1. Start a local Valkey server (the default `config.yaml` points at `valkey://localhost:6379`):
    ```bash
    docker run --rm -p 6379:6379 valkey/valkey
    ```

2. Install dependencies and set your API key:
    ```bash
    ./build.sh
    export OPENAI_API_KEY=<OPENAI_API_KEY>
    ```

3. Run the agent locally:
    ```bash
    uv run ak run
    ```

The session state (agent memory) is persisted in the local Valkey server between requests. Use
`valkeys://` in the URL for an SSL/TLS-enabled endpoint.

## Deployed Resources

The AWS deployment provisions the following resources:

- AWS Lambda function running the Agent Kernel implementation.
- API Gateway endpoint for the Lambda function.
- An ElastiCache for Valkey cluster (`create_valkey_cluster = true` in `deploy/main.tf`). The
  deployment injects the cluster endpoint as `AK_SESSION__VALKEY__URL`, overriding the URL in
  `config.yaml`. Set `create_valkey_cluster = false` to reuse an existing Valkey host configured
  in `config.yaml` instead.

## AWS Deployment Steps

1. Configure environment variables:
    ```bash
    export TF_VAR_openai_api_key=<OPENAI_API_KEY>
    ```

2. Set the VPC and subnets to deploy into in `deploy/terraform.tfvars` (`vpc_id`,
   `private_subnet_ids`), then run the deployment script:
    ```bash
    cd deploy && ./deploy.sh # ./deploy.sh local if dependencies are built locally
    ```

3. Tear down when finished:
    ```bash
    cd deploy && terraform destroy
    ```
