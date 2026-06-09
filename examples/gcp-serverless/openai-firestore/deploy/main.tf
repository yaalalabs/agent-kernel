module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.5.0"

  # Basic Cloud Run configuration
  project_id           = var.project_id
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  memory               = "512Mi"
  timeout              = 120
  backend_deadline     = 110
  product_display_name = "AK OpenAI Firestore Serverless Example"
  region               = var.region
  container_port       = 8000

  # Firestore for session storage (GCP equivalent of DynamoDB)
  create_firestore_database = true

  # Defining custom API endpoints
  gateway_endpoints = [
    {
      path           = "app"
      method         = "GET"
      overwrite_path = "/app"
    }
  ]

  # Environment variables passed to Cloud Run
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
