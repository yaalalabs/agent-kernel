# ---------- Queue Mode Resources ----------
# This file orchestrates SQS queues, agent runner, and related resources for queue-based execution

# ---------- SQS Queues Module ----------

module "queues" {
  count  = var.enable_queue_mode ? 1 : 0
  source = "./modules/queues"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name

  queue_config = var.queue_config

  tags = var.tags
}

# ---------- Agent Runner Module ----------

module "agent_runner" {
  count  = var.enable_queue_mode ? 1 : 0
  source = "./modules/agent-runner"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  region        = var.region
  prefix        = local.prefix

  vpc_id     = local.vpc_id
  subnet_ids = local.subnet_ids

  ecs_cluster_arn  = module.ecs.cluster_arn
  ecs_cluster_name = module.ecs.cluster_name

  input_queue_url  = module.queues[0].input_queue_url
  input_queue_arn  = module.queues[0].input_queue_arn
  output_queue_url = module.queues[0].output_queue_url
  output_queue_arn = module.queues[0].output_queue_arn

  redis_url                  = local.redis_url
  dynamodb_memory_table_arn  = local.dynamodb_memory_table_arn
  dynamodb_memory_table_name = local.dynamodb_memory_table_name

  agent_runner   = {
    cpu                   = var.agent_runner.cpu
    memory                = var.agent_runner.memory
    desired_count         = var.agent_runner.desired_count
    # Use agent_runner image if package_path provided, else use image_uri, else fallback to rest_service image
    image_uri             = var.agent_runner.package_path != null ? module.agent_runner_docker_image[0].docker_image_uri : (var.agent_runner.image_uri != null ? var.agent_runner.image_uri : module.docker_image[0].docker_image_uri)
    command               = var.agent_runner.command
    environment_variables = merge(var.environment_variables, var.agent_runner.environment_variables)
  }
  queue_config   = var.queue_config
  scaling_config = var.scaling_config

  default_image_uri = module.docker_image[0].docker_image_uri

  account_id = data.aws_caller_identity.current.account_id

  tags = var.tags
}
