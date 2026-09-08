# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.0"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  product_alias         = var.product_alias
  env_alias             = var.env_alias
  module_name           = var.module_name
  product_display_name  = "Agent Kernel OpenAI with Valkey"
  create_valkey_cluster = true # Creates an ElastiCache for Valkey cluster and injects AK_SESSION__VALKEY__URL. Set to false to reuse an existing Valkey host configured in config.yaml instead.
  vpc_id                = var.vpc_id
  private_subnet_ids    = var.private_subnet_ids
  security_group_id     = var.security_group_id
  region                = var.region

  # Request handler configuration
  request_handler = {
    function_description = "Agent Kernel OpenAI with Valkey"
    function_name        = "oai-valkey"
    handler_path         = "lambda.handler"
    module_name          = var.module_name
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 512
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }
}
