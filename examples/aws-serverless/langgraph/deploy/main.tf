# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "../../../../ak-deployment/ak-aws/serverless"
  version = "0.1.0-a2"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel LangGraph Sample Lambda"
  function_name        = "langgraph-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  region               = var.region
  vpc_id               = "vpc-05026dbb802f05202"
  redis_host           = "ak-openai-serverless-dev-examples-redis.qaandw.0001.apse2.cache.amazonaws.com"
  private_subnet_ids   = ["subnet-08fedd7404eaf64e8", "subnet-0f29b45c27e9715a8"]
  memory_size          = 256
  agent_memory_type    = "redis"
  product_display_name = "AK Langraph Serverless Example"

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
