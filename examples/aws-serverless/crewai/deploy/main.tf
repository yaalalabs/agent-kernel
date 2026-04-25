# Lambda module configuration for deploying OpenAI Agent Lambda function
module "serverless_agents" {
  source = "yaalalabs/ak-serverless/aws"
  version = "0.3.3"

  # Basic lambda configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  vpc_id               = "vpc-09033229d67314c1c"
  private_subnet_ids   = ["subnet-00e888e445f16d1b1", "subnet-0ab5240262cd77119"]
  product_display_name = "AK CrewAI Serverless Example"

  # Request handler configuration
  request_handler = {
    function_name         = "crewai-agents"
    function_description   = "Agent Kernel CrewAI Sample Lambda"
    handler_path          = "lambda.handler"
    module_name           = var.module_name
    package_path          = "../dist"
    package_type          = "Image"
    memory_size           = 512
    timeout               = 60
    environment_variables = {
      OPENAI_API_KEY     = var.openai_api_key,
      CREWAI_STORAGE_DIR = "/tmp/crewai",
      EMBEDCHAIN_DB_PATH = "/tmp/crewai/embedchain.db",
      HOME               = "/tmp"
    }
  }
}
