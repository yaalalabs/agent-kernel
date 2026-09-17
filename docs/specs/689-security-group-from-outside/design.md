# #689: Accept externally-provided security groups in the containerized and serverless AWS modules

Both AWS Terraform deployment classes (`containerized`, `serverless`) always create their own security
groups today. This change adds an opt-in "bring your own SG" toggle wherever they do: a new nullable
`security_group_id` variable per logical SG, mirroring the existing `var.vpc_id` bring-your-own-VPC
convention — `null` (default) keeps today's create-a-new-SG behavior; a provided ID skips creation and
wires that ID into the same downstream resources instead. Every logical SG in scope needs exactly one
ID (each SG, ECS-level or Lambda-tier, is single-purpose), so no list-typed variable is needed anywhere.
Scope: ECS-level SGs in `containerized` and, per Lambda pipeline stage (request handler, agent runner,
response handler — **amended**, see the `serverless/state.tf` section below; originally one SG shared
by all five Lambdas), the Lambda-tier SGs in `serverless`. Redis/Valkey SGs are explicitly out of scope
(user decision).

## Motivation

- GitHub issue #689 asks specifically for the **serverless** Lambda SG:
  - `serverless/state.tf:92-105` creates `aws_security_group.lambda` unconditionally.
  - `serverless/state.tf:14` hard-wires `local.security_group_id = aws_security_group.lambda.id`.
  - Cited blockers: pipeline role lacking `ec2:CreateSecurityGroup`, default `0.0.0.0/0` egress
    disallowed by policy, existing downstream SG rules (RDS/ElastiCache) already reference a specific
    SG, and naming collisions when two stacks share `product_alias`/`env_alias` in one VPC.
  - Issue's own proposed shape: a single nullable `security_group_id` (mirrors `var.vpc_id`), with an
    open question about single-ID vs list (Lambda's `vpc_config` accepts multiple SGs).
  - Issue explicitly states containerized is out of its scope ("the containerized module doesn't create
    a Lambda SG") — **this design deliberately extends scope to containerized's ECS SGs per user
    request**, since the same operational blockers (no `ec2:CreateSecurityGroup`, pre-approved SGs)
    apply equally to ECS task/ALB SGs.
- A "create or use provided" toggle already exists in `common/modules/authorizer`
  (`security_group_ids`, list-shaped, default `[]`), but this design instead follows the more directly
  applicable `var.vpc_id` bring-your-own-VPC pattern — singular and nullable — since every SG in scope
  here (confirmed with the requester: all five serverless Lambdas share exactly one SG; each
  `containerized` SG below is single-purpose) needs only one ID. See `spec.md`'s Shared convention
  section for the detailed precedent comparison.
  - `authorizer`'s own `variables.tf`/`main.tf` need no changes — its call sites already only ever feed
    it a single-element list, and that stays true after this change.
- **containerized/modules/rest-service** creates two SGs with a dependency between them:
  - `rest-service/main.tf:144-162` — `aws_security_group.ecs_alb` (ALB SG, ingress from `var.vpc_cidr`
    on port 80).
  - `rest-service/main.tf:164-182` — `aws_security_group.ecs_service` (ECS task SG); its ingress rule
    at `main.tf:172` references `aws_security_group.ecs_alb.id` directly.
  - Consumers of `ecs_alb`: `aws_lb.app.security_groups` (`main.tf:191`).
  - Consumers of `ecs_service`: the `ecs_service` submodule call's `security_group_ids` (`main.tf:295`).
  - Both are exposed as outputs (`outputs.tf:41-49`: `security_group_id`, `alb_security_group_id`), and
    `alb_security_group_id` is consumed one level up by
    `containerized/api_gateway.tf:24` (`aws_apigatewayv2_vpc_link.ecs_alb.security_group_ids`).
- **containerized/modules/agent-runner** creates one egress-only SG:
  - `agent-runner/main.tf:277-290` — `aws_security_group.agent_runner`.
  - Consumed at `agent-runner/main.tf:341-345`
    (`aws_ecs_service.agent_runner.network_configuration.security_groups`).
  - Exposed via `agent-runner/outputs.tf:21-24` (`security_group_id`); not currently consumed by the
    containerized root module (verified: no reference to `module.agent_runner[0].security_group_id` in
    `containerized/*.tf`).
- **serverless/state.tf** creates one Lambda SG shared by five submodule calls:
  - `state.tf:92-105` — `aws_security_group.lambda`.
  - `state.tf:14` — `local.security_group_id = aws_security_group.lambda.id`.
  - Consumers: `module.authorizer` (`state.tf:183`, takes the **list**-shaped
    `security_group_ids = [local.security_group_id]`), `module.ws_connection_handler` (`state.tf:531`),
    `module.request_handler` (`state.tf:559`), `module.agent_runner` (`state.tf:690`),
    `module.response_handler` (`state.tf:708`) — these last four take a **singular**
    `security_group_id` (verified in `serverless/modules/request-handler/variables.tf:157-159`, type
    `string`; consumed at `serverless/modules/request-handler/main.tf:339` as
    `var.security_group_id != "" ? [var.security_group_id] : []`). The four non-authorizer submodules
    were never designed to take more than one shared SG.
- No `docs/specs/689-*` existed before this document; no code has landed on this branch yet.
- No production deployments of these modules exist yet (confirmed with the requester), so this change
  does not need to preserve existing Terraform state — adding `count` to the SG resources below is a
  plain change, no state-migration handling required.

## Requirements

### Shared convention (applies to every module below)

- New variable(s) named `security_group_id` (or a module-specific name, see below), `type = string`,
  `default = null` — one per logical SG, mirroring `var.vpc_id`'s shape and description style ("...If
  not provided, a new one will be created").
  - `null` (default) → module creates its own SG, exactly as today. No behavior change for existing
    callers that don't set the variable.
  - Non-null → module skips creating its own SG and uses the provided ID directly.
  - No separate boolean "create" flag — presence of a value is the toggle.
- Every SG resource this change touches becomes conditional on its variable.
- Every consumer of a conditional SG resource's ID is rewritten to read from a resolving local (the
  provided ID, or the created one) — never the raw resource attribute directly, since that reference
  breaks once the resource becomes conditional.
- Anywhere a list-typed argument is required downstream (ECS `network_configuration.security_groups`,
  `aws_lb.security_groups`, a submodule's `security_group_ids`), wrap the single effective ID.
- No new validation that a provided SG belongs to the target VPC — matches this module's existing
  practice of not validating `vpc_id`/`private_subnet_ids` either.

### `containerized/modules/rest-service`

- Two separate variables — `ecs_alb` and `ecs_service` are logically distinct SGs with different rules
  and an ingress dependency between them, and are toggled **independently** (you may provide one and
  let the module create the other; both-or-neither is not required):
  - `alb_security_group_id` — toggles the ALB SG.
  - `ecs_service_security_group_id` — toggles the ECS task SG.
- The ECS task SG's ingress rule must reference the resolved ALB SG (created or provided), so the ECS
  task always allows ingress from whichever ALB SG is actually in effect.
- The ALB itself and the `ecs_service` submodule call read from the resolved locals, not the raw
  resource attributes.
- Both module outputs (`security_group_id`, `alb_security_group_id`) must expose the effective ID —
  required because `containerized/api_gateway.tf:24` consumes `alb_security_group_id` for the VPC Link,
  and that must resolve correctly whether the ALB SG was created or user-provided.

### `containerized/modules/agent-runner`

- New variable: `security_group_id`.
- The SG resource becomes conditional; the ECS service's network configuration and the module's own
  output read the resolved local.

### `containerized` root (`state.tf`, `variables.tf`, `rest_service.tf`, `queue_mode.tf`)

- **Amendment (post-implementation):** the root already exposes `rest_service` and `agent_runner` as
  object-typed variables for that service's other settings (`variables.tf`'s `rest_service`/
  `agent_runner` blocks). To avoid a second, parallel flat-variable surface for config that belongs to
  the same service, the three SG IDs are added as `optional(string, null)` fields on those existing
  objects instead of new standalone root variables:
  - `rest_service.alb_security_group_id`, `rest_service.ecs_service_security_group_id`.
  - `agent_runner.security_group_id`.
  This supersedes the "three flat singular variables" decision recorded in Open Questions item 3 below.
- The ALB and ECS-service SG fields have an effect in every mode; the agent-runner SG field only has any
  effect when `queue_mode = true`, matching how other queue-mode-only `agent_runner` fields already
  behave outside queue mode.
- Each field is read straight through (`var.rest_service.alb_security_group_id`, etc.) and passed to the
  corresponding module call's existing flat `alb_security_group_id` / `ecs_service_security_group_id` /
  `security_group_id` argument — the submodules' own interfaces are unchanged (see the
  `containerized/modules/*` sections above).
- No change to `containerized/api_gateway.tf:24` itself — it keeps consuming
  `module.rest_service.alb_security_group_id`, which now resolves correctly in both create and
  provided-SG cases per the rest-service change above.

### `serverless/state.tf`

**Amendment (post-implementation):** superseding the single-shared-SG shape below, `serverless` now
splits into **three** logical security groups — one per Lambda pipeline stage (request handler, agent
runner, response handler) — mirroring `containerized`'s per-service SG split instead of one SG shared by
all five Lambdas. Each of the three lives as a field on the corresponding `request_handler`/
`agent_runner`/`response_handler` object variable (the same "field on the existing service object,
not a new flat variable" convention the containerized-root amendment above already established), rather
than as a single root-level `security_group_id` variable:

- `request_handler.security_group_id` — used by the request handler Lambda, and also by the authorizer
  and WebSocket connection handler Lambdas, since both are part of the same request-handling front door
  and neither was asked to get its own dedicated SG.
- `agent_runner.security_group_id` — used by the agent runner Lambda only (queue mode only).
- `response_handler.security_group_id` — used by the response handler Lambda only (queue mode only).

Each toggles independently, exactly like `containerized/modules/rest-service`'s two SG fields. Three
`aws_security_group` resources replace the single `aws_security_group.lambda`, each `count`-gated on its
own field being `null` (not on `queue_mode`/`enable_api_gateway`, to keep the resolving `local` always
safe to evaluate — see spec.md's Amendment for the reasoning). Three root outputs
(`request_handler_security_group_id`, `agent_runner_security_group_id`,
`response_handler_security_group_id`) replace the single `security_group_id` output.

<details>
<summary>Superseded: original single-shared-SG design</summary>

- New root-level variable: `security_group_id` — one ID shared by all five Lambda submodules,
  confirmed with the requester (all serverless Lambdas use the same SG; no submodule needs a distinct
  one).
- The Lambda SG resource becomes conditional; the existing shared local resolves to either the created
  or the provided ID.
- No changes needed at any of the five submodule call sites — they already reference that local, which
  now transparently resolves to either source.
- New output at the serverless root exposing the effective ID — issue #689 explicitly asks for a
  `lambda_security_group_id`-style output, and no SG output currently exists at either root module.
  `containerized` root gets equivalent outputs for its three SGs for the same reason (external consumers
  need to discover the effective ID either way).

</details>

## Non-goals

- `common/modules/redis` and `common/modules/valkey` are explicitly out of scope (user decision) —
  their SGs (`common/modules/redis/main.tf:1`, `common/modules/valkey/main.tf:1`) keep being created
  unconditionally.
- No validation that a caller-provided SG belongs to the deployment's VPC.
- No change to the SG *rules* (ingress/egress ports, CIDRs) created when the module does create its own
  SG — this change only toggles creation vs. reuse, not the rule content.
- Documentation updates (module READMEs, `docs/docs/deployment/aws-containerized.md`, its serverless
  equivalent) are tracked but not detailed here — they land as a `plan.md` iteration once the design and
  spec are settled.

## Open questions

This change is small and straightforward enough that these were confirmed directly with the requester
rather than through a formal review cycle; `design.md`/`spec.md`/`plan.md` exist to make implementation
easier, not as a gate. All four are resolved and folded into the Requirements above:

1. ~~Fan the serverless list out to all five submodules?~~ Originally moot — all five Lambdas were
   confirmed to share exactly one SG, so the variable was singular and no submodule needed changing.
   **Superseded (post-implementation)**: revisited to split into three SGs — one per Lambda pipeline
   stage (request handler, agent runner, response handler) — mirroring `containerized`'s per-service
   split; the authorizer and WebSocket connection handler Lambdas share the request handler's SG rather
   than getting their own. See the `serverless/state.tf` Amendment in Requirements above.
2. ~~Root-level output naming for `serverless`?~~ Originally singular `security_group_id`, per (1).
   **Superseded**: three outputs now, one per SG — see the same Amendment.
3. ~~containerized root variable granularity?~~ Originally three flat singular variables
   (`alb_security_group_id`, `ecs_service_security_group_id`, `agent_runner_security_group_id`),
   matching `vpc_id`'s existing flat-variable convention at that layer. **Superseded**: since
   `rest_service`/`agent_runner` are already object-typed config variables at this layer, the three SG
   IDs are nested fields on those objects instead of new flat variables — see the Amendment in
   Requirements above.
4. ~~Independent vs. both-or-neither toggle for `rest-service`'s two SGs?~~ Independent — you may
   provide an ID for one and let the module create the other.

No open questions remain. Ready for `spec.md` once this design is confirmed as final.
