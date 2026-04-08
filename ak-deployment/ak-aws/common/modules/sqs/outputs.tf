output "queue_url" {
  description = "URL of the main SQS queue"
  value       = module.sqs_queue.queue_url
}

output "queue_arn" {
  description = "ARN of the main SQS queue"
  value       = module.sqs_queue.queue_arn
}

output "queue_name" {
  description = "Name of the main SQS queue"
  value       = module.sqs_queue.queue_name
}

output "queue_id" {
  description = "ID of the main SQS queue"
  value       = module.sqs_queue.queue_id
}


output "dlq_url" {
  description = "URL of the dead letter queue"
  value       = var.create_dlq ? module.sqs_queue.dead_letter_queue_url : null
}


output "dlq_arn" {
  description = "ARN of the dead letter queue"
  value       = var.create_dlq ? module.sqs_queue.dead_letter_queue_arn : null
}


output "dlq_name" {
  description = "Name of the dead letter queue"
  value       = var.create_dlq ? module.sqs_queue.dead_letter_queue_name : null
}


output "dlq_id" {
  description = "ID of the dead letter queue"
  value       = var.create_dlq ? module.sqs_queue.dead_letter_queue_id : null
}