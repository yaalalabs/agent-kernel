terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.8.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
}

# Work out the full path and a hash of the source files
# so we only rebuild when something actually changes
locals {
  source_path   = "${path.root}/${var.source_path}"
  path_include  = ["**"]
  path_exclude  = ["**/__pycache__/**"]
  files_include = setunion([for f in local.path_include : fileset(local.source_path, f)]...)
  files_exclude = setunion([for f in local.path_exclude : fileset(local.source_path, f)]...)
  files         = sort(setsubtract(local.files_include, local.files_exclude))
  dir_sha       = sha1(join("", [for f in local.files : filesha1("${local.source_path}/${f}")]))

  repo_name = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  image_tag = local.dir_sha
  image_url = "${var.region}-docker.pkg.dev/${var.project_id}/${local.repo_name}/${var.module_name}:${local.image_tag}"
}

# Create the Artifact Registry repository (Docker format)
resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = local.repo_name
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-last-30"
    action = "KEEP"

    most_recent_versions {
      keep_count = 30
    }
  }
}

# Build the Docker image locally
resource "docker_image" "image" {
  name = local.image_url

  build {
    context    = local.source_path
    platform   = "linux/amd64"
    dockerfile = "Dockerfile"
  }

  triggers = {
    dir_sha = local.dir_sha
  }
}

# Push the image to Artifact Registry
resource "docker_registry_image" "push" {
  name          = docker_image.image.name
  keep_remotely = true

  triggers = {
    dir_sha = local.dir_sha
  }
}
