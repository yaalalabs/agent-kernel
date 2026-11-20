# Pub/Sub objects for Agent Kernel queue mode: a request queue whose ordered subscription pushes to
# the agent runner, a reply queue whose ordered subscription the edge pulls, and a dead-letter topic
# per queue (with a subscription on it, so the copies are kept: Pub/Sub drops messages published to
# a topic with no subscription).

resource "google_pubsub_topic" "queue" {
  for_each = local.queues

  project = var.project_id
  name    = each.value.name
  labels  = var.labels
}

resource "google_pubsub_topic" "dead_letter" {
  for_each = local.queues

  project = var.project_id
  name    = "${each.value.name}${var.dlq_suffix}"
  labels  = var.labels
}
