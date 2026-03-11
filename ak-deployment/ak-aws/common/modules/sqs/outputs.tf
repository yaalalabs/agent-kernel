output "queue_url" {
  description = "URL of the main SQS FIFO queue"
  value       = module.main.queue_url
}

output "queue_arn" {
  description = "ARN of the main SQS FIFO queue"
  value       = module.main.queue_arn
}

output "queue_name" {
  description = "Name of the main SQS FIFO queue"
  value       = module.main.queue_name
}

output "dlq_url" {
  description = "URL of the dead letter queue"
  value       = module.main.dlq_url
}

output "dlq_arn" {
  description = "ARN of the dead letter queue"
  value       = module.main.dlq_arn
}

output "dlq_name" {
  description = "Name of the dead letter queue"
  value       = module.main.dlq_name
}

output "queue_id" {
  description = "ID of the main SQS FIFO queue"
  value       = module.main.queue_id
}

output "dlq_id" {
  description = "ID of the dead letter queue"
  value       = module.main.dlq_id
}