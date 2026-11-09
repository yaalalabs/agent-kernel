# Queue mode on Cloud Run (serverless). The module deploys two services from one image:
# - the edge (the image's CMD, app.main -> CloudRun.run()): /api/v1/chat publishes each request to
#   Pub/Sub and answers with the reply once it is stored in Memorystore;
# - the agent runner (agent_runner.command, app.runner -> CloudRunAgentRunner.run()): a private
#   service Pub/Sub pushes each request to. It runs the agents and publishes the reply.
# Both scale to zero. queue_mode is the module's default; Memorystore is created as the reply store.
module "serverless_agents" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.9.5"

  providers = { google = google, google-beta = google-beta, docker = docker }

  project_id           = var.project_id
  prefix               = var.prefix
  region               = var.region
  package_path         = "../dist"
  container_port       = 8000
  memory               = "512Mi"
  product_display_name = "AK OpenAI Queue Mode Example"

  queue_mode     = true # the default, shown for clarity
  execution_mode = "rest_sync"

  # A request waits for its reply, which includes a cold start of the runner after a quiet spell.
  # config.yaml's response store waits up to 100 s, inside this 110 s gateway deadline.
  timeout          = 120
  backend_deadline = 110

  agent_runner = {
    # The same image, with its own entry point.
    command            = ["python", "-c", "from app import runner; runner()"]
    min_instance_count = 0 # scale to zero between requests
    max_instance_count = 3
  }

  environment_variables = {
    "OPENAI_API_KEY" = var.openai_api_key
  }
}
