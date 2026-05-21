module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.2.14"

  # Basic Cloud Run configuration
  project_id           = var.project_id
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  memory               = "512Mi"
  timeout              = 120
  backend_deadline     = 110
  create_redis_cluster = true
  product_display_name = "AK OpenAI Auth Serverless Example"
  region               = var.region
  container_port       = 8000

  # Defining custom API endpoints
  gateway_endpoints = [
    {
      path           = "app"
      method         = "GET"
      overwrite_path = "/app"
    },
    {
      path           = "app_info"
      method         = "POST"
      overwrite_path = "/app_info"
    }
  ]

  # Environment variables passed to Cloud Run
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }

  # JWT authorizer — GCP equivalent of AWS Lambda Authorizer.
  # API Gateway (ESPv2) validates Google Identity Tokens before forwarding to Cloud Run.
  # Clients must pass: Authorization: Bearer $(gcloud auth print-identity-token --audiences=<service_url>)
  authorizer = {
    issuer    = "https://accounts.google.com"
    jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"
    # User identity tokens from `gcloud auth print-identity-token` use the gcloud SDK client ID as audience.
    # For service-to-service auth (service account tokens), use the Cloud Run service URL instead.
    audiences = ["32555940559.apps.googleusercontent.com"]
  }
}
