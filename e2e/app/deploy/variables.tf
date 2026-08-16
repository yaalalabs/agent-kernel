variable "region" {
  type        = string
  description = "Region"
  default     = "us-east-2"
}

variable "product_alias" {
  type        = string
  description = "Product alias"
}

variable "env_alias" {
  type        = string
  description = "Environment alias"
}

variable "module_name" {
  type        = string
  description = "module name"
}

variable "is_production" {
  description = "Is production"
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC ID for ECS deployment. If null, a new VPC is created"
  type        = string
  default     = null
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS deployment (required when vpc_id is set)"
  type        = list(string)
  default     = null
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
  sensitive   = true
}

variable "slack_bot_token" {
  description = "Slack bot token (xoxb-...) of the e2e test Slack app"
  type        = string
  sensitive   = true
}

variable "slack_signing_secret" {
  description = "Slack signing secret of the e2e test Slack app"
  type        = string
  sensitive   = true
}

variable "telegram_bot_token" {
  description = "Telegram bot token (from BotFather) of the e2e test bot"
  type        = string
  sensitive   = true
}

variable "telegram_webhook_secret" {
  description = "Secret token passed to Telegram setWebhook and verified on every webhook delivery. Empty disables verification"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gmail_client_id" {
  description = "Google OAuth client ID for the bot Gmail account. Empty disables the Gmail integration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gmail_client_secret" {
  description = "Google OAuth client secret for the bot Gmail account"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gmail_token_b64" {
  description = "Base64-encoded token.pickle of the bot Gmail account (generate with e2e/tests/scripts/gmail_login.py)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gmail_sender_filter" {
  description = "Only process emails from these comma-separated senders (set to the tester address so stray mail is ignored)"
  type        = string
  default     = ""
}

variable "whatsapp_access_token" {
  description = "WhatsApp Cloud API access token of the BOT Meta app. Empty disables the WhatsApp integration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "whatsapp_phone_number_id" {
  description = "Phone number ID of the bot's WhatsApp business number"
  type        = string
  default     = ""
}

variable "whatsapp_verify_token" {
  description = "Self-chosen token entered when registering the webhook in the Meta app dashboard"
  type        = string
  sensitive   = true
  default     = ""
}

variable "whatsapp_app_secret" {
  description = "Meta app secret for webhook signature verification. Empty disables signature checks"
  type        = string
  sensitive   = true
  default     = ""
}

variable "messenger_access_token" {
  description = "Facebook Page access token for the bot Page. Empty disables the Messenger integration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "messenger_verify_token" {
  description = "Self-chosen token entered when registering the Messenger webhook in the Meta app dashboard"
  type        = string
  sensitive   = true
  default     = ""
}

variable "messenger_app_secret" {
  description = "Meta app secret for Messenger webhook signature verification. Empty disables signature checks"
  type        = string
  sensitive   = true
  default     = ""
}

variable "instagram_access_token" {
  description = "Instagram Business access token. Empty disables the Instagram integration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "instagram_verify_token" {
  description = "Self-chosen token entered when registering the Instagram webhook in the Meta app dashboard"
  type        = string
  sensitive   = true
  default     = ""
}

variable "instagram_app_secret" {
  description = "Meta app secret for Instagram webhook signature verification. Empty disables signature checks"
  type        = string
  sensitive   = true
  default     = ""
}

variable "instagram_account_id" {
  description = "Instagram Business Account ID (optional; not required to send)"
  type        = string
  default     = ""
}
