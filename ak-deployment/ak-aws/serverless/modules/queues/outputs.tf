# Input Queue Outputs
output "input_queue_arn" {
  description = "ARN of the input queue"
  value       = module.input_queue.queue_arn
}

output "input_queue_url" {
  description = "URL of the input queue"
  value       = module.input_queue.queue_url
}

output "input_queue_name" {
  description = "Name of the input queue"
  value       = module.input_queue.queue_name
}

output "input_dlq_arn" {
  description = "ARN of the input dead letter queue"
  value       = module.input_queue.dlq_arn
}

output "input_dlq_url" {
  description = "URL of the input dead letter queue"
  value       = module.input_queue.dlq_url
}

output "input_queue_visibility_timeout" {
  description = "Visibility timeout of the input queue"
  value       = var.queue_config.input_queue_visibility_timeout
}

# Output Queue Outputs
output "output_queue_arn" {
  description = "ARN of the output queue"
  value       = module.output_queue.queue_arn
}

output "output_queue_url" {
  description = "URL of the output queue"
  value       = module.output_queue.queue_url
}

output "output_queue_name" {
  description = "Name of the output queue"
  value       = module.output_queue.queue_name
}

output "output_dlq_arn" {
  description = "ARN of the output dead letter queue"
  value       = module.output_queue.dlq_arn
}

output "output_dlq_url" {
  description = "URL of the output dead letter queue"
  value       = module.output_queue.dlq_url
}

output "output_queue_visibility_timeout" {
  description = "Visibility timeout of the output queue"
  value       = var.queue_config.output_queue_visibility_timeout
}