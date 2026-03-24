data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

data "aws_caller_identity" "current" {}

data "aws_ecr_authorization_token" "token" {}

locals {
  lambda_kms_key_arn                    = null
  cloudwatch_kms_key_arn                = null
  lambda_signer_profile_name            = "sample_profile"
  lambda_signing_config_arn             = null
  vpc_id                                = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr                              = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids                            = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_url                             = var.create_redis_cluster == true ? module.redis[0].url : null
  dynamodb_memory_table_arn             = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_arn : null
  dynamodb_memory_table_name            = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_name : null
  dynamodb_multimodal_memory_table_arn  = var.create_dynamodb_multimodal_memory_table == true ? module.dynamodb_multimodal_memory[0].table_arn : null
  dynamodb_multimodal_memory_table_name = var.create_dynamodb_multimodal_memory_table == true ? module.dynamodb_multimodal_memory[0].table_name : null
  create_authorizer                     = var.authorizer != null ? (var.authorizer.function_name != null && var.authorizer.handler_path != null && var.authorizer.package_type != null && var.authorizer.package_path != null && var.authorizer.module_name != null) : false

  #TODO:: check conditions and remove unwanted stuff

  # Response handler condition checks
  is_async_mode         = var.execution_mode == "async"
  create_response_store = var.scalable_mode && !local.is_async_mode && var.response_store != null

  # Helper conditions for checking if configs exist
  has_redis_config    = local.create_response_store && var.response_store.redis != null
  has_dynamodb_config = local.create_response_store && var.response_store.dynamodb != null

  # Response store creation conditions - create new resources only if URL/ARN not provided
  create_redis_response_store    = local.has_redis_config && var.response_store.redis.url == null
  create_dynamodb_response_store = local.has_dynamodb_config && var.response_store.dynamodb.table_arn == null

  # Computed response store values - use created resources or provided values
  response_store_redis_url = (
    local.create_redis_response_store
    ? module.response_stores[0].redis_url
    : (local.has_redis_config ? var.response_store.redis.url : null)
  )
  response_store_dynamodb_table_name = (
    local.create_dynamodb_response_store
    ? module.response_stores[0].dynamodb_table_name
    : (local.has_dynamodb_config ? var.response_store.dynamodb.table_name : null)
  )
  response_store_dynamodb_table_arn = (
    local.create_dynamodb_response_store
    ? module.response_stores[0].dynamodb_table_arn
    : (local.has_dynamodb_config ? var.response_store.dynamodb.table_arn : null)
  )

  # Response handler response_store configuration
  response_handler_response_store = local.create_response_store ? {
    redis = local.has_redis_config ? {
      prefix = var.response_store.redis.prefix
      url    = local.response_store_redis_url
      ttl    = var.response_store.redis.ttl
    } : null
    dynamodb = local.has_dynamodb_config ? {
      table_name = local.response_store_dynamodb_table_name
      table_arn  = local.response_store_dynamodb_table_arn
      ttl        = var.response_store.dynamodb.ttl
    } : null
  } : null

  # Authorizer status message for logging
  authorizer_required_vars_text = join(", ", compact(["authorizer_function_name", "authorizer_handler_path", "authorizer_package_type", "authorizer_package_path", "authorizer_module_name"]))
  authorizer_status_message     = local.create_authorizer ? format("Created Authorizer Lambda: All required variables are present (%s)", local.authorizer_required_vars_text) : format("Did NOT create Authorizer Lambda: Missing one or more required variables (%s)", local.authorizer_required_vars_text)

  # Queue configuration with defaults
  queue_config = var.queue_config != null ? var.queue_config : {}

  # Input queue
  input_queue_url = var.scalable_mode ? module.queues[0].input_queue_url : null
  input_queue_arn = var.scalable_mode ? module.queues[0].input_queue_arn : null

  # Output queue
  output_queue_url = var.scalable_mode ? module.queues[0].output_queue_url : null
  output_queue_arn = var.scalable_mode ? module.queues[0].output_queue_arn : null

  # Endpoint configuration for API Gateway module
  chat_endpoint = [
    {
      path   = var.agent_endpoint
      method = "POST"
    }
  ]
  complete_gateway_endpoints = concat(
    local.chat_endpoint,
    var.gateway_endpoints
  )
}