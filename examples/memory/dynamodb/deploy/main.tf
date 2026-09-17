# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.1"

  providers = { aws = aws, docker = docker }
  # Basic lambda configuration
  prefix                       = var.prefix
  product_display_name         = "Agent Kernel OpenAI with DynamoDB"
  create_dynamodb_memory_table = true
  vpc_id                       = var.vpc_id
  private_subnet_ids           = var.private_subnet_ids
  region                       = var.region

  # Request handler configuration
  request_handler = {
    function_description = "Agent Kernel OpenAI with DynamoDB"
    function_name        = "oai-ddb"
    handler_path         = "lambda.handler"
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 512
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }
}
