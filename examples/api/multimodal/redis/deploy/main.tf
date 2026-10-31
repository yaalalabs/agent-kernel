# Lambda module configuration for deploying Multimodal Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  create_redis_cluster = true
  product_display_name = "Agent Kernel Multimodal with Redis"
  region               = var.region

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  # Terraform creates each parameter holding REPLACE_ME; overwrite it with the real value after the first apply.
  ssm_enabled     = true
  ssm_secret_keys = ["OPENAI_API_KEY"]

  # Request handler configuration
  request_handler = {
    function_description = "Agent Kernel Multimodal with Redis"
    function_name        = "mm-redis"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 2048
    timeout              = 60
  }
}


