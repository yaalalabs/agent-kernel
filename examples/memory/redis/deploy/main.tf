# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.5"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel OpenAI with Redis"
  function_name        = "oai-redis"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist.zip"
  memory_size          = 256
  create_redis_cluster = false # This is optional. Set to true if you want to create one. Otherwise you can reuse an already existing redis host by setting configurations on config.yaml
  product_display_name = "Agent Kernel OpenAI with Redis"
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  region               = var.region

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
