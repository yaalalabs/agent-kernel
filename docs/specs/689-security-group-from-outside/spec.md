# #689: Accept externally-provided security groups in the containerized and serverless AWS modules — Implementation Spec

Implements `design.md` in this directory: a nullable `security_group_id` variable per logical SG in
`containerized/modules/rest-service`, `containerized/modules/agent-runner`, and `serverless/state.tf`,
each following the existing `var.vpc_id` bring-your-own convention (`null` → create as today, non-null →
use the provided ID and skip creation). The CI base deployment and any registry consumer already have
Terraform state for these SG resources under their unindexed addresses; adding `count` here without a
`moved` block causes the next `apply` against that state to attempt a replace instead of a reindex (see
design.md Motivation). This was raised in review and accepted as a one-time migration rather than
adding `moved` blocks.

## Design

### Shared convention

Applied identically at every SG resource touched by this change:

```hcl
variable "security_group_id" {          # name varies per module — see each section below
  type        = string
  description = "Security group ID. If not provided, a new one will be created"
  default     = null
}

resource "aws_security_group" "x" {
  count = var.security_group_id == null ? 1 : 0
  # ...unchanged rule content...
}

locals {
  # Effective ID: the provided one, or the one just created.
  x_security_group_id = var.security_group_id != null ? var.security_group_id : aws_security_group.x[0].id
}
```

Governing rules:

1. Every reference to a `count`-ed SG resource's `.id` goes through the `local`, never
   `aws_security_group.x.id`/`aws_security_group.x[0].id` directly — the raw resource reference breaks
   (indexes into a zero-length resource) when the SG is user-provided.
2. Anywhere a list-typed argument is required (`network_configuration.security_groups`,
   `aws_lb.security_groups`, a submodule's `security_group_ids`), wrap the singular local:
   `[local.x_security_group_id]`.
3. Variable description copies `var.vpc_id`'s wording ("...If not provided, a new one will be created")
   for consistency across the module family.
4. No plan-time validation that a provided ID belongs to the deployment's VPC or is even a real SG —
   matches this module's existing non-validation of `vpc_id`/`private_subnet_ids` (see Error handling).

### `containerized/modules/rest-service`

Two independent variables — `alb_security_group_id` and `ecs_service_security_group_id` — since
`ecs_alb` and `ecs_service` are separate SGs with different rules and a one-way dependency (the ECS
service's ingress rule allows traffic from the ALB SG).

`variables.tf` additions:

```hcl
variable "alb_security_group_id" {
  type        = string
  description = "ALB security group ID. If not provided, a new one will be created"
  default     = null
}

variable "ecs_service_security_group_id" {
  type        = string
  description = "ECS service security group ID. If not provided, a new one will be created"
  default     = null
}
```

`main.tf` changes (all under the existing `# Security Groups` heading, `main.tf:142-182`):

```hcl
resource "aws_security_group" "ecs_alb" {
  count = var.alb_security_group_id == null ? 1 : 0
  # ...unchanged body (name/description/vpc_id/ingress/egress/tags)...
}

resource "aws_security_group" "ecs_service" {
  count = var.ecs_service_security_group_id == null ? 1 : 0
  # ...unchanged description/vpc_id/egress/tags...
  ingress {
    from_port       = var.rest_service.container_port
    to_port         = var.rest_service.container_port
    protocol        = "tcp"
    security_groups = [local.alb_security_group_id]   # was: [aws_security_group.ecs_alb.id]
  }
}

locals {
  alb_security_group_id         = var.alb_security_group_id != null ? var.alb_security_group_id : aws_security_group.ecs_alb[0].id
  ecs_service_security_group_id = var.ecs_service_security_group_id != null ? var.ecs_service_security_group_id : aws_security_group.ecs_service[0].id
}
```

Downstream reference updates in `main.tf`:

- `aws_lb.app.security_groups` (`main.tf:191`): `[aws_security_group.ecs_alb.id]` → `[local.alb_security_group_id]`.
- `module "ecs_service"`'s `security_group_ids` (`main.tf:295`): `[aws_security_group.ecs_service.id]` → `[local.ecs_service_security_group_id]`.

`outputs.tf` changes (`outputs.tf:41-49`) — expose the effective local, not the raw resource attribute,
because `containerized/api_gateway.tf:24` depends on `alb_security_group_id` resolving correctly in both
the create and provided-SG cases:

```hcl
output "security_group_id" {
  description = "ECS service security group ID"
  value       = local.ecs_service_security_group_id   # was: aws_security_group.ecs_service.id
}

output "alb_security_group_id" {
  description = "ALB security group ID"
  value       = local.alb_security_group_id           # was: aws_security_group.ecs_alb.id
}
```

### `containerized/modules/agent-runner`

One variable, following the shared convention exactly:

```hcl
variable "security_group_id" {
  type        = string
  description = "Agent Runner security group ID. If not provided, a new one will be created"
  default     = null
}
```

`main.tf` (`main.tf:277-290`):

```hcl
resource "aws_security_group" "agent_runner" {
  count = var.security_group_id == null ? 1 : 0
  # ...unchanged name/description/vpc_id/egress/tags...
}

locals {
  security_group_id = var.security_group_id != null ? var.security_group_id : aws_security_group.agent_runner[0].id
}
```

- `aws_ecs_service.agent_runner.network_configuration.security_groups` (`main.tf:343`):
  `[aws_security_group.agent_runner.id]` → `[local.security_group_id]`.
- `outputs.tf:21-24` `security_group_id` output value: `aws_security_group.agent_runner.id` →
  `local.security_group_id`.

### `containerized` root (`variables.tf`, `state.tf`, `rest_service.tf`, `queue_mode.tf`, `outputs.tf`)

**Amendment (post-implementation):** rather than three new flat root variables, the SG IDs are added as
`optional(string, null)` fields on the existing `rest_service` and `agent_runner` object variables — this
supersedes the flat-variable shape originally specified below in this section, because it avoids a
second, parallel flat surface for config that already belongs to those two objects.

`variables.tf`'s `rest_service` object gains two fields:

```hcl
variable "rest_service" {
  description = "REST service configuration object"
  type = object({
    # ...existing fields...
    alb_security_group_id         = optional(string, null) # ALB security group ID. If not provided, a new one will be created
    ecs_service_security_group_id = optional(string, null) # ECS service security group ID. If not provided, a new one will be created
  })
}
```

`variables.tf`'s `agent_runner` object gains one field (and its `default` block a matching entry):

```hcl
variable "agent_runner" {
  description = "Agent runner configuration object"
  type = object({
    # ...existing fields...
    security_group_id = optional(string, null) # Agent Runner security group ID (queue mode only). If not provided, a new one will be created
  })
  default = {
    # ...existing fields...
    security_group_id = null
  }
}
```

Wiring (no `state.tf` locals needed — these pass straight through as literal values, unlike `vpc_id`
which needs VPC lookup/derivation):

- `rest_service.tf`'s `module "rest_service"` block (`rest_service.tf:4-65`) gets two new arguments:
  `alb_security_group_id = var.rest_service.alb_security_group_id` and
  `ecs_service_security_group_id = var.rest_service.ecs_service_security_group_id`. The submodule's own
  flat `alb_security_group_id`/`ecs_service_security_group_id` variables (per the `rest-service` section
  above) are unchanged — only where the root sources their values from changes.
- `queue_mode.tf`'s `module "agent_runner"` block (`queue_mode.tf:25-79`) gets one new argument:
  `security_group_id = var.agent_runner.security_group_id`. The submodule's own flat `security_group_id`
  variable is unchanged.

New outputs in `outputs.tf` (grouped near the existing `vpc_id`/`private_subnet_ids` outputs,
`outputs.tf:34-42`):

```hcl
output "alb_security_group_id" {
  description = "ALB security group ID"
  value       = module.rest_service.alb_security_group_id
}

output "ecs_service_security_group_id" {
  description = "ECS service security group ID"
  value       = module.rest_service.security_group_id
}

output "agent_runner_security_group_id" {
  description = "Agent Runner security group ID (queue mode only)"
  value       = var.queue_mode ? module.agent_runner[0].security_group_id : null
}
```

`containerized/api_gateway.tf:24` is unchanged — it already consumes `module.rest_service.alb_security_group_id`, which resolves correctly under both the create and provided-SG cases after the `rest-service` change above.

### `serverless/state.tf`

**Amendment (post-implementation):** superseded the single-shared-SG shape below with **three** logical
SGs, one per Lambda pipeline stage, following the same "field on the existing service object" convention
as the `containerized` root amendment. `request_handler`/`agent_runner`/`response_handler` (all in
`variables.tf`) each gain a `security_group_id = optional(string, null)` field:

```hcl
variable "request_handler" {
  type = object({
    # ...existing fields...
    security_group_id = optional(string, null) # Request handler security group ID, also shared by the authorizer and WebSocket connection handler Lambdas. If not provided, a new one will be created
  })
}

variable "agent_runner" {
  type = object({
    # ...existing fields...
    security_group_id = optional(string, null) # Agent runner security group ID (queue mode only). If not provided, a new one will be created
  })
}

variable "response_handler" {
  type = object({
    # ...existing fields...
    security_group_id = optional(string, null) # Response handler security group ID (queue mode only). If not provided, a new one will be created
  })
}
```

`state.tf` replaces the single `aws_security_group.lambda` with three resources, each gated purely on
its own field being `null` — **not** additionally on `queue_mode`/`enable_api_gateway` — so the
resolving `local` never has to branch into a resource whose `count` depends on a different condition
than the one the `local` itself checks (that mismatch is exactly the "index into a zero-length resource"
trap the shared convention's rule 1 warns about: if the SG resource's `count` were `var.queue_mode &&
security_group_id == null` while the `local` only checks `security_group_id == null`, a `queue_mode =
false` deployment with the field left unset would try to index `aws_security_group.agent_runner[0]`
into a resource that was never created). This mirrors the original single-SG shape's own
unconditional-`count` behavior (that resource, too, was always created regardless of what else was
enabled), so it's not a new tradeoff — just preserved across the split:

```hcl
resource "aws_security_group" "request_handler" {
  count = var.request_handler.security_group_id == null ? 1 : 0
  # name/description reference the request handler explicitly; egress-all; unchanged otherwise
}

resource "aws_security_group" "agent_runner" {
  count = var.agent_runner.security_group_id == null ? 1 : 0
}

resource "aws_security_group" "response_handler" {
  count = var.response_handler.security_group_id == null ? 1 : 0
}

locals {
  request_handler_security_group_id  = var.request_handler.security_group_id != null ? var.request_handler.security_group_id : aws_security_group.request_handler[0].id
  agent_runner_security_group_id     = var.agent_runner.security_group_id != null ? var.agent_runner.security_group_id : aws_security_group.agent_runner[0].id
  response_handler_security_group_id = var.response_handler.security_group_id != null ? var.response_handler.security_group_id : aws_security_group.response_handler[0].id
}
```

Submodule call sites are rewired (unlike the superseded design, where no rewiring was needed since every
call site already shared one local):

- `module.authorizer`'s `security_group_ids` and `module.ws_connection_handler`'s `security_group_id` →
  `local.request_handler_security_group_id` (both are part of the request-handling front door).
- `module.request_handler`'s `security_group_id` → `local.request_handler_security_group_id`.
- `module.agent_runner`'s `security_group_id` → `local.agent_runner_security_group_id`.
- `module.response_handler`'s `security_group_id` → `local.response_handler_security_group_id`.

Three outputs in `outputs.tf` replace the single `security_group_id` output (the `agent_runner`/
`response_handler` ones are nulled when `queue_mode = false`, matching this file's existing convention
for every other agent-runner/response-handler output — the underlying local is still always resolvable,
this only suppresses a meaningless value in the output):

```hcl
output "request_handler_security_group_id" {
  value = local.request_handler_security_group_id
}
output "agent_runner_security_group_id" {
  value = var.queue_mode ? local.agent_runner_security_group_id : null
}
output "response_handler_security_group_id" {
  value = var.queue_mode ? local.response_handler_security_group_id : null
}
```

<details>
<summary>Superseded: original single-shared-SG design</summary>

One root variable, one shared SG, matching `vpc_id`'s exact shape:

```hcl
variable "security_group_id" {   # in variables.tf, alongside vpc_id (variables.tf:98-102)
  type        = string
  description = "Security group ID for Lambda functions. If not provided, a new one will be created"
  default     = null
}
```

`state.tf` changes:

```hcl
resource "aws_security_group" "lambda" {
  count = var.security_group_id == null ? 1 : 0
  # ...unchanged name/description/vpc_id/egress...
}

locals {
  # was: security_group_id = aws_security_group.lambda.id
  security_group_id = var.security_group_id != null ? var.security_group_id : aws_security_group.lambda[0].id
  # ...rest of the locals block unchanged...
}
```

No changes at any of the five submodule call sites (`module.authorizer` `state.tf:183`,
`module.ws_connection_handler` `state.tf:531`, `module.request_handler` `state.tf:559`,
`module.agent_runner` `state.tf:690`, `module.response_handler` `state.tf:708`) — they already reference
`local.security_group_id` (wrapped `[local.security_group_id]` for `authorizer`, singular for the other
four), and that local now transparently resolves to either source.

New output in `outputs.tf` (grouped near the existing `vpc_id`/`private_subnet_ids` outputs,
`outputs.tf:33-41`):

```hcl
output "security_group_id" {
  description = "Security group ID used for Lambda functions"
  value       = local.security_group_id
}
```

</details>

### Consumer changes

| File | Change |
|---|---|
| `containerized/modules/rest-service/main.tf` | `ecs_alb`/`ecs_service` gain `count`; ingress rule, `aws_lb.app.security_groups`, `ecs_service` submodule call updated to read the new locals |
| `containerized/modules/rest-service/variables.tf` | + `alb_security_group_id`, `ecs_service_security_group_id` |
| `containerized/modules/rest-service/outputs.tf` | `security_group_id`, `alb_security_group_id` now return the effective local |
| `containerized/modules/agent-runner/main.tf` | `agent_runner` gains `count`; `network_configuration.security_groups` updated to read the new local |
| `containerized/modules/agent-runner/variables.tf` | + `security_group_id` |
| `containerized/modules/agent-runner/outputs.tf` | `security_group_id` now returns the effective local |
| `containerized/variables.tf` | + `alb_security_group_id`/`ecs_service_security_group_id` fields on `rest_service`; + `security_group_id` field on `agent_runner` (amended — not new flat variables) |
| `containerized/rest_service.tf` | passes `var.rest_service.alb_security_group_id` / `var.rest_service.ecs_service_security_group_id` through to the submodule's flat variables |
| `containerized/queue_mode.tf` | passes `var.agent_runner.security_group_id` through to the submodule's flat `security_group_id` variable |
| `containerized/outputs.tf` | + `alb_security_group_id`, `ecs_service_security_group_id`, `agent_runner_security_group_id` |
| `containerized/api_gateway.tf` | **unchanged** — verified `module.rest_service.alb_security_group_id` keeps working via the updated output |
| `serverless/state.tf` | **Amended** — the single `aws_security_group.lambda` is replaced by three resources (`request_handler`, `agent_runner`, `response_handler`), each gated on its own object field; three resolving locals replace the one shared local |
| `serverless/variables.tf` | **Amended** — + `security_group_id` field on each of `request_handler`, `agent_runner`, `response_handler` (not a new flat root variable) |
| `serverless/outputs.tf` | **Amended** — `request_handler_security_group_id`, `agent_runner_security_group_id`, `response_handler_security_group_id` replace the single `security_group_id` output |
| `serverless/state.tf` submodule calls (`authorizer`, `ws_connection_handler`, `request_handler`, `agent_runner`, `response_handler`) | **Amended** — rewired to the three new locals (`request_handler_security_group_id` for `authorizer`/`ws_connection_handler`/`request_handler`; `agent_runner_security_group_id` / `response_handler_security_group_id` for their own modules) |
| `common/modules/authorizer/*` | **unchanged** — out of scope; already supports a list-shaped `security_group_ids`, always fed a single-element list |
| `common/modules/redis/*`, `common/modules/valkey/*` | **unchanged** — explicitly out of scope (design.md Non-goals) |

### Config changes

None. This change is entirely Terraform infrastructure variables — it does not touch `AKConfig`, any
`config.yaml`, or any `AK_*` environment variable injected into the application containers/Lambdas.

### Behavioural changes

1. **New optional inputs, default-preserving.** Every new variable defaults to `null`, which preserves
   today's create-a-new-SG behavior exactly. A deployment that doesn't set any of these new variables
   sees no plan diff from this change (same SG rules, same resource count).
2. **SG resources gain `count`.** `aws_security_group.ecs_alb`, `aws_security_group.ecs_service`,
   `aws_security_group.agent_runner` (all in `containerized`), and `aws_security_group.request_handler` /
   `aws_security_group.agent_runner` / `aws_security_group.response_handler` (`serverless`, amended —
   three resources replacing the original single `aws_security_group.lambda`) move from unconditional
   resources to `count`-based ones. No state-migration handling (no `moved` blocks) — confirmed with the
   requester that no production deployment of these modules exists yet.
3. **New capability**: when a `*_security_group_id` variable is set, the module skips creating its own
   SG and wires the provided ID into every place that SG's ID was previously used (ingress rules, load
   balancer, ECS `network_configuration`, Lambda `vpc_security_group_ids`, module outputs).
4. **`rest-service`'s two SG toggles are independent.** You may provide `alb_security_group_id` alone,
   `ecs_service_security_group_id` alone, both, or neither — any combination is valid. If only
   `alb_security_group_id` is provided, `ecs_service`'s ingress rule allows traffic from that provided
   ALB SG (not a module-created one); if only `ecs_service_security_group_id` is provided, the ALB SG is
   still created by the module and the provided ECS-service SG's ingress rule (defined outside this
   module, by the caller) is expected to allow that ALB SG.
5. **(Amended) `serverless`'s three SG toggles are independent, and one is shared by three Lambdas.**
   `request_handler.security_group_id`, `agent_runner.security_group_id`, and
   `response_handler.security_group_id` may each be set or left unset in any combination.
   `request_handler.security_group_id` (created or provided) is also wired into the authorizer and
   WebSocket connection handler Lambdas — those two were not given their own SG field, since neither was
   asked for one and both belong to the same request-handling tier as the request handler.
   `agent_runner.security_group_id` and `response_handler.security_group_id` only have an effect when
   `queue_mode = true` (their Lambdas don't exist otherwise), matching how other queue-mode-only fields
   on those same objects already behave.

**Non-changes**: the SG *rule content* (ports, protocols, CIDR blocks, egress-to-`0.0.0.0/0`) created
when a module still creates its own SG is untouched. `common/modules/authorizer`'s own
`variables.tf`/`main.tf` are untouched. No submodule under `serverless/modules/*` is touched. No change
to any resource unrelated to security groups.

## Error handling

- **Provided ID doesn't exist / belongs to a different VPC**: not validated at plan time (matches
  existing `vpc_id`/`private_subnet_ids` behavior in both root modules). Surfaces as a standard AWS API
  error at `terraform apply` time — e.g. ECS/Lambda/ALB creation fails with an AWS-reported
  `InvalidGroup.NotFound` or a networking error if the SG is real but not reachable from the target
  subnets. No custom error handling is added; this is consistent with how this module already treats
  invalid `vpc_id`/`subnet_ids` input.
- **Empty string vs. null**: variables are typed `string` with `default = null`; an empty string `""` is
  a distinct, valid-but-wrong value that is NOT treated as "unset" (the toggle checks `== null`, not
  falsiness) — passing `""` attempts to use `""` as a security group ID and fails at apply time with an
  AWS validation error. No plan-time guard is added, matching this module's general practice of not
  validating individual string variables for emptiness (e.g. `vpc_id` has no such guard either).
- **Both `security_group_id` set and the module's own SG somehow still referenced**: not possible by
  construction — the `count` on each `aws_security_group` resource and the `local` resolution are the
  single source of truth; every downstream reference goes through the `local`.

## Testing

This repo has no Terraform unit-test framework (no `.tftest.hcl` files, no Terratest — verified: none
exist under `ak-deployment/`). Verification for Terraform changes in this repo happens through:

1. **Static checks** (run locally, no AWS credentials needed) on every module touched:
   - `terraform fmt -check -recursive` in `ak-deployment/ak-aws/containerized` and
     `ak-deployment/ak-aws/serverless`.
   - `terraform validate` in `containerized/modules/rest-service`, `containerized/modules/agent-runner`,
     `containerized` (root), and `serverless` (root).
2. **Plan review** (no AWS credentials strictly needed for a syntax/graph-level check, but a full
   provider-aware plan needs credentials) — for both root modules, confirm via `terraform plan`:
   - With no `*_security_group_id` variables set: **zero plan diff** for a deployment that already
     exists at the pre-change code (or, since none do yet, this reduces to "the create-path plan output
     is unchanged in resource count and attributes from before this change").
   - With a `*_security_group_id` variable set to a plausible (fake, for a syntax-only plan) SG ID: the
     corresponding `aws_security_group` resource shows 0 count, and every consumer (ingress rule, ALB,
     ECS `network_configuration`, Lambda `vpc_security_group_ids`, module/root outputs) resolves to the
     provided ID rather than erroring on a missing resource index.
3. **CI integration test** (`.github/workflows/integration-test-weekly.yaml`): the `aws-containerized`
   and `aws-serverless` matrix entries already deploy real infrastructure and already thread a
   pre-created VPC through `--vpc-id`/`--private-subnet-ids` (`integration-test-weekly.yaml:291-293`),
   proving the bring-your-own-VPC path end-to-end. This spec does not add a bring-your-own-SG scenario
   to that matrix — doing so is optional follow-up (would need the base-infra step to also pre-create a
   security group and thread its ID through `run_single_test.py`/`inject_dependencies.py`); the default
   (`null`) path these matrix entries already exercise is what regresses if this change breaks anything,
   and that continues to run unmodified.
