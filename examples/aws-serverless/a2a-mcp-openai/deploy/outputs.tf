output "agent_invoke_url" {
  description = "The chat route. The integration test derives every other URL from it"
  value       = module.serverless_agents.agent_invoke_url
}

output "public_base_url" {
  description = "Public URL of the API up to and including the version: a2a.url and mcp.url are built on it"
  value       = trimsuffix(module.serverless_agents.agent_invoke_url, "/chat")
}

output "a2a_agent_card_url" {
  description = "The assistant's A2A agent card: public, no token needed"
  value       = "${trimsuffix(module.serverless_agents.agent_invoke_url, "/chat")}/a2a/assistant/.well-known/agent-card.json"
}

output "mcp_url" {
  description = "The MCP endpoint: send the demo bearer token"
  value       = "${trimsuffix(module.serverless_agents.agent_invoke_url, "/chat")}/mcp/"
}
