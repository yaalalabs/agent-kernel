module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.9.5"

  providers = { google = google, google-beta = google-beta, docker = docker }
  # Basic Cloud Run configuration
  project_id   = var.project_id
  prefix       = var.prefix
  package_path = "../dist"
  # This example runs its agents inside the one Cloud Run service (RESTAPI.run in app.py).
  # Queue mode, the modules' default, needs a queue-mode app: see the openai-queue-mode example.
  queue_mode           = false
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
