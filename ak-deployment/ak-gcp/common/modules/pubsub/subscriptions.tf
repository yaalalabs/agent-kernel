# Requests are pushed to the agent runner, one HTTP call per message; the response acknowledges it.
resource "google_pubsub_subscription" "input" {
  project = var.project_id
  name    = local.queues.input.name
  topic   = google_pubsub_topic.queue["input"].id
  labels  = var.labels

  # A session's turns share an ordering key: with push, Pub/Sub keeps one outstanding per key, so
  # they run in order, one at a time.
  enable_message_ordering = true

  # For push this is how long Pub/Sub waits for the runner to answer: the maximum, 600 seconds. A
  # longer agent run is redelivered while it is still going and runs a second time (the accepted
  # trade-off of push on Cloud Run).
  ack_deadline_seconds = 600

  push_config {
    push_endpoint = var.input_push_endpoint
    oidc_token {
      service_account_email = var.input_push_service_account_email
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter["input"].id
    max_delivery_attempts = min(max(local.queues.input.max_receive_count, 5), 100)
  }

  retry_policy {
    minimum_backoff = "2s"
    maximum_backoff = "60s"
  }

  # Never expire: by default Pub/Sub deletes a subscription after 31 days without activity.
  expiration_policy {
    ttl = ""
  }

  depends_on = [google_pubsub_topic_iam_member.dead_letter_publisher]
}

# Replies are pulled by the edge's response handler.
resource "google_pubsub_subscription" "output" {
  project = var.project_id
  name    = local.queues.output.name
  topic   = google_pubsub_topic.queue["output"].id
  labels  = var.labels

  enable_message_ordering = true

  # Pub/Sub's minimum. The transport renews each pulled message's lease itself (up to its ack_wait),
  # so this only bounds how long a message lost to a cancelled pull waits before redelivery. Keep it
  # equal to SUBSCRIPTION_ACK_DEADLINE_SECONDS in agentkernel/pipeline/transport/pubsub.py.
  ack_deadline_seconds = 10

  # The response handler permanently fails a reply on its max_receive_count-th delivery and copies it
  # here itself; the policy is the server-side backstop behind that.
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter["output"].id
    max_delivery_attempts = min(max(local.queues.output.max_receive_count, 5), 100)
  }

  # The 60 s maximum bounds how late a redelivery can arrive, which the transport's 300 s memory of
  # acknowledged messages relies on.
  retry_policy {
    minimum_backoff = "2s"
    maximum_backoff = "60s"
  }

  expiration_policy {
    ttl = ""
  }

  depends_on = [google_pubsub_topic_iam_member.dead_letter_publisher]
}

resource "google_pubsub_subscription" "dead_letter" {
  for_each = local.queues

  project = var.project_id
  name    = google_pubsub_topic.dead_letter[each.key].name
  topic   = google_pubsub_topic.dead_letter[each.key].id
  labels  = var.labels

  # Kept for inspection: the longest retention Pub/Sub allows.
  message_retention_duration = "604800s"

  expiration_policy {
    ttl = ""
  }
}
