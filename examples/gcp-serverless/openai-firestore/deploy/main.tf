# Cloud Run (serverless) module configuration for deploying OpenAI Agent with Firestore session storage.
#
# Uses Firestore as the session backend (GCP equivalent of DynamoDB for AWS Lambda).
# Session data is stored as Firestore documents — one document per session_id,
# with each session key stored as a field on that document.
#
# Endpoints exposed via API Gateway:
# /api/v1/chat - Agent execution
# /api/v1/app  - Custom GET endpoint
module "serverless_agents" {
  source = "../../../../ak-deployment/ak-gcp/serverless"
  # source  = "yaalalabs/ak-serverless/google"  # uncomment for registry
  # version = "0.2.14"                          # uncomment for registry

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
  container_port       = 8080

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
