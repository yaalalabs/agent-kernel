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
  security_group_id                     = aws_security_group.lambda.id
  security_group_name                   = "${var.product_alias}-${var.env_alias}-lambda-sg"
  redis_url                             = (var.create_redis_cluster == true || var.create_redis_response_store) ? module.redis[0].url : null
  dynamodb_memory_table_arn             = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_arn : null
  dynamodb_memory_table_name            = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_name : null
  dynamodb_multimodal_memory_table_arn  = var.create_dynamodb_multimodal_memory_table == true ? module.dynamodb_multimodal_memory[0].table_arn : null
  dynamodb_multimodal_memory_table_name = var.create_dynamodb_multimodal_memory_table == true ? module.dynamodb_multimodal_memory[0].table_name : null
  
  request_handler_enabled               = var.enable_api_gateway || var.execution_mode == "async"
  request_handler_package_path          = var.package_path
  request_handler_lambda_function_arn   = local.request_handler_enabled ? module.request_handler[0].lambda_function_arn : null
  request_handler_lambda_function_name  = local.request_handler_enabled ? module.request_handler[0].lambda_function_name : null
  request_handler_lambda_invoke_arn     = local.request_handler_enabled ? module.request_handler[0].lambda_function_invoke_arn : null
  request_handler_lambda_role_arn       = local.request_handler_enabled ? module.request_handler[0].lambda_role_arn : null

  websocket_api_enabled                  = var.execution_mode == "async"
  rest_api_enabled                       = var.enable_api_gateway && var.execution_mode != "async"
  
  agent_runner_package_path             = try(var.agent_runner.package_path, null)
  agent_runner_artifact_module_name     = var.agent_runner.module_name
  agent_runner_logs_retention_in_days   = try(var.agent_runner.cloudwatch_logs_retention_in_days, null)

  response_handler_package_path         = try(var.response_handler.package_path, null)
  response_handler_package_type         = try(var.response_handler.package_type, null)
  response_handler_artifact_module_name = var.response_handler.module_name
  response_handler_logs_retention_in_days = try(var.response_handler.cloudwatch_logs_retention_in_days, null)

  create_authorizer                     = var.enable_api_gateway && var.authorizer != null ? (var.authorizer.function_name != null && var.authorizer.handler_path != null && var.authorizer.package_type != null && var.authorizer.package_path != null && var.authorizer.module_name != null) : false
  # Authorizer status message for logging
  authorizer_required_vars_text = join(", ", compact(["function_name", "handler_path", "package_type", "package_path", "module_name"]))
  authorizer_status_message     = !var.enable_api_gateway ? "Did NOT create Authorizer Lambda: enable_api_gateway is false." : (local.create_authorizer ? format("Created Authorizer Lambda: All required variables are present (%s)", local.authorizer_required_vars_text) : format("Did NOT create Authorizer Lambda: Missing one or more required variables (%s)", local.authorizer_required_vars_text))

  # Effective response store creation flags (disabled when execution_mode is async)
  create_dynamodb_response_store_effective = var.create_dynamodb_response_store && var.execution_mode != "async"
  create_redis_response_store_effective     = var.create_redis_response_store && var.execution_mode != "async"

  # DynamoDB response store configuration
  response_store_dynamodb_table_name     = local.create_dynamodb_response_store_effective ? module.dynamodb_response_store[0].table_name : null
  response_store_dynamodb_table_arn      = local.create_dynamodb_response_store_effective ? module.dynamodb_response_store[0].table_arn : null
  response_handler_response_store_dynamodb = local.create_dynamodb_response_store_effective ? {
    table_name = local.response_store_dynamodb_table_name
    table_arn  = local.response_store_dynamodb_table_arn
  } : null
  # Redis response store configuration
  response_store_redis_url            = local.create_redis_response_store_effective ? local.redis_url : null
  response_handler_response_store_redis = local.create_redis_response_store_effective ? {
    url = local.response_store_redis_url
  } : null

  # Input queue
  input_queue_url                = var.queue_mode ? module.queues[0].input_queue_url : null
  input_queue_arn                = var.queue_mode ? module.queues[0].input_queue_arn : null
  input_queue_visibility_timeout = var.queue_mode ? var.queue_config.input_queue_visibility_timeout : null
  # Output queue
  output_queue_url                = var.queue_mode ? module.queues[0].output_queue_url : null
  output_queue_arn                = var.queue_mode ? module.queues[0].output_queue_arn : null
  output_queue_visibility_timeout = var.queue_mode ? var.queue_config.output_queue_visibility_timeout : null

  # Endpoint configuration for API Gateway module
  chat_endpoint = concat(
    [
      {
        path   = var.agent_endpoint
        method = "POST"
      }
    ],
    var.execution_mode == "rest_async" ? [
      {
        path   = var.agent_endpoint
        method = "GET"
      }
    ] : []
  )

  complete_gateway_endpoints = concat(
    local.chat_endpoint,
    var.gateway_endpoints
  )

  agent_invoke_url = try(module.api_gateway[0].agent_invoke_url, null)

  # WebSocket API Gateway locals
  websocket_api_endpoint_url      = try(module.websocket_api_gateway[0].websocket_api_endpoint_url, null)
  websocket_api_endpoint_arn      = try(module.websocket_api_gateway[0].websocket_api_execution_arn, null)
  websocket_connection_table_name = local.websocket_api_enabled ? module.websocket_connections[0].table_name : null
  websocket_connection_table_arn  = local.websocket_api_enabled ? module.websocket_connections[0].table_arn : null
}

resource "aws_security_group" "lambda" {
  name        = local.security_group_name
  description = "Security group for Lambda functions"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = local.security_group_name
  }
}

module "request_handler_source_storage" {
  count                = local.request_handler_enabled ? ((var.package_type == "S3Zip") ? 1 : 0) : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.4.0"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module "request_handler_source_package" {
  count            = local.request_handler_enabled ? ((var.package_type == "S3Zip") ? 1 : 0) : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.4.0"
  env_alias        = var.env_alias
  region           = var.region
  module_name      = var.module_name
  package_dir_path = var.package_path
  product_alias    = var.product_alias
  s3_bucket        = module.request_handler_source_storage[0].source_storage_s3_bucket
  depends_on       = [module.request_handler_source_storage]
}

module "vpc" {
  source               = "yaalalabs/ak-common/aws//modules/vpc"
  version              = "0.4.0"
  count                = var.vpc_id == null ? 1 : 0
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  tags                 = var.tags
}


module "authorizer" {
  count                      = local.create_authorizer ? 1 : 0
  source                     = "yaalalabs/ak-common/aws//modules/authorizer"
  version                    = "0.4.0"
  region                     = var.region
  product_alias              = var.product_alias
  env_alias                  = var.env_alias
  authorizer_info            = var.authorizer
  module_type                = var.module_type
  timeout                    = var.timeout
  memory_size                = var.memory_size
  layers                     = var.layers
  tags                       = var.tags
  vpc_id                     = local.vpc_id
  subnet_ids                 = local.subnet_ids
  security_group_ids         = [local.security_group_id]
  is_production              = var.is_production
  lambda_kms_key_arn         = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn     = local.cloudwatch_kms_key_arn
  lambda_signer_profile_name = local.lambda_signer_profile_name
  lambda_signing_config_arn  = local.lambda_signing_config_arn
}

# Shared API Gateway Resources Module
module "shared_api_gateway_resources" {
  source = "./modules/shared-api-gateway-resources"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  tags          = var.tags
}

module "api_gateway" {
  count  = local.rest_api_enabled ? 1 : 0
  source = "./modules/api-gateway"

  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = var.product_display_name
  api_base_path        = var.api_base_path
  api_version          = var.api_version
  agent_endpoint       = var.agent_endpoint
  tags                 = var.tags

  lambda_function_invoke_arn = local.request_handler_lambda_invoke_arn
  lambda_function_name       = local.request_handler_lambda_function_name

  endpoints = local.complete_gateway_endpoints

  authorizer                            = var.authorizer
  authorizer_lambda_function_name       = local.create_authorizer ? module.authorizer[0].lambda_function_name : ""
  authorizer_lambda_function_invoke_arn = local.create_authorizer ? module.authorizer[0].lambda_function_invoke_arn : ""
  create_authorizer                     = local.create_authorizer

  cloudwatch_kms_key_arn       = local.cloudwatch_kms_key_arn

  depends_on = [module.shared_api_gateway_resources]
}

module "websocket_api_gateway" {
  count  = local.websocket_api_enabled ? 1 : 0
  source = "./modules/websocket-api-gateway"

  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = var.product_display_name
  tags                 = var.tags
  chat_route           = var.ws_chat_route
  custom_routes        = var.ws_routes

  route_handler_lambda_invoke_arn      = local.request_handler_lambda_invoke_arn
  route_handler_lambda_name            = local.request_handler_lambda_function_name
  route_handler_lambda_role_name        = local.request_handler_enabled ? module.request_handler[0].lambda_role_name : null
  connection_handler_lambda_invoke_arn = module.ws_connection_handler[0].ws_connection_handler_lambda_function_invoke_arn
  connection_handler_lambda_name       = module.ws_connection_handler[0].ws_connection_handler_lambda_function_name

  cloudwatch_kms_key_arn     = local.cloudwatch_kms_key_arn

  depends_on = [module.shared_api_gateway_resources]
}

module "docker_image" {
  count         = local.request_handler_enabled ? ((var.package_type == "Image") ? 1 : 0) : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.4.0"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

module "agent_runner_source_storage" {
  count                = (var.agent_runner.package_type == "S3Zip") ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.4.0"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module "agent_runner_source_package" {
  count            = (var.agent_runner.package_type == "S3Zip") ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.4.0"
  env_alias        = var.env_alias
  region           = var.region
  module_name      = local.agent_runner_artifact_module_name
  package_dir_path = local.agent_runner_package_path
  product_alias    = var.product_alias
  s3_bucket        = module.agent_runner_source_storage[0].source_storage_s3_bucket
  depends_on       = [module.agent_runner_source_storage]
}

module "agent_runner_docker_image" {
  count         = (var.agent_runner.package_type == "Image") ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.4.0"
  env_alias     = var.env_alias
  module_name   = local.agent_runner_artifact_module_name
  product_alias = var.product_alias
  source_path   = local.agent_runner_package_path
}

module "response_handler_source_storage" {
  count                = var.queue_mode && local.response_handler_package_type == "S3Zip" ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.4.0"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module "response_handler_source_package" {
  count            = var.queue_mode && local.response_handler_package_type == "S3Zip" ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.4.0"
  env_alias        = var.env_alias
  region           = var.region
  module_name      = local.response_handler_artifact_module_name
  package_dir_path = local.response_handler_package_path
  product_alias    = var.product_alias
  s3_bucket        = module.response_handler_source_storage[0].source_storage_s3_bucket
  depends_on       = [module.response_handler_source_storage]
}

module "response_handler_docker_image" {
  count         = var.queue_mode && local.response_handler_package_type == "Image" ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.4.0"
  env_alias     = var.env_alias
  module_name   = local.response_handler_artifact_module_name
  product_alias = var.product_alias
  source_path   = local.response_handler_package_path
}

module "redis" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.4.0"
  count         = (var.create_redis_cluster == true || local.create_redis_response_store_effective) ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module "dynamodb_memory" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.4.0"
  count   = var.create_dynamodb_memory_table == true ? 1 : 0
  attributes = [
    { name = "session_id", type = "S" },
    { name = "key", type = "S" },
  ]
  hash_key           = "session_id"
  range_key          = "key"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = var.module_name
  product_alias      = var.product_alias
  table_name         = "session_store"
  ttl_attribute_name = "expiry_time"
}

module "dynamodb_multimodal_memory" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.4.0"
  count   = var.create_dynamodb_multimodal_memory_table == true ? 1 : 0
  attributes = [
    { name = "session_id", type = "S" },
    { name = "attachment_id", type = "S" },
  ]
  hash_key           = "session_id"
  range_key          = "attachment_id"
  ttl_enabled        = true
  ttl_attribute_name = "expiry_time"
  env_alias          = var.env_alias
  module_name        = var.module_name
  product_alias      = var.product_alias
  table_name         = "mm-attachments"
}

module "queues" {
  count  = var.queue_mode ? 1 : 0
  source = "./modules/queues"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  tags          = var.tags

  queue_config = var.queue_config
}

# SQS Queues Module (conditional on queue_mode)
check "queue_visibility_timeouts" {
  assert {
    condition = var.queue_mode ? (
      var.queue_config.input_queue_visibility_timeout >= var.agent_runner.timeout &&
      var.queue_config.output_queue_visibility_timeout >= var.response_handler.timeout
    ) : true
    error_message = format(
      "[IMPORTANT] Invalid queue visibility timeout configuration: input queue visibility timeout (%d) must be >= agent runner timeout (%d), and output queue visibility timeout (%d) must be >= response handler timeout (%d).",
      var.queue_config.input_queue_visibility_timeout,
      var.agent_runner.timeout,
      var.queue_config.output_queue_visibility_timeout,
      var.response_handler.timeout,
    )
  }
}

# WebSocket Connections DynamoDB Table
module "websocket_connections" {
  count  = local.websocket_api_enabled ? 1 : 0
  source = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.3.3"
  attributes = [
    { name = "user_id", type = "S" },
    { name = "connection_id", type = "S" }
  ]
  global_secondary_indexes = [
    {
      name            = "connection_id-index"
      hash_key        = "connection_id"
      range_key       = "user_id"
      projection_type = "ALL"
    }
  ]
  hash_key           = "user_id"
  range_key          = "connection_id"
  env_alias          = var.env_alias
  module_name        = "${var.module_name}-websocket-connections"
  product_alias      = var.product_alias
  table_name         = "websocket-connections"
  ttl_enabled        = true
  ttl_attribute_name = "expiry_time"
}

# DynamoDB response store module
module "dynamodb_response_store" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.4.0"
  count   = local.create_dynamodb_response_store_effective ? 1 : 0

  attributes = [
    { name = "request_id", type = "S" },
    { name = "session_id", type = "S" },
  ]

  global_secondary_indexes = [
    {
      name            = "session_id-index"
      hash_key        = "session_id"
      range_key       = "request_id"
      projection_type = "ALL"
    },
  ]

  hash_key           = "request_id"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = "${var.module_name}-response-store"
  product_alias      = var.product_alias
  table_name         = "ak-responses"
  ttl_attribute_name = "expiry_time"
}

module "ws_connection_handler" {
  count  = local.websocket_api_enabled ? 1 : 0
  source = "./modules/ws-connection-handler"
  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_type          = var.module_type
  is_production        = var.is_production
  vpc_id              = local.vpc_id
  subnet_ids          = local.subnet_ids
  security_group_id   = local.security_group_id
  lambda_kms_key_arn     = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn
  ws_connection_handler = merge(var.ws_connection_handler, {
    environment_variables = merge(
      try(var.ws_connection_handler.environment_variables, {}),
      {
        AK_WEBSOCKET_API__CONNECTION_TABLE__TABLE_NAME = local.websocket_connection_table_name
      }
    )
  })
  websocket_connection_table_arn = local.websocket_connection_table_arn
}

# Request Handler Lambda Module
module "request_handler" {
  count                                   = local.request_handler_enabled ? 1 : 0
  source                                  = "./modules/request-handler"
  region                                  = var.region
  product_alias                           = var.product_alias
  product_display_name                    = var.product_display_name
  env_alias                               = var.env_alias
  module_type                             = var.module_type
  module_name                             = var.module_name
  is_production                           = var.is_production
  package_path                            = local.request_handler_package_path
  cloudwatch_logs_retention_in_days       = var.cloudwatch_logs_retention_in_days
  queue_mode                              = var.queue_mode
  event_source_mapping                    = var.event_source_mapping
  timeout                                 = var.timeout
  memory_size                             = var.memory_size
  function_name                           = var.function_name
  function_description                    = var.function_description
  handler_path                            = var.handler_path
  package_type                            = var.package_type
  layers                                  = var.layers
  api_version                             = var.api_version
  agent_endpoint                          = var.agent_endpoint
  api_base_path                           = var.api_base_path
  vpc_id                                  = local.vpc_id
  subnet_ids                              = local.subnet_ids
  security_group_id                       = local.security_group_id
  source_bucket                           = try(module.request_handler_source_storage[0].source_storage_s3_bucket, null)
  create_dynamodb_memory_table            = var.queue_mode ? false : var.create_dynamodb_memory_table
  create_dynamodb_multimodal_memory_table = var.queue_mode ? false : var.create_dynamodb_multimodal_memory_table
  redis_url                               = var.queue_mode ? null : local.redis_url
  dynamodb_memory_table_arn               = var.queue_mode ? null : local.dynamodb_memory_table_arn
  dynamodb_memory_table_name              = var.queue_mode ? null : local.dynamodb_memory_table_name
  dynamodb_multimodal_memory_table_arn    = var.queue_mode ? null : local.dynamodb_multimodal_memory_table_arn
  dynamodb_multimodal_memory_table_name   = var.queue_mode ? null : local.dynamodb_multimodal_memory_table_name
  input_queue_arn                         = local.input_queue_arn
  input_queue_url                         = local.input_queue_url
  response_store_redis                    = local.response_handler_response_store_redis
  response_store_dynamodb                 = local.response_handler_response_store_dynamodb
  websocket_connections_dynamodb          = local.websocket_api_enabled ? {
    table_name = module.websocket_connections[0].table_name
    table_arn  = module.websocket_connections[0].table_arn
  } : null
  lambda_signer_profile_name              = local.lambda_signer_profile_name
  lambda_signing_config_arn               = local.lambda_signing_config_arn
  docker_image_uri                        = var.package_type == "Image" ? module.docker_image[0].docker_image_uri : null
  lambda_kms_key_arn                      = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn                  = local.cloudwatch_kms_key_arn
  environment_variables = merge(try(var.environment_variables, null), {
    AK_EXECUTION__MODE = var.execution_mode,
  }, local.websocket_api_enabled ? {
    AK_WEBSOCKET_API__CHAT_ROUTE = var.ws_chat_route,
  } : {})

  depends_on = [module.request_handler_source_package]
}

# Agent Runner Module (conditional on queue_mode)
module "agent_runner" {
  count  = var.queue_mode ? 1 : 0
  source = "./modules/agent-runner"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  region        = var.region
  module_type   = var.module_type

  agent_runner = merge(var.agent_runner, {
    module_name  = local.agent_runner_artifact_module_name
    package_path = local.agent_runner_package_path
    package_type = try(var.agent_runner.package_type, null)
    layers       = try(var.agent_runner.layers, null)
    environment_variables = merge(try(var.agent_runner.environment_variables, null), {
      AK_EXECUTION__MODE = var.execution_mode
    })
  })

  source_bucket                     = var.agent_runner.package_type == "S3Zip" ? module.agent_runner_source_storage[0].source_storage_s3_bucket : null
  docker_image_uri                  = var.agent_runner.package_type == "Image" ? module.agent_runner_docker_image[0].docker_image_uri : null
  is_production                     = var.is_production
  lambda_signer_profile_name        = local.lambda_signer_profile_name
  lambda_signing_config_arn         = local.lambda_signing_config_arn
  cloudwatch_logs_retention_in_days = local.agent_runner_logs_retention_in_days
  create_dynamodb_memory_table      = var.create_dynamodb_memory_table
  create_dynamodb_multimodal_memory_table = var.create_dynamodb_multimodal_memory_table
  dynamodb_memory_table_arn         = local.dynamodb_memory_table_arn
  dynamodb_memory_table_name        = local.dynamodb_memory_table_name
  dynamodb_multimodal_memory_table_arn  = local.dynamodb_multimodal_memory_table_arn
  dynamodb_multimodal_memory_table_name = local.dynamodb_multimodal_memory_table_name
  redis_url                         = local.redis_url

  queue_config = {
    input_queue_arn                    = local.input_queue_arn
    output_queue_arn                   = local.output_queue_arn
    output_queue_url                   = local.output_queue_url
    input_queue_max_receive_count      = var.queue_config.input_queue_max_receive_count
    batch_size                         = var.queue_config.batch_size
    maximum_batching_window_in_seconds = var.queue_config.maximum_batching_window_in_seconds
  }

  subnet_ids             = local.subnet_ids
  security_group_id      = local.security_group_id
  lambda_kms_key_arn     = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn

  depends_on = [module.queues]
}

module "response_handler" {
  count  = var.queue_mode ? 1 : 0
  source = "./modules/response-handler"

  region                            = var.region
  cloudwatch_logs_retention_in_days = local.response_handler_logs_retention_in_days
  subnet_ids                        = local.subnet_ids
  security_group_id                 = local.security_group_id
  lambda_kms_key_arn                = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn            = local.cloudwatch_kms_key_arn
  source_bucket                     = local.response_handler_package_type == "S3Zip" ? module.response_handler_source_storage[0].source_storage_s3_bucket : null
  docker_image_uri                  = local.response_handler_package_type == "Image" ? module.response_handler_docker_image[0].docker_image_uri : null
  is_production                     = var.is_production
  lambda_signer_profile_name        = local.lambda_signer_profile_name
  lambda_signing_config_arn         = local.lambda_signing_config_arn

  product_alias = var.product_alias
  env_alias     = var.env_alias
  response_handler = merge(var.response_handler, {
    module_name = local.response_handler_artifact_module_name
    package_path = local.response_handler_package_path
    package_type = local.response_handler_package_type
    environment_variables = merge(try(var.response_handler.environment_variables, null), {
      AK_EXECUTION__MODE = var.execution_mode
    })
  })

  queue_config = {
    output_queue_arn                   = local.output_queue_arn
    output_queue_max_receive_count     = var.queue_config.output_queue_max_receive_count
    batch_size                         = var.queue_config.batch_size
    maximum_batching_window_in_seconds = var.queue_config.maximum_batching_window_in_seconds
  }

  response_store_redis    = local.response_handler_response_store_redis
  response_store_dynamodb = local.response_handler_response_store_dynamodb
  websocket_connections_dynamodb = local.websocket_api_enabled ? {
    table_name = module.websocket_connections[0].table_name
    table_arn  = module.websocket_connections[0].table_arn
  } : null
  websocket_api_execution_arn = local.websocket_api_enabled ? module.websocket_api_gateway[0].websocket_api_execution_arn : null
  execution_mode = var.execution_mode

  depends_on = [module.websocket_api_gateway, module.queues, module.dynamodb_response_store]
}

