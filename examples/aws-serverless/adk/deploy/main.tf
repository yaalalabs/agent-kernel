# Lambda module configuration for deploying Google Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Google ADK Serverless Example"

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  # Terraform creates each parameter holding REPLACE_ME; overwrite it with the real value after the first apply.
  ssm_enabled     = true
  ssm_secret_keys = ["OPENAI_API_KEY"]

  # Request handler configuration
  request_handler = {
    function_name        = "adk-agents"
    function_description = "Agent Kernel ADK Sample Lambda"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 1024
    timeout              = 60
    security_group_id    = var.request_handler_security_group_id
  }
}
