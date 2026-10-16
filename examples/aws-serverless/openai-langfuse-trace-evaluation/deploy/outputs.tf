output "agent_invoke_url" {
  description = "The URL to invoke the agent lambda function"
  value       = module.serverless_agents.agent_invoke_url
}

output "results_table_name" {
  description = "DynamoDB table holding one evaluation row per trace"
  value       = aws_dynamodb_table.results.name
}
