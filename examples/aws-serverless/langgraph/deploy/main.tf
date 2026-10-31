# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Langraph Serverless Example"

  # Secret resolution: grants ssm:GetParameter on /ak/<prefix>/* and injects AK_SECRET__PREFIX, so the app
  # resolves OPENAI_API_KEY from /ak/<prefix>/<key lowercased> (config.yaml `secret:` block)
  ssm_enabled = true

  # Request handler configuration
  request_handler = {
    function_name        = "langgraph-agents"
    function_description = "Agent Kernel LangGraph Sample Lambda"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 1024
    security_group_id    = var.request_handler_security_group_id
  }
}
