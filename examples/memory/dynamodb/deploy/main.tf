# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.2.13"

  # Basic lambda configuration
  product_alias                = var.product_alias
  env_alias                    = var.env_alias
  function_description         = "Agent Kernel OpenAI with DynamoDB"
  function_name                = "oai-ddb"
  handler_path                 = "lambda.handler"
  module_name                  = var.module_name
  package_path                 = "../dist.zip"
  memory_size                  = 256
  product_display_name         = "Agent Kernel OpenAI with DynamoDB"
  create_dynamodb_memory_table = true
  vpc_id                       = "vpc-09033229d67314c1c"
  private_subnet_ids           = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  region                       = var.region

  # Environment variables passed to lambda
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
