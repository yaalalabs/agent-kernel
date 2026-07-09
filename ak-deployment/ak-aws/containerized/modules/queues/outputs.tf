output "input_queue_arn" {
  description = "ARN of the input queue"
  value       = module.input_queue.queue_arn
}

output "input_queue_url" {
  description = "URL of the input queue"
  value       = module.input_queue.queue_url
}

output "output_queue_arn" {
  description = "ARN of the output queue"
  value       = module.output_queue.queue_arn
}

output "output_queue_url" {
  description = "URL of the output queue"
  value       = module.output_queue.queue_url
}
