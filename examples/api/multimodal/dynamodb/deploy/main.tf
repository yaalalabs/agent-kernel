
# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.3.3"

  # Basic lambda configuration
  product_alias                           = var.product_alias
  env_alias                               = var.env_alias
  module_name                             = var.module_name
  create_dynamodb_multimodal_memory_table = true
  product_display_name                    = "Agent Kernel OpenAI Multimodal with DynamoDB"
  region                                  = var.region

  # Request handler configuration
  request_handler = {
    function_description = "Agent Kernel OpenAI Multimodal with DynamoDB"
    function_name        = "mm-ddb"
    handler_path         = "lambda.handler" # Set dummy valid file to skip validaton inside zip
    module_name          = var.module_name
    package_path         = "../dist"
    package_type         = "Image"
    memory_size          = 2048
    timeout              = 60
    environment_variables = {
      "OPENAI_API_KEY" = var.openai_api_key
    }
  }
}
