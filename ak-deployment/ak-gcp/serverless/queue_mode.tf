# Queue mode (#886): the service becomes the edge (REST API + response handler, started by
# CloudRun.run()), and an agent-runner service runs the agents (CloudRunAgentRunner.run()): Pub/Sub
# pushes each request to it, and it publishes the reply, which the edge pulls. Replies are handed
# back through the Memorystore response store. With queue_mode = false nothing here is created and
# the single-service deployment is unchanged.

locals {
  edge_service_account_member = "serviceAccount:${google_service_account.function_sa.email}"

  # The runner's image: its own build, else a prebuilt image, else the edge's image (which then
  # runs with agent_runner.command, enforced by that variable's validation).
  agent_runner_image = (
    var.agent_runner.package_path != null ? module.agent_runner_docker_image[0].image_url :
    var.agent_runner.image_uri != null ? var.agent_runner.image_uri : module.docker_image.image_url
  )

  # Queue coordinates, injected into both tiers. Never AK_EXECUTION__QUEUES__TYPE or the response
  # store type: the app's config.yaml declares those. A max_receive_count here counts deliveries,
  # as on AWS: the app fails a message on that delivery, so it is given one less.
  queue_env = var.queue_mode ? merge(
    {
      AK_EXECUTION__QUEUES__PUBSUB__PROJECT_ID          = var.project_id
      AK_EXECUTION__QUEUES__PUBSUB__INPUT_TOPIC         = module.pubsub[0].topics["input"]
      AK_EXECUTION__QUEUES__PUBSUB__OUTPUT_TOPIC        = module.pubsub[0].topics["output"]
      AK_EXECUTION__QUEUES__PUBSUB__OUTPUT_SUBSCRIPTION = module.pubsub[0].output_subscription
      AK_EXECUTION__QUEUES__PUBSUB__DLQ_SUFFIX          = module.pubsub[0].dlq_suffix
      AK_EXECUTION__QUEUES__INPUT__MAX_RECEIVE_COUNT    = tostring(max(1, var.queue_config.input_queue_max_receive_count - 1))
      AK_EXECUTION__QUEUES__OUTPUT__MAX_RECEIVE_COUNT   = tostring(max(1, var.queue_config.output_queue_max_receive_count - 1))
      AK_EXECUTION__QUEUES__BATCH_SIZE                  = tostring(var.queue_config.batch_size)
      AK_EXECUTION__RESPONSE_STORE__REDIS__URL          = local.redis_url
      # Both tiers must agree on the reply shape the edge's route expects.
      AK_EXECUTION__MODE = var.execution_mode
    },
    var.message_type != null ? { AK_EXECUTION__MESSAGE_TYPE = var.message_type } : {},
  ) : {}
}

module "pubsub" {
  source = "yaalalabs/ak-common/google//modules/pubsub"
  count  = var.queue_mode ? 1 : 0

  project_id                     = var.project_id
  prefix                         = var.prefix
  input_queue_max_receive_count  = var.queue_config.input_queue_max_receive_count
  output_queue_max_receive_count = var.queue_config.output_queue_max_receive_count
  labels                         = var.tags

  # Requests are pushed to the agent runner. (Its environment uses only the topics and the reply
  # subscription, never the request subscription, which depends on its URL.)
  input_push_endpoint              = module.agent_runner[0].push_endpoint
  input_push_service_account_email = module.agent_runner[0].push_service_account_email
}

# The runner's own image, when it is packaged separately. Its own prefix: the Artifact Registry
# repository is named after the prefix.
module "agent_runner_docker_image" {
  source = "yaalalabs/ak-common/google//modules/artifact-registry"
  count  = var.queue_mode && var.agent_runner.package_path != null ? 1 : 0

  project_id  = var.project_id
  region      = var.region
  prefix      = "${var.prefix}-runner"
  source_path = var.agent_runner.package_path
}

module "agent_runner" {
  source = "yaalalabs/ak-common/google//modules/agent-runner"
  count  = var.queue_mode ? 1 : 0

  project_id            = var.project_id
  region                = var.region
  prefix                = var.prefix
  image_url             = local.agent_runner_image
  command               = var.agent_runner.command
  args                  = var.agent_runner.args
  cpu                   = var.agent_runner.cpu
  memory                = var.agent_runner.memory
  min_instance_count    = var.agent_runner.min_instance_count
  max_instance_count    = var.agent_runner.max_instance_count
  concurrency           = var.agent_runner.concurrency
  container_port        = var.container_port
  environment_variables = merge(var.environment_variables, local.session_env, local.queue_env, var.agent_runner.environment_variables)
  vpc_connector_id      = google_vpc_access_connector.connector.id
  grant_firestore       = var.create_firestore_database
  labels                = var.tags

  pubsub = {
    topics             = module.pubsub[0].topics
    dead_letter_topics = module.pubsub[0].dead_letter_topics
  }
}

# The edge publishes requests, and copies permanently failed replies to the output dead-letter
# topic. viewer lets the transport verify each topic at startup.
resource "google_pubsub_topic_iam_member" "edge_publish" {
  for_each = {
    for pair in(var.queue_mode ? setproduct(["input", "output_dead_letter"], ["roles/pubsub.publisher", "roles/pubsub.viewer"]) : []) :
    "${pair[0]}:${pair[1]}" => {
      topic = pair[0] == "input" ? module.pubsub[0].topics["input"] : module.pubsub[0].dead_letter_topics["output"]
      role  = pair[1]
    }
  }

  project = var.project_id
  topic   = each.value.topic
  role    = each.value.role
  member  = local.edge_service_account_member
}

# The edge's response handler pulls replies.
resource "google_pubsub_subscription_iam_member" "edge_output" {
  for_each = var.queue_mode ? toset(["roles/pubsub.subscriber", "roles/pubsub.viewer"]) : toset([])

  project      = var.project_id
  subscription = module.pubsub[0].output_subscription
  role         = each.value
  member       = local.edge_service_account_member
}
