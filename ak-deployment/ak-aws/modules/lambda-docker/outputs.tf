output "docker_image_uri" {
  description = "The ECR Docker image URI used to deploy Lambda Function"
  value       = module.docker_build_from_ecr.image_uri
}