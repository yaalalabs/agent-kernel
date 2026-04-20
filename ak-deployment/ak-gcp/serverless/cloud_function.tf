# Service account for Cloud Run — like an IAM role in AWS
resource "google_service_account" "function_sa" {
  project      = var.project_id
  account_id   = local.sa_id
  display_name = "Cloud Run SA for ${var.product_alias}-${var.env_alias}"
}

# Let the service write logs to Cloud Logging
resource "google_project_iam_member" "function_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

# Let the service read/write Firestore if enabled
resource "google_project_iam_member" "function_firestore" {
  count   = var.create_firestore_database ? 1 : 0
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.function_sa.email}"
}

# Cleanup script that runs on destroy to delete phantom firewall rules left
# behind by GCP when the VPC connector is deleted. Without this, the VPC
# cannot be deleted and terraform destroy gets stuck.
resource "null_resource" "connector_cleanup" {
  triggers = {
    project_id     = var.project_id
    connector_name = local.connector_name
    network_name   = local.network_name != null ? local.network_name : ""
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      # Delete phantom firewall rules left by the VPC connector
      for fw in $(gcloud compute firewall-rules list \
        --project=${self.triggers.project_id} \
        --filter="name~${self.triggers.connector_name}" \
        --format="value(name)" 2>/dev/null); do
        echo "Deleting phantom firewall rule: $fw"
        gcloud compute firewall-rules delete "$fw" \
          --project=${self.triggers.project_id} --quiet 2>/dev/null || true
      done
      # Delete auto-generated default routes that block VPC deletion
      if [ -n "${self.triggers.network_name}" ]; then
        for rt in $(gcloud compute routes list \
          --project=${self.triggers.project_id} \
          --filter="network.name=${self.triggers.network_name} AND nextHopGateway~default-internet-gateway" \
          --format="value(name)" 2>/dev/null); do
          echo "Deleting auto-generated route: $rt"
          gcloud compute routes delete "$rt" \
            --project=${self.triggers.project_id} --quiet 2>/dev/null || true
        done
      fi
    EOT
  }
}

# VPC connector — lets Cloud Run talk to private resources (Redis, etc.)
resource "google_vpc_access_connector" "connector" {
  name          = local.connector_name
  project       = var.project_id
  region        = var.region
  network       = local.network_id
  ip_cidr_range = var.connector_cidr

  min_instances = 2
  max_instances = var.is_production ? 10 : 3
}

# Firewall rule — allow traffic from the VPC connector to reach private resources
# (e.g. Redis/Memorystore). Without this, Cloud Run → connector → Redis is blocked.
resource "google_compute_firewall" "allow_connector" {
  name    = "${local.prefix}-allow-connector"
  project = var.project_id
  network = local.network_id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  source_ranges = [var.connector_cidr]
}

# Cloud Run service — GCP equivalent of AWS Lambda Image type.
# Scales to zero by default (min_instance_count = 0) giving serverless behaviour:
# no idle cost, cold starts on first request after inactivity.
resource "google_cloud_run_v2_service" "service" {
  name               = local.service_name
  project            = var.project_id
  location           = var.region
  deletion_protection = false

  launch_stage = "GA"

  template {
    service_account = google_service_account.function_sa.email

    timeout = "${var.timeout}s"

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = var.max_instance_count
    }

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      name  = local.prefix
      image = module.docker_image.image_url

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      startup_probe {
        http_get {
          path = var.health_check_endpoint
          port = var.container_port
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = var.health_check_endpoint
          port = var.container_port
        }
        period_seconds = 30
      }

      # Environment variables — merge user vars with Redis/Firestore config
      dynamic "env" {
        for_each = merge(
          var.environment_variables,
          {
            API_BASE_PATH  = var.api_base_path
            API_VERSION    = var.api_version
            AGENT_ENDPOINT = var.agent_endpoint
          },
          local.redis_url != null ? {
            AK_SESSION__REDIS__URL = local.redis_url
          } : {},
          local.firestore_db_name != null ? {
            AK_SESSION__FIRESTORE__DATABASE = local.firestore_db_name
            AK_SESSION__FIRESTORE__PROJECT  = var.project_id
          } : {}
        )
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  labels = var.tags

  depends_on = [
    google_project_iam_member.function_logging,
  ]
}

# Configure log retention on the project's default Cloud Logging bucket.
# GCP logs to Cloud Logging automatically — this sets how long logs are kept.
# Equivalent of aws_cloudwatch_log_group retention_in_days in AWS.
resource "google_logging_project_bucket_config" "default_logs" {
  count          = var.log_retention_days != null ? 1 : 0
  project        = var.project_id
  location       = "global"
  retention_days = var.log_retention_days
  bucket_id      = "_Default"
}

# Allow any caller to invoke the Cloud Run service directly.
# Note: this makes the Cloud Run URL publicly accessible, bypassing the API Gateway.
# Authentication is enforced at the API Gateway level (JWT authorizer). For stricter
# network-level isolation, restrict this to the API Gateway service agent and use VPC controls.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
