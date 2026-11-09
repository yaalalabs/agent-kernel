output "topics" {
  description = "Queue topic names, keyed by queue (input, output)"
  value       = { for queue, topic in google_pubsub_topic.queue : queue => topic.name }
}

output "input_subscription" {
  description = "The request subscription's name (push, to the agent runner)"
  value       = google_pubsub_subscription.input.name
}

output "output_subscription" {
  description = "The reply subscription's name (pulled by the edge)"
  value       = google_pubsub_subscription.output.name
}

output "dead_letter_topics" {
  description = "Dead-letter topic names, keyed by queue (input, output)"
  value       = { for queue, topic in google_pubsub_topic.dead_letter : queue => topic.name }
}

output "dlq_suffix" {
  description = "Suffix of the dead-letter topic names, as the transport's execution.queues.pubsub.dlq_suffix"
  value       = var.dlq_suffix
}
