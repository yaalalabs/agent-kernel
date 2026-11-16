# Pub/Sub's own service agent moves messages to the dead-letter topics: it publishes to them and
# reads from the queue subscriptions it forwards from.

data "google_project" "project" {
  project_id = var.project_id
}

resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  for_each = local.queues

  project = var.project_id
  topic   = google_pubsub_topic.dead_letter[each.key].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "dead_letter_forwarder" {
  for_each = {
    input  = google_pubsub_subscription.input.name
    output = google_pubsub_subscription.output.name
  }

  project      = var.project_id
  subscription = each.value
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}
