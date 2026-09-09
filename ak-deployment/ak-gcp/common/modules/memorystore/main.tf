# Memorystore for Redis — GCP's managed Redis service
# Equivalent of ElastiCache (AWS) or Azure Cache for Redis
resource "google_redis_instance" "redis" {
  name           = "${substr("${var.product_alias}-${var.env_alias}-${var.module_name}", 0, min(length("${var.product_alias}-${var.env_alias}-${var.module_name}"), 34))}-redis"
  project        = var.project_id
  region         = var.region
  tier           = var.tier
  memory_size_gb = var.memory_size_gb
  redis_version  = var.redis_version

  # Place the Redis instance inside our VPC
  authorized_network = var.network_id

  # Turn on AUTH so connections need a password
  auth_enabled = var.auth_enabled

  # In-transit encryption — same idea as SSL on ElastiCache
  transit_encryption_mode = "SERVER_AUTHENTICATION"

  labels = var.tags
}

# Enable exportCustomRoutes on the Memorystore peering so the VPC connector
# subnet can reach Redis. Without this, return traffic from Memorystore back
# to the connector is dropped ("connection reset by peer").
# GCP does not expose the peering name as a Terraform attribute, so we
# update it via gcloud after the Redis instance is ready.
resource "null_resource" "redis_peering_export_routes" {
  triggers = {
    redis_id   = google_redis_instance.redis.id
    network    = var.network_id
    project_id = var.project_id
  }

  provisioner "local-exec" {
    command = <<-EOT
      NETWORK_NAME=$(echo "${var.network_id}" | sed 's|.*/||')
      PEERING=$(gcloud compute networks describe "$NETWORK_NAME" \
        --project=${var.project_id} \
        --format='value(peerings[].name)' | tr ';' '\n' | grep '^redis-peer-' | head -1)
      gcloud compute networks peerings update "$PEERING" \
        --network="$NETWORK_NAME" \
        --export-custom-routes \
        --project=${var.project_id}
    EOT
  }

  depends_on = [google_redis_instance.redis]
}
