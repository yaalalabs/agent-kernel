output "service_url" {
  description = "Direct Cloud Run service URL"
  value       = google_cloud_run_v2_service.service.uri
}

output "service_name" {
  description = "Cloud Run service name"
  value       = google_cloud_run_v2_service.service.name
}

output "service_account_email" {
  description = "Service account email used by Cloud Run"
  value       = google_service_account.run_sa.email
}

output "gateway_url" {
  description = "API Gateway base URL"
  value       = google_api_gateway_gateway.gateway.default_hostname
}

output "api_gateway_id" {
  description = "API Gateway ID"
  value       = google_api_gateway_api.api.api_id
}

output "agent_invoke_url" {
  description = "Full agent invocation URL via API Gateway"
  value       = "https://${google_api_gateway_gateway.gateway.default_hostname}/${local.api_base_segment}/${var.api_version}/${var.agent_endpoint}"
}

output "authorizer_status" {
  description = "Status message indicating whether the JWT authorizer is configured"
  value       = local.authorizer_status_message
}
