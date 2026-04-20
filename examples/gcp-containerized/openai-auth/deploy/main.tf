# Cloud Run (containerized) module configuration for deploying OpenAI Agent with authentication.
#
# GCP equivalent of AWS Lambda Authorizer — auth is enforced at the API Gateway level
# using Google Identity Tokens (OIDC). The gateway validates the JWT against Google's
# public keys before forwarding to Cloud Run, so no auth code is needed in the app.
#
# AWS:  Client → API Gateway → Lambda Authorizer (custom code) → Lambda (app)
# GCP:  Client → API Gateway (ESPv2 JWT validation) → Cloud Run (app)
#
# Endpoints exposed via API Gateway:
# /api/v1/chat     - Agent execution (requires valid Google Identity Token)
# /api/v1/app      - Custom GET endpoint (requires valid Google Identity Token)
# /api/v1/app_info - Custom POST endpoint (requires valid Google Identity Token)
module "containerized_agents" {
  source = "../../../../ak-deployment/ak-gcp/containerized"
  # source  = "yaalalabs/ak-containerized/google"  # uncomment for registry
  # version = "0.2.14"                             # uncomment for registry

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
  product_display_name = "AK OpenAI Auth Containerized Example"
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

  # Environment variables passed to container
  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }

  # JWT authorizer — GCP equivalent of AWS Lambda Authorizer.
  # API Gateway (ESPv2) validates Google Identity Tokens before forwarding to Cloud Run.
  # Clients must pass: Authorization: Bearer $(gcloud auth print-identity-token)
  authorizer = {
    issuer    = "https://accounts.google.com"
    jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"
    # User identity tokens from `gcloud auth print-identity-token` use the gcloud SDK client ID as audience.
    # For service-to-service auth (service account tokens), use the Cloud Run service URL instead.
    audiences = ["32555940559.apps.googleusercontent.com"]
  }
}
