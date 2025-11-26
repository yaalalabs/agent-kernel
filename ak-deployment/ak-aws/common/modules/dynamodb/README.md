# DynamoDB Table (Common Module)

This module wraps `terraform-aws-modules/dynamodb-table/aws` to provision DynamoDB tables with sensible defaults and a naming convention consistent with the rest of the project.

It is intended to be consumed by both serverless and containerized stacks to create and manage DynamoDB tables.

## Features
- Opinionated naming: defaults to `<product>-<env>-<module>-ddb` when `table_name` is not provided
- PAY_PER_REQUEST by default (can switch to PROVISIONED)
- Optional GSIs and LSIs
- TTL, Streams, PITR, SSE, and deletion protection toggles
- Pass-through tags

## Inputs
Key inputs (see `variables.tf` for full list):
- `product_alias`, `env_alias`, `module_name`, `tags`
- `table_name` (optional) — override the default name
- `attributes` (required) — attribute definitions
- `hash_key` (required), `range_key` (optional)
- `billing_mode` (default: PAY_PER_REQUEST), `read_capacity`, `write_capacity`
- `global_secondary_indexes`, `local_secondary_indexes`
- `ttl_enabled`, `ttl_attribute_name`
- `stream_enabled`, `stream_view_type`
- `point_in_time_recovery_enabled` (default: true)
- `server_side_encryption_enabled` (default: true), `kms_key_arn`
- `deletion_protection_enabled` (default: true)

## Outputs
- `table_name`, `table_id`, `table_arn`
- `stream_arn`, `stream_label`

## Usage

### Basic table (on-demand, key-only)
```hcl
module "orders_table" {
  source = "../../common/modules/dynamodb"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = "orders"

  attributes = [
    { name = "pk", type = "S" },
    { name = "sk", type = "S" }
  ]
  hash_key  = "pk"
  range_key = "sk"

  tags = var.tags
}
```

### With a GSI and TTL
```hcl
module "events_table" {
  source = "../../common/modules/dynamodb"

  product_alias = var.product_alias
  env_alias     = var.env_alias
  module_name   = "events"

  attributes = [
    { name = "pk", type = "S" },
    { name = "sk", type = "S" },
    { name = "gsi1pk", type = "S" },
    { name = "gsi1sk", type = "S" },
    { name = "ttl", type = "N" }
  ]
  hash_key  = "pk"
  range_key = "sk"

  global_secondary_indexes = [
    {
      name            = "gsi1"
      hash_key        = "gsi1pk"
      range_key       = "gsi1sk"
      projection_type = "ALL"
    }
  ]

  ttl_enabled        = true
  ttl_attribute_name = "ttl"

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = var.tags
}
```

### Referencing from Serverless/Containerized stacks
- Add the module call in your stack (serverless or containerized) like shown above
- Export any outputs you need (e.g., stream ARN for event source mappings) or pass the table name/ARN as environment variables to Lambdas or ECS tasks

Example: pass table name to a Lambda via `environment_variables` in serverless `lambda.tf` usage.
```hcl
environment_variables = merge(var.environment_variables, {
  DDB_TABLE_ORDERS = module.orders_table.table_name
})
```

## Versioning
- Module pins `terraform-aws-modules/dynamodb-table` to `~> 4.0` compatible (`= 4.0.0` currently). Adjust as needed.

## Notes
- When using PROVISIONED capacity, set `read_capacity` and `write_capacity` (and per-GSI capacities if applicable)
- For SSE with customer-managed key, provide `kms_key_arn`
