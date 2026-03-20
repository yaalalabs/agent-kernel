data "aws_vpc" "provided" {
  count = var.vpc_id != null ? 1 : 0
  id    = var.vpc_id
}

locals {
  lambda_kms_key_arn         = null
  cloudwatch_kms_key_arn     = null
  lambda_signer_profile_name = "sample_profile"
  lambda_signing_config_arn  = null
  vpc_id                     = var.vpc_id != null ? var.vpc_id : module.vpc[0].vpc_id
  vpc_cidr                   = var.vpc_id != null ? data.aws_vpc.provided[0].cidr_block : var.vpc_cidr
  subnet_ids                 = var.vpc_id != null ? var.private_subnet_ids : module.vpc[0].private_subnet_ids
  redis_url                  = var.create_redis_cluster == true ? module.redis[0].url : null
  dynamodb_memory_table_arn  = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_arn : null
  dynamodb_memory_table_name = var.create_dynamodb_memory_table == true ? module.dynamodb_memory[0].table_name : null
  create_authorizer          = var.authorizer != null ? (var.authorizer.function_name != null && var.authorizer.handler_path != null && var.authorizer.package_type != null && var.authorizer.package_path != null && var.authorizer.module_name != null) : false

  # TODO:: check conditions and remove unwanted stuff

  # Response handler condition checks
  is_async_mode                  = var.execution_mode == "async"

  # Response store creation conditions
  create_response_store          = var.scalable_mode && !local.is_async_mode && var.response_store != null
  create_redis_response_store    = local.create_response_store && var.response_store.redis != null ? var.response_store.redis.url == null : false
  create_dynamodb_response_store = local.create_response_store && var.response_store.dynamodb != null ? var.response_store.dynamodb.table_arn == null : false
  has_redis_config             = var.response_store != null ? var.response_store.redis != null : false
  has_dynamodb_config          = var.response_store != null ? var.response_store.dynamodb != null : false
  should_use_external_redis    = local.has_redis_config ? var.response_store.redis.url == null : false
  should_use_external_dynamodb = local.has_dynamodb_config ? var.response_store.dynamodb.table_arn == null : false

  # Computed response store Redis URL
  response_store_redis_url = local.should_use_external_redis ? module.redis_response_store[0].url : (local.has_redis_config ? var.response_store.redis.url : null)

  # Computed response store DynamoDB values
  response_store_dynamodb_table_name = local.should_use_external_dynamodb ? module.dynamodb_response_store[0].table_name : (local.has_dynamodb_config ? var.response_store.dynamodb.table_name : null)
  response_store_dynamodb_table_arn  = local.should_use_external_dynamodb ? module.dynamodb_response_store[0].table_arn : (local.has_dynamodb_config ? var.response_store.dynamodb.table_arn : null)

  # Response handler response_store configuration
  response_handler_response_store = local.is_async_mode || var.response_store == null ? null : {
    database = var.response_store.database
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
  }

  # Authorizer status message for logging
  authorizer_required_vars_text = join(", ", compact(["authorizer_function_name", "authorizer_handler_path", "authorizer_package_type", "authorizer_package_path", "authorizer_module_name"]))
  authorizer_status_message     = local.create_authorizer ? format("Created Authorizer Lambda: All required variables are present (%s)", local.authorizer_required_vars_text) : format("Did NOT create Authorizer Lambda: Missing one or more required variables (%s)", local.authorizer_required_vars_text)


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
  normalized_endpoints = [
    for ep in local.complete_gateway_endpoints : {
      parts  = split("/", trim(ep.path, "/"))
      method = ep.method
    }
  ]
  converted_endpoints = [
    for ep in local.normalized_endpoints : {
      mainpath  = ep.parts[0]
      subpath   = length(ep.parts) > 1 ? ep.parts[1] : ""
      childpath = length(ep.parts) > 2 ? ep.parts[2] : ""
      method    = ep.method
    }
  ]
  all_endpoints = {
    for ep in local.converted_endpoints :
    "${ep.mainpath}/${ep.subpath != "" ? ep.subpath : "_root"}/${ep.childpath != "" ? ep.childpath : "_root"}/${ep.method}" => ep
  }
  mainpaths = {
    for _, v in local.all_endpoints : v.mainpath => v...
  }
  sub_resources = {
    for _, v in local.all_endpoints :
    "${v.mainpath}/${v.subpath}" => v...
    if v.subpath != ""
  }
  child_resources = {
    for _, v in local.all_endpoints :
    "${v.mainpath}/${v.subpath}/${v.childpath}" => v...
    if v.subpath != "" && v.childpath != ""
  }
}

module "vpc" {
  source               = "yaalalabs/ak-common/aws//modules/vpc"
  version              = "0.2.13"
  count                = var.vpc_id == null ? 1 : 0
  vpc_cidr             = var.vpc_cidr
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  tags                 = var.tags
}


module "source_storage" {
  count                = (var.package_type == "S3Zip") ? 1 : 0
  source               = "yaalalabs/ak-common/aws//modules/s3"
  version              = "0.2.13"
  region               = var.region
  env_alias            = var.env_alias
  is_production        = var.is_production
  product_alias        = var.product_alias
  product_display_name = var.product_display_name
  s3_kms_key_id        = ""
}

module "source_package" {
  count            = (var.package_type == "S3Zip") ? 1 : 0
  source           = "yaalalabs/ak-common/aws//modules/lambda-package"
  version          = "0.2.13"
  env_alias        = var.env_alias
  region           = var.region
  module_name      = var.module_name
  package_dir_path = var.package_path
  product_alias    = var.product_alias
  s3_bucket        = module.source_storage[0].source_storage_s3_bucket
  depends_on       = [module.source_storage]
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
  security_group_ids         = [aws_security_group.lambda.id]
  is_production              = var.is_production
  lambda_kms_key_arn         = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn     = local.cloudwatch_kms_key_arn
  lambda_signer_profile_name = local.lambda_signer_profile_name
  lambda_signing_config_arn  = local.lambda_signing_config_arn
}

module "docker_image" {
  count         = (var.package_type == "Image") ? 1 : 0
  source        = "yaalalabs/ak-common/aws//modules/ecr"
  version       = "0.2.13"
  env_alias     = var.env_alias
  module_name   = var.module_name
  product_alias = var.product_alias
  source_path   = var.package_path
}

module "redis" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.2.13"
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
  version = "0.2.13"
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

module "redis_response_store" {
  source        = "yaalalabs/ak-common/aws//modules/redis"
  version       = "0.2.13"
  count         = local.create_redis_response_store ? 1 : 0
  env_alias     = var.env_alias
  module_name   = "${var.module_name}-response-store"
  product_alias = var.product_alias
  vpc_cidr      = local.vpc_cidr
  vpc_id        = local.vpc_id
  subnet_ids    = local.subnet_ids
}

module "dynamodb_response_store" {
  source  = "yaalalabs/ak-common/aws//modules/dynamodb"
  version = "0.2.13"
  count   = local.create_dynamodb_response_store ? 1 : 0
  attributes = [
    { name = "request_id", type = "S" },
    { name = "timestamp", type = "N" },
  ]
  hash_key           = "request_id"
  range_key          = "timestamp"
  ttl_enabled        = true
  env_alias          = var.env_alias
  module_name        = "${var.module_name}-response-store"
  product_alias      = var.product_alias
  table_name         = var.response_store.dynamodb.table_name
  ttl_attribute_name = "expiry_time"
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

module "response_handler" {
  count  = var.scalable_mode ? 1 : 0
  source = "./modules/response-handler"
  # source = "yaalalabs/ak-serverless/aws//modules/response-handler"
  # version = "0.2.13"

  # Pass through all the required variables
  package_path     = var.package_path
  package_type     = var.package_type
  product_alias    = var.product_alias
  env_alias        = var.env_alias
  module_name      = var.module_name
  response_handler = var.response_handler
  response_store   = local.response_handler_response_store
  environment_variables = {
    AK_EXECUTION_MODE = var.execution_mode
  }

  # Pass local values
  subnet_ids             = local.subnet_ids
  security_group_id      = aws_security_group.lambda.id
  lambda_kms_key_arn     = local.lambda_kms_key_arn
  cloudwatch_kms_key_arn = local.cloudwatch_kms_key_arn

  depends_on = [null_resource.build_response_handler]
}
