output "agent_invoke_url" {
  description = "POST to this URL to chat with the agent; the thread routes live beside it"
  value       = module.serverless_agents.agent_invoke_url
}

output "threads_url" {
  description = "GET this URL (with a demo bearer token) to list threads; append /<session_id> to read one"
  value       = "${trimsuffix(module.serverless_agents.agent_invoke_url, "/chat")}/threads"
}
