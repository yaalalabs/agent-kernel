output "agent_invoke_url" {
  description = "Chat endpoint. POST here with curl -N to read the SSE stream"
  value       = module.containerized_agents.agent_invoke_url
}

output "api_gateway_id" {
  description = "REST API Gateway ID"
  value       = module.containerized_agents.api_gateway_id
}

output "api_gateway_stage" {
  description = "REST API Gateway stage name"
  value       = module.containerized_agents.api_gateway_stage
}

output "redis_url" {
  description = "Response store Redis URL. SSE reads its chunks from here"
  value       = module.containerized_agents.redis_url
}

output "alb_dns_name" {
  description = "Internal ALB DNS name. Curl this from inside the VPC to take the gateway out of the picture"
  value       = module.containerized_agents.alb_dns_name
}

output "input_queue_url" {
  description = "SQS Input Queue URL"
  value       = module.containerized_agents.input_queue_url
}

output "output_queue_url" {
  description = "SQS Output Queue URL"
  value       = module.containerized_agents.output_queue_url
}

output "agent_runner_service_name" {
  description = "ECS Agent Runner service name"
  value       = module.containerized_agents.agent_runner_service_name
}
