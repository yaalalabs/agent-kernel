# Pub/Sub Module

The Pub/Sub objects for Agent Kernel queue mode on GCP: a request queue (`<prefix>-agent-input`)
whose subscription **pushes** each request to the agent runner, and a reply queue
(`<prefix>-agent-output`) whose subscription the edge **pulls**, plus a dead-letter topic per queue.

- **Ordering:** subscriptions have message ordering enabled. A session's turns share an ordering
  key, so they run in order, one at a time.
- **Dead letters:** `<queue>-dlq` topics. The agent runner copies a message there itself once it
  gives up on it; the subscription's dead-letter policy (`max_delivery_attempts`, clamped to 5-100)
  is the server-side backstop. Each dead-letter topic has a subscription (7-day retention) so the
  copies are kept: Pub/Sub drops messages published to a topic with no subscription.
- **Push:** the request subscription waits 600 seconds (Pub/Sub's maximum) for the runner to answer,
  and signs each push with an OIDC token for `input_push_service_account_email`. A longer agent run
  is redelivered while it is still going (the accepted trade-off of push).
- **Leases:** the reply subscription's ack deadline is Pub/Sub's minimum (10 s). Agent Kernel's
  transport renews each pulled message's lease itself, up to its `ack_wait`.
- **Never expire:** `expiration_policy { ttl = "" }`, so a quiet deployment keeps its queues.
- **IAM:** grants Pub/Sub's service agent the rights dead-letter forwarding needs. The edge and the
  runner get their own rights from the root module and the `agent-runner` module.

## Usage

```hcl
module "pubsub" {
  source = "yaalalabs/ak-common/google//modules/pubsub"

  project_id                       = "my-gcp-project"
  prefix                           = "myapp-prod-api"
  input_queue_max_receive_count    = 3
  output_queue_max_receive_count   = 3
  input_push_endpoint              = module.agent_runner.push_endpoint
  input_push_service_account_email = module.agent_runner.push_service_account_email
}
```

## Inputs

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `project_id` | GCP project that owns the topics and subscriptions | `string` | required |
| `prefix` | Name prefix for the queues | `string` | required |
| `input_queue_max_receive_count` | Deliveries of a request before it is permanently failed | `number` | `3` |
| `output_queue_max_receive_count` | Deliveries of a reply before it is permanently failed | `number` | `3` |
| `input_push_endpoint` | URL the request subscription pushes to | `string` | required |
| `input_push_service_account_email` | Identity each push is signed with | `string` | required |
| `dlq_suffix` | Suffix of the dead-letter topic names | `string` | `"-dlq"` |
| `labels` | Labels on every topic and subscription | `map(string)` | `{}` |

## Outputs

| Name | Description |
|------|-------------|
| `topics` | Queue topic names, keyed by `input` / `output` |
| `input_subscription` | The request subscription's name (push) |
| `output_subscription` | The reply subscription's name (pull) |
| `dead_letter_topics` | Dead-letter topic names, keyed by `input` / `output` |
| `dlq_suffix` | The dead-letter suffix, for `execution.queues.pubsub.dlq_suffix` |
