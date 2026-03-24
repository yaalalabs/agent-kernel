provider "aws" {
  region = var.region
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.11.0" # pin terraform provider version
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
  required_version = ">= 1.9.5" # pin terraform version
}

provider "docker" {
  registry_auth {
    address = format("%v.dkr.ecr.%v.amazonaws.com", data.aws_caller_identity.current.account_id, var.region)
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

module "vpc" {
  source               = "yaalalabs/ak-common/aws//modules/vpc"
  version              = "0.2.14"
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
  version                    = "0.2.13"
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
  security_group_ids         = [module.request_handler.lambda_security_group_id]
  is_production              = var.is_production
  lambda_kms_key_arn         = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn     = local.cloudwatch_kms_key_arn
  lambda_signer_profile_name = local.lambda_signer_profile_name
  lambda_signing_config_arn  = local.lambda_signing_config_arn
}

# API Gateway Module
module "api_gateway" {
  source = "./modules/api-gateway"

  region               = var.region
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  product_display_name = var.product_display_name
  api_base_path        = var.api_base_path
  api_version          = var.api_version
  agent_endpoint       = var.agent_endpoint
  tags                 = var.tags

  lambda_function_invoke_arn = module.request_handler.lambda_function_invoke_arn
  lambda_function_name       = module.request_handler.lambda_function_name

  endpoints = local.complete_gateway_endpoints

  authorizer                            = var.authorizer
  authorizer_lambda_function_invoke_arn = local.create_authorizer ? module.authorizer[0].lambda_function_invoke_arn : ""
  create_authorizer                     = local.create_authorizer

  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn

  depends_on = [module.request_handler]
}

module "docker_image" {
  count         = (var.package_type == "Image") ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.2.14"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

module "redis" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.2.14"
  count         = var.create_redis_cluster == true ? 1 : 0
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module "dynamodb_memory" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.2.14"
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
  version = "0.2.13"
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

# SQS Queues Module (conditional on scalable_mode)
module "queues" {
  count  = var.scalable_mode ? 1 : 0
  source = "./modules/queues"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  tags          = var.tags

  queue_config = local.queue_config
}

# Response Stores Module (conditional on scalable_mode and execution_mode != "async")
module "response_stores" {
  count  = local.create_response_store ? 1 : 0
  source = "./modules/response-stores"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name

  create_redis    = local.create_redis_response_store
  create_dynamodb = local.create_dynamodb_response_store

  dynamodb_table_name   = local.has_dynamodb_config ? var.response_store.dynamodb.table_name : "ak-responses"
  response_store_suffix = var.response_store != null ? var.response_store.suffix : null

  vpc_id     = local.vpc_id
  vpc_cidr   = local.vpc_cidr
  subnet_ids = local.subnet_ids
}

# Build response handler package
resource "null_resource" "build_response_handler" {
  count = var.scalable_mode ? 1 : 0
  triggers = { # will trigger the script (script running is done in local-exec) if package_path OR the build_response_handler.sh script changes
    package_path = var.package_path
    script_hash  = filemd5("${path.module}/modules/response-handler/build_response_handler.sh")
  }
  provisioner "local-exec" {
    command     = "./build_response_handler.sh --package-path ${var.package_path}"
    working_dir = "${path.module}/modules/response-handler"
  }
}

# Request Handler Lambda Module
module "request_handler" {
  source = "./modules/request-handler"

  region                                  = var.region
  product_alias                           = var.product_alias
  product_display_name                    = var.product_display_name
  env_alias                               = var.env_alias
  module_type                             = var.module_type
  module_name                             = var.module_name
  is_production                           = var.is_production
  package_path                            = var.package_path
  scalable_mode                           = var.scalable_mode
  event_source_mapping                    = var.event_source_mapping
  environment_variables                   = var.environment_variables
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
  create_dynamodb_memory_table            = var.create_dynamodb_memory_table
  create_dynamodb_multimodal_memory_table = var.create_dynamodb_multimodal_memory_table
  dynamodb_memory_table_arn               = local.dynamodb_memory_table_arn
  dynamodb_memory_table_name              = local.dynamodb_memory_table_name
  dynamodb_multimodal_memory_table_arn    = local.dynamodb_multimodal_memory_table_arn
  dynamodb_multimodal_memory_table_name   = local.dynamodb_multimodal_memory_table_name
  input_queue_arn                         = local.input_queue_arn
  input_queue_url                         = local.input_queue_url
  redis_url                               = local.redis_url
  lambda_signer_profile_name              = local.lambda_signer_profile_name
  lambda_signing_config_arn               = local.lambda_signing_config_arn
  docker_image_uri                        = var.package_type == "Image" ? module.docker_image[0].docker_image_uri : null
  lambda_kms_key_arn                      = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn                  = local.cloudwatch_kms_key_arn
}

# Agent Runner Module (conditional on scalable_mode)
module "agent_runner" {
  count  = var.scalable_mode ? 1 : 0
  source = "./modules/agent-runner"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  module_type   = var.module_type

  agent_runner = merge(var.agent_runner, {
    package_path = var.package_path
    package_type = var.package_type
    layers       = var.layers
    environment_variables = merge(var.environment_variables, {
      AK_EXECUTION__MODE = var.execution_mode
    })
  })

  queue_config = {
    input_queue_arn                    = local.input_queue_arn
    output_queue_arn                   = local.output_queue_arn
    output_queue_url                   = local.output_queue_url
    batch_size                         = var.queue_config != null ? var.queue_config.batch_size : 10
    maximum_batching_window_in_seconds = var.queue_config != null ? var.queue_config.maximum_batching_window_in_seconds : 5
  }

  subnet_ids             = local.subnet_ids
  security_group_id      = module.request_handler.lambda_security_group_id
  lambda_kms_key_arn     = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn

  depends_on = [module.queues]
}

module "response_handler" {
  count  = var.scalable_mode ? 1 : 0
  source = "./modules/response-handler"
  # source = "yaalalabs/ak-serverless/aws//modules/response-handler"
  # version = "0.2.13"

  # Pass through all the required variables
  package_path = var.package_path
  package_type = var.package_type

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = var.module_name
  response_handler = merge(var.response_handler, {
    environment_variables = {
      AK_EXECUTION__MODE = var.execution_mode
    }
  })
  response_store = local.response_handler_response_store

  queue_config = {
    output_queue_arn                   = local.output_queue_arn
    batch_size                         = var.queue_config != null ? var.queue_config.batch_size : 10
    maximum_batching_window_in_seconds = var.queue_config != null ? var.queue_config.maximum_batching_window_in_seconds : 5
  }

  # Pass local values
  subnet_ids             = local.subnet_ids
  security_group_id      = module.request_handler.lambda_security_group_id
  lambda_kms_key_arn     = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn

  depends_on = [null_resource.build_response_handler, module.queues, module.response_stores]
}