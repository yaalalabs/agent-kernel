output "docker_image_uri" {
  description = "Full image URI including tag"
  value       = local.image_url
}

# Alias used by Cloud Run (cloud_run.tf references module.docker_image.image_url)
output "image_url" {
  description = "Full image URI including tag (alias for docker_image_uri)"
  value       = local.image_url
}

output "repository_id" {
  description = "Artifact Registry repository ID"
  value       = google_artifact_registry_repository.repo.repository_id
}

output "repository_url" {
  description = "Artifact Registry repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${local.repo_name}"
}
