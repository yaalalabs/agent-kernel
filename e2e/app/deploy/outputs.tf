locals {
  webhook_base_url = "https://${module.e2e_agents.api_gateway_id}.execute-api.${var.region}.amazonaws.com/${module.e2e_agents.api_gateway_stage}"
}

output "agent_invoke_url" {
  description = "The URL to invoke the agent directly via the REST API"
  value       = module.e2e_agents.agent_invoke_url
}

output "slack_events_url" {
  description = "Request URL to configure under the Slack app's Event Subscriptions"
  value       = "${local.webhook_base_url}/api/v1/slack/events"
}

output "telegram_webhook_url" {
  description = "URL to register with the Telegram Bot API setWebhook method"
  value       = "${local.webhook_base_url}/api/v1/telegram/webhook"
}

output "whatsapp_webhook_url" {
  description = "Callback URL to register under the Meta app's WhatsApp webhook configuration"
  value       = "${local.webhook_base_url}/api/v1/whatsapp/webhook"
}

output "messenger_webhook_url" {
  description = "Callback URL to register under the Meta app's Messenger webhook configuration"
  value       = "${local.webhook_base_url}/api/v1/messenger/webhook"
}

output "instagram_webhook_url" {
  description = "Callback URL to register under the Meta app's Instagram webhook configuration"
  value       = "${local.webhook_base_url}/api/v1/instagram/webhook"
}
