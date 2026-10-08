output "agent_invoke_url" {
  description = "POST to this URL to chat with the agent (send the demo bearer token)"
  value       = module.serverless_agents.agent_invoke_url
}

output "slack_events_url" {
  description = "Paste this into the Slack app's Event Subscriptions > Request URL"
  value       = "${trimsuffix(module.serverless_agents.agent_invoke_url, "/chat")}/slack/events"
}
