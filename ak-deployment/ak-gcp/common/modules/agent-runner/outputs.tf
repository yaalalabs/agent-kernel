output "service_name" {
  description = "Name of the agent runner's Cloud Run service"
  value       = google_cloud_run_v2_service.runner.name
}

output "push_endpoint" {
  description = "URL Pub/Sub pushes requests to (CloudRunAgentRunner's push route)"
  value       = "${google_cloud_run_v2_service.runner.uri}/pubsub/push"
}

output "push_service_account_email" {
  description = "Identity Pub/Sub signs each push with; the only caller allowed to invoke the runner"
  value       = google_service_account.push.email
}

output "service_account_email" {
  description = "Service account the agent runner runs as"
  value       = google_service_account.runner.email
}
