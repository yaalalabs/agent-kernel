# Lambda module configuration for deploying GOogle Agent Lambda function
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-aws/serverless"
  # version = "0.1.0-a2"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  function_description = "Agent Kernel Google Sample Lambda"
  function_name        = "google-agents"
  handler_path         = "lambda.handler"
  module_name          = var.module_name
  package_path         = "../dist"
  package_type         = "Image"
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  memory_size          = 512
  timeout              = 60
  product_display_name = "AK Google Serverless Example"

  # Environment variables passed to lambda
  environment_variables = {
    OPENAI_API_KEY     = var.openai_api_key,
    GOOGLE_STORAGE_DIR = "/tmp/google",
    HOME               = "/tmp"
  }
}
