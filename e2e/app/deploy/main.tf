# Containerized module configuration for the Agent Kernel messaging e2e test deployment.
# Deploys a single ECS service running one OpenAI agent with the Slack and Telegram
# integrations enabled, fronted by an HTTPS API Gateway so both platforms can deliver
# webhooks:
#   POST {invoke_url}/api/v1/slack/events      -> /slack/events      (Slack Events API request URL)
#   POST {invoke_url}/api/v1/telegram/webhook  -> /telegram/webhook  (Telegram setWebhook URL)
module "e2e_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.8.0"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  container_type       = "ecs"
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Messaging Integrations E2E"

  gateway_endpoints = [
    {
      path           = "slack/events",
      method         = "POST",
      overwrite_path = "/slack/events"
    },
    {
      path           = "telegram/webhook",
      method         = "POST",
      overwrite_path = "/telegram/webhook"
    },
    {
      path           = "whatsapp/webhook",
      method         = "GET",
      overwrite_path = "/whatsapp/webhook"
    },
    {
      path           = "whatsapp/webhook",
      method         = "POST",
      overwrite_path = "/whatsapp/webhook"
    },
    {
      # Messenger webhook verification (Meta sends GET with hub.* query params)
      path           = "messenger/webhook",
      method         = "GET",
      overwrite_path = "/messenger/webhook"
    },
    {
      path           = "messenger/webhook",
      method         = "POST",
      overwrite_path = "/messenger/webhook"
    },
    {
      # Instagram webhook verification (Meta sends GET with hub.* query params)
      path           = "instagram/webhook",
      method         = "GET",
      overwrite_path = "/instagram/webhook"
    },
    {
      path           = "instagram/webhook",
      method         = "POST",
      overwrite_path = "/instagram/webhook"
    },
    {
      path           = "teams/messages",
      method         = "POST",
      overwrite_path = "/teams/messages"
    }
  ]

  rest_service = {
    package_path   = "../dist"
    container_port = 8000
    environment_variables = {
      OPENAI_API_KEY                     = var.openai_api_key
      SLACK_BOT_TOKEN                    = var.slack_bot_token
      SLACK_SIGNING_SECRET               = var.slack_signing_secret
      AK_TELEGRAM__BOT_TOKEN             = var.telegram_bot_token
      AK_TELEGRAM__WEBHOOK_SECRET        = var.telegram_webhook_secret
      AK_GMAIL__CLIENT_ID                = var.gmail_client_id
      AK_GMAIL__CLIENT_SECRET            = var.gmail_client_secret
      AK_GMAIL__TOKEN_B64                = var.gmail_token_b64
      AK_GMAIL__SENDER_FILTER            = var.gmail_sender_filter
      AK_WHATSAPP__ACCESS_TOKEN          = var.whatsapp_access_token
      AK_WHATSAPP__PHONE_NUMBER_ID       = var.whatsapp_phone_number_id
      AK_WHATSAPP__VERIFY_TOKEN          = var.whatsapp_verify_token
      AK_WHATSAPP__APP_SECRET            = var.whatsapp_app_secret
      AK_MESSENGER__ACCESS_TOKEN         = var.messenger_access_token
      AK_MESSENGER__VERIFY_TOKEN         = var.messenger_verify_token
      AK_MESSENGER__APP_SECRET           = var.messenger_app_secret
      AK_INSTAGRAM__ACCESS_TOKEN         = var.instagram_access_token
      AK_INSTAGRAM__VERIFY_TOKEN         = var.instagram_verify_token
      AK_INSTAGRAM__APP_SECRET           = var.instagram_app_secret
      AK_INSTAGRAM__INSTAGRAM_ACCOUNT_ID = var.instagram_account_id
      AK_TEAMS__APP_ID                   = var.teams_app_id
      AK_TEAMS__APP_PASSWORD             = var.teams_app_password
      AK_TEAMS__TENANT_ID                = var.teams_tenant_id
    }
  }
}
