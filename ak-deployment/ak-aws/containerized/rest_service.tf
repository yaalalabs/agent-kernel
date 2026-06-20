# ---------- REST Service Module ----------
# Manages the main ECS service that handles HTTP requests

module "rest_service" {
  source = "./modules/rest-service"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  region        = var.region
  prefix        = local.prefix

  vpc_id     = local.vpc_id
  vpc_cidr   = local.vpc_cidr
  subnet_ids = local.subnet_ids

  ecs_cluster_arn = module.ecs.cluster_arn

  service_name   = local.service_name
  container_name = local.container_name

  redis_url                  = local.redis_url
  dynamodb_memory_table_arn  = local.dynamodb_memory_table_arn
  dynamodb_memory_table_name = local.dynamodb_memory_table_name

  rest_service = {
    cpu                   = var.rest_service.cpu
    memory                = var.rest_service.memory
    desired_count         = var.rest_service.desired_count
    container_port        = var.rest_service.container_port
    health_check_endpoint = var.rest_service.health_check_endpoint
    image_uri             = var.rest_service.image_uri != null ? var.rest_service.image_uri : module.docker_image[0].docker_image_uri
    command               = var.rest_service.command
    environment_variables = merge(var.environment_variables, var.rest_service.environment_variables)
  }

  enable_queue_mode         = var.enable_queue_mode
  input_queue_url           = var.enable_queue_mode ? module.queues[0].input_queue_url : null
  output_queue_url          = var.enable_queue_mode ? module.queues[0].output_queue_url : null
  response_store_table_name = var.enable_queue_mode ? aws_dynamodb_table.response_store[0].name : null

  tags = var.tags
}

# ---------- ECS Cluster ----------

module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "6.10.0"

  cluster_name = "${var.product_alias}-${var.env_alias}-${var.module_name}"

  tags = var.tags
}
