# Agent Runner Module

The agent tier of Agent Kernel queue mode on GCP: a private Cloud Run **service** that Pub/Sub
pushes each request to. Its entry point calls `agentkernel.gcp.CloudRunAgentRunner.run()`, which
runs the agents and publishes the reply to the output topic. Cloud Run scales it on those pushes,
down to zero.

- **Push, accepted trade-off:** Pub/Sub waits at most 600 seconds for a push to be answered. An
  agent run that takes longer is redelivered while it is still going and runs a second time. The
  service's own request timeout is Cloud Run's maximum (60 minutes), so a long run is never cut off.
- **Private:** ingress is internal-only. Pub/Sub push from the same project counts as internal, and
  only the push identity (`<prefix>-psh`) holds `roles/run.invoker`.
- **Identity:** its own service account, with least-privilege Pub/Sub rights on the named
  resources (publish to the output topic and the input dead-letter topic, and view them for the
  transport's checks), plus logging and, optionally, Firestore.
- **Network:** the root's Serverless VPC Access connector, so it reaches Memorystore the way the
  edge service does.

## Usage

```hcl
module "agent_runner" {
  source = "yaalalabs/ak-common/google//modules/agent-runner"

  project_id       = "my-gcp-project"
  region           = "us-central1"
  prefix           = "myapp-prod-api"
  image_url        = module.docker_image.image_url
  command          = ["python", "-c", "from app import runner; runner()"]
  vpc_connector_id = google_vpc_access_connector.connector.id
  pubsub = {
    topics             = module.pubsub.topics
    dead_letter_topics = module.pubsub.dead_letter_topics
  }
  environment_variables = { AK_EXECUTION__QUEUES__PUBSUB__PROJECT_ID = "my-gcp-project" }
}
```

Pass its `push_endpoint` and `push_service_account_email` to the `pubsub` module.

## Inputs

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `project_id`, `region`, `prefix` | Where and under what name the service is created (`<prefix>-runner`) | `string` | required |
| `image_url` | Container image | `string` | required |
| `command`, `args` | Entrypoint and argument overrides | `list(string)` | `null` |
| `cpu` / `memory` | Per instance | `string` | `"1"` / `"512Mi"` |
| `min_instance_count` / `max_instance_count` | Scaling bounds; 0 scales to zero | `number` | `0` / `10` |
| `concurrency` | Agent runs per instance | `number` | `5` |
| `container_port` | The app's `api.port` | `number` | `8000` |
| `environment_variables` | Runner environment, including the queue coordinates | `map(string)` | `{}` |
| `vpc_connector_id` | VPC connector for Memorystore | `string` | required |
| `pubsub` | The `pubsub` module's `topics` and `dead_letter_topics` | `object` | required |
| `grant_firestore` | Grant `roles/datastore.user` | `bool` | `false` |
| `labels` | Labels | `map(string)` | `{}` |

## Outputs

| Name | Description |
|------|-------------|
| `service_name` | The service's name |
| `push_endpoint` | URL Pub/Sub pushes requests to |
| `push_service_account_email` | Identity Pub/Sub signs each push with |
| `service_account_email` | The runner's service account |
