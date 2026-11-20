# The agent runner of Agent Kernel queue mode: a private Cloud Run service that Pub/Sub pushes each
# request to. Its entry point calls agentkernel.gcp.CloudRunAgentRunner.run(), which runs the agents
# and publishes replies. Cloud Run scales it on those pushes, down to zero.
#
# Accepted trade-off: Pub/Sub waits at most 600 seconds for a push to be answered. An agent run that
# takes longer is redelivered while it is still going, so it runs twice. The service's own request
# timeout is not capped at that: it is Cloud Run's maximum, so a long run is never cut off.

resource "google_cloud_run_v2_service" "runner" {
  name                = local.service_name
  project             = var.project_id
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  # Pub/Sub push from the same project counts as internal traffic; nothing else may reach it.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.runner.email
    labels          = var.labels

    # Cloud Run's maximum, so an agent run is never cut off. Pub/Sub still redelivers a push it has
    # waited 600 seconds for (the accepted trade-off above).
    timeout                          = "3600s"
    max_instance_request_concurrency = var.concurrency

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    # The same connector as the edge service, so the runner reaches Memorystore the same way.
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image   = var.image_url
      command = var.command
      args    = var.args

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # Work happens only inside push requests, so CPU outside them is not needed.
        cpu_idle = true
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 24
      }

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.runner_logging,
    google_pubsub_topic_iam_member.runner_publish,
  ]
}
