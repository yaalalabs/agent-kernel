locals {
  queues = {
    input  = { name = "${var.prefix}-agent-input", max_receive_count = var.input_queue_max_receive_count }
    output = { name = "${var.prefix}-agent-output", max_receive_count = var.output_queue_max_receive_count }
  }

  # Pub/Sub's own service agent moves messages to a dead-letter topic, so it needs rights on both
  # ends of every dead-letter policy.
  pubsub_service_agent = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
