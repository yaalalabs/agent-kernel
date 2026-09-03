# #689: Accept externally-provided security groups in the containerized and serverless AWS modules

Both AWS Terraform deployment classes (`containerized`, `serverless`) always create their own security
groups today. This change adds an opt-in "bring your own SG" toggle wherever they do: a new nullable
`security_group_id` variable per logical SG, mirroring the existing `var.vpc_id` bring-your-own-VPC
convention — `null` (default) keeps today's create-a-new-SG behavior; a provided ID skips creation and
wires that ID into the same downstream resources instead. Every logical SG in scope needs exactly one
ID (confirmed: all Lambdas share one SG, each ECS-level SG is single-purpose), so no list-typed variable
is needed anywhere. Scope: ECS-level SGs in `containerized` and the shared Lambda SG in `serverless`.
Redis/Valkey SGs are explicitly out of scope (user decision).

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
- Existing precedent for a "create or use provided" toggle lives in `common/modules/authorizer`:
  - `authorizer/variables.tf:57-61` — `security_group_ids`, `list(string)`, default `[]`.
  - `authorizer/main.tf:39-40` — `count = length(var.security_group_ids) == 0 && length(var.subnet_ids) > 0 ? 1 : 0`.
  - `authorizer/main.tf:121` — `vpc_security_group_ids = length(var.security_group_ids) > 0 ? var.security_group_ids : (length(var.subnet_ids) > 0 ? [aws_security_group.authorizer_lambda[0].id] : null)`.
  - This submodule's own variable is list-shaped, but every current call site only ever feeds it a
    single-element list (see below) — that stays true after this change, so `authorizer`'s
    `variables.tf`/`main.tf` need **no changes**.
  - No `coalesce()` anywhere in the repo's `.tf` files (verified by grep).
  - The more directly-applicable precedent is the top-level `vpc_id` bring-your-own-VPC pattern
    (`containerized/state.tf:1-9`, `serverless/state.tf:1-13`), which is singular and nullable:
    `variable "vpc_id" { type = string, default = null, description = "VPC ID. If not provided, a new
    one will be created" }`. Every SG in scope for this change (confirmed with the requester: all five
    serverless Lambdas share exactly one SG; each `containerized` SG below is single-purpose) needs
    only one ID, so this design follows the `vpc_id` shape — a singular nullable `security_group_id` —
    rather than `authorizer`'s list shape, which is specific to that one submodule's own interface.
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

- New variable(s) named `security_group_id`, `type = string`, `default = null` — one per logical SG,
  mirroring `var.vpc_id`'s exact shape and description style ("...If not provided, a new one will be
  created").
  - `null` (default) → module creates its own SG, exactly as today. No behavior change for existing
    callers that don't set the variable.
  - Non-null → module skips creating its own SG and uses the provided ID directly.
  - No separate boolean "create" flag — presence of a value is the toggle (same "presence implies
    external" spirit as `authorizer`'s convention, applied with `vpc_id`'s singular shape since no SG
    in scope needs more than one ID).
- Every `aws_security_group` resource this change touches gets `count = var.security_group_id == null ? 1 : 0`.
- Every consumer of a `count`-based SG resource's `.id` is rewritten to read from a `local` that
  resolves to the effective ID (provided vs. created) — never `aws_security_group.x.id` directly, since
  that reference breaks once `count` is added (becomes `aws_security_group.x[0].id`, which errors when
  the count is 0). Pattern: `local.effective_id = var.security_group_id != null ? var.security_group_id : aws_security_group.x[0].id`.
- Anywhere a list-typed argument is required downstream (ECS `network_configuration.security_groups`,
  `aws_lb.security_groups`, a submodule's `security_group_ids`), wrap the single effective ID:
  `[local.effective_id]` — same as how `request-handler/main.tf:339` already wraps its singular
  `var.security_group_id` today.
- No new validation that a provided SG belongs to the target VPC — matches this module's existing
  practice of not validating `vpc_id`/`private_subnet_ids` either.

### `containerized/modules/rest-service`

- Two separate variables — `ecs_alb` and `ecs_service` are logically distinct SGs with different rules
  and an ingress dependency between them, and are toggled **independently** (you may provide one and
  let the module create the other; both-or-neither is not required):
  - `alb_security_group_id` (`string`, default `null`) — toggles `aws_security_group.ecs_alb`.
  - `ecs_service_security_group_id` (`string`, default `null`) — toggles `aws_security_group.ecs_service`.
- `aws_security_group.ecs_alb` (`main.tf:144`) gets `count = var.alb_security_group_id == null ? 1 : 0`.
- `aws_security_group.ecs_service` (`main.tf:164`) gets `count = var.ecs_service_security_group_id == null ? 1 : 0`.
- New locals resolve the effective IDs:
  - `local.alb_security_group_id` = `var.alb_security_group_id` if set, else `aws_security_group.ecs_alb[0].id`.
  - `local.ecs_service_security_group_id` = `var.ecs_service_security_group_id` if set, else `aws_security_group.ecs_service[0].id`.
- `ecs_service`'s ingress rule (`main.tf:168-173`, currently `security_groups =
  [aws_security_group.ecs_alb.id]`) must reference `[local.alb_security_group_id]` instead — this holds
  regardless of whether the ALB SG was created or provided, so the ECS task always allows ingress from
  whichever ALB SG is actually in effect.
- `aws_lb.app.security_groups` (`main.tf:191`) → `[local.alb_security_group_id]`.
- The `ecs_service` submodule call's `security_group_ids` (`main.tf:295`) →
  `[local.ecs_service_security_group_id]`.
- `outputs.tf:41-49` (`security_group_id`, `alb_security_group_id`) must expose the **effective** local,
  not the raw resource attribute — required because `containerized/api_gateway.tf:24` consumes
  `module.rest_service.alb_security_group_id` for the VPC Link, and that must resolve correctly whether
  the ALB SG was created or user-provided.
### `containerized/modules/agent-runner`

- New variable: `security_group_id` (`string`, default `null`).
- `aws_security_group.agent_runner` (`main.tf:277`) gets `count = var.security_group_id == null ? 1 : 0`.
- New local `local.security_group_id` resolves to `var.security_group_id` if set, else
  `aws_security_group.agent_runner[0].id`.
- `aws_ecs_service.agent_runner.network_configuration.security_groups` (`main.tf:343`) →
  `[local.security_group_id]`.
- `outputs.tf:21-24` (`security_group_id`) exposes the effective value (still not consumed at the
  containerized root today, but should stay correct for any future/external consumer).
### `containerized` root (`state.tf`, `variables.tf`, `rest_service.tf`, `queue_mode.tf`)

- New root-level variables, one per independently-toggleable SG, each `string` default `null`,
  following `vpc_id`'s exact convention at this layer:
  - `alb_security_group_id`
  - `ecs_service_security_group_id`
  - `agent_runner_security_group_id`
- All three are always declared regardless of mode. Confirmed current behavior: `rest_service.tf`'s
  `module "rest_service"` call is unconditional, so the ALB SG and ECS-service SG exist in **every**
  mode (2 SGs in normal/non-queue mode). `queue_mode.tf`'s `module "agent_runner"` call has
  `count = var.queue_mode ? 1 : 0`, so the agent-runner SG (the 3rd) only exists — and
  `agent_runner_security_group_id` only has any effect — when `queue_mode = true`. This matches how
  other queue-mode-only variables (e.g. `var.agent_runner`) already behave: harmlessly ignored outside
  queue mode.
- `rest_service.tf`'s `module "rest_service"` call passes `alb_security_group_id` and
  `ecs_service_security_group_id` straight through.
- `queue_mode.tf`'s `module "agent_runner"` call passes `agent_runner_security_group_id` through as
  that module's `security_group_id`.
- No change to `containerized/api_gateway.tf:24` itself — it keeps consuming
  `module.rest_service.alb_security_group_id`, which now resolves correctly in both create and
  provided-SG cases per the rest-service change above.

### `serverless/state.tf`

- New root-level variable: `security_group_id` (`string`, default `null`) — one ID shared by all five
  Lambda submodules, confirmed with the requester (all serverless Lambdas use the same SG; no submodule
  needs a distinct one).
- `aws_security_group.lambda` (`state.tf:92`) gets `count = var.security_group_id == null ? 1 : 0`.
- `local.security_group_id` (`state.tf:14`) changes from `aws_security_group.lambda.id` to:
  `var.security_group_id != null ? var.security_group_id : aws_security_group.lambda[0].id`.
- No changes needed at any of the five submodule call sites (`module.authorizer` `state.tf:183`,
  `module.ws_connection_handler` `state.tf:531`, `module.request_handler` `state.tf:559`,
  `module.agent_runner` `state.tf:690`, `module.response_handler` `state.tf:708`) — they already
  reference `local.security_group_id` (wrapped in `[...]` for `authorizer`, singular for the other
  four), and that local now transparently resolves to either the created or the provided ID.
- New output at the serverless root: `security_group_id`, exposing `local.security_group_id` — issue
  #689 explicitly asks for a `lambda_security_group_id`-style output; no SG output currently exists at
  either root module (`containerized/outputs.tf`, `serverless/outputs.tf` — verified, neither has one
  today). `containerized` root gets equivalent outputs for its three SGs for the same reason (external
  consumers need to discover the effective ID either way).

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

All four questions raised in the previous review cycle are now resolved and folded into the
Requirements above:

1. ~~Fan the serverless list out to all five submodules?~~ Moot — all five Lambdas share exactly one SG
   (confirmed), so the variable is singular and no submodule needs changing.
2. ~~Root-level output naming for `serverless`?~~ Singular `security_group_id`, per (1).
3. ~~containerized root variable granularity?~~ Three flat singular variables
   (`alb_security_group_id`, `ecs_service_security_group_id`, `agent_runner_security_group_id`),
   matching `vpc_id`'s existing flat-variable convention at that layer; confirmed normal mode uses the
   first two, queue mode adds the third.
4. ~~Independent vs. both-or-neither toggle for `rest-service`'s two SGs?~~ Independent — you may
   provide an ID for one and let the module create the other.

No open questions remain. Ready for `spec.md` once this design is confirmed as final.

---

## Phase 2: Wire bring-your-own security groups into the weekly integration test flow

Phase 1 (above) adds the opt-in variables but nothing in CI ever sets them — every example still takes
the `null`-default create-path. This phase wires the new variables into
`.github/workflows/integration-test-weekly.yaml`, mirroring the existing `vpc_id`/`private_subnet_ids`
base-deployment pattern, so the bring-your-own-SG path is actually exercised weekly, not just left
dormant. Scope: the `weekly` tier only.

### Motivation

- `docs/specs/689-security-group-from-outside/plan.md:74-78` (Iteration 5) explicitly deferred this:
  "Extending that matrix to also pass a pre-created SG id is optional follow-up, not part of this plan."
  This phase is that follow-up.
- **How the existing `vpc_id`/`private_subnet_ids` base pattern works today:**
  - `.github/integration-test-config.yaml:5-8` — `deployment_base` names exactly one entry:
    `type: aws-serverless`, `path: examples/aws-serverless/openai`.
  - `.github/scripts/generate_test_matrix.py:64-66` — `base = config['deployment_base'][0]  # Assume
    single base deployment`. The single-base assumption lives in this Python script, not in the YAML
    shape (`deployment_base` is already a YAML list).
  - `.github/workflows/integration-test-weekly.yaml:85-156` (`deploy-openai`) deploys the base once via
    `run_single_test.py --action deploy` (and a non-blocking `--action test`). **There is no matching
    destroy step anywhere in this workflow for the base** (confirmed: no `--action destroy` call for
    `deployment-base` exists in the file) — unlike every matrix example, which gets an explicit Destroy
    step (`workflow:316-335`). The base's `terraform apply` runs idempotently against persisted remote
    state every week: it creates resources once, then no-ops on subsequent runs. It is never torn down.
  - `.github/workflows/integration-test-weekly.yaml:158-193` (`get-base-outputs`) runs
    `.github/scripts/get_base_outputs.py`, which does `terraform output -raw vpc_id` /
    `terraform output -json private_subnet_ids` against the base's state and writes them to
    `$GITHUB_OUTPUT` (`get_base_outputs.py:47-78`).
  - `.github/workflows/integration-test-weekly.yaml:291-293` and `:332-334` — the `run-tests` matrix
    job's Deploy/Destroy steps append `--vpc-id`/`--private-subnet-ids` to `run_single_test.py`'s args
    whenever `matrix.type` starts with `aws-` (covers both `aws-serverless` and `aws-containerized`
    matrix entries).
  - `.github/scripts/run_single_test.py:760-761` (CLI args), `:591-599`/`:657-666`
    (`destroy_aws_resources`/`deploy_aws_resources`) — turns `--vpc-id`/`--private-subnet-ids` into
    `TF_VAR_vpc_id`/`TF_VAR_private_subnet_ids` env vars before invoking Terraform.
  - `examples/aws-serverless/openai/deploy/outputs.tf` — the only example whose `outputs.tf` exposes
    `vpc_id`/`private_subnet_ids`; every other AWS example's `deploy/variables.tf` declares them as
    **required, no-default** inputs (e.g. `examples/aws-serverless/crewai/deploy/variables.tf`,
    `examples/aws-containerized/adk/deploy/variables.tf`) and threads them into its `module` block.
- **Serverless composes directly onto the existing base, containerized does not:**
  - Phase 1 gives `serverless` **one** shared `security_group_id` (`ak-deployment/ak-aws/serverless/{variables.tf,outputs.tf,state.tf}`)
    — every Lambda submodule already shares one SG, so this slots directly into the existing `openai`
    base with zero extra AWS cost (a security group is a free, instant-to-create/delete resource; the
    base already pays for the VPC/NAT it lives in).
  - Phase 1 gives `containerized` **three independent** variables (`alb_security_group_id`,
    `ecs_service_security_group_id`, `agent_runner_security_group_id`) with different ingress shapes
    (ALB needs port-80 ingress; ECS-service needs ingress from the ALB SG; agent-runner is egress-only)
    — these do not map onto a Lambda SG's shape, and no containerized "base" exists today. Every
    `aws-containerized` weekly example currently gets its VPC/subnets from the *same* `aws-serverless`
    base (`workflow:291,332` match on `aws-*`, not `aws-serverless` specifically), but there is no
    equivalent shared source for containerized-only SGs.
  - Verified via grep: all 6 weekly `aws-containerized` examples
    (`adk`, `openai-dynamodb`, `crewai`, `mcp/multi`, `openai-dynamodb-scalable`, `openai-schedule`) set
    `container_port = 8000` in their `deploy/main.tf`. Two of them
    (`openai-dynamodb-scalable`, `openai-schedule`) set `queue_mode = true`; the other four omit it
    (defaults `false`).
  - Rejected option: promote an existing full example (e.g. `openai-dynamodb`) to a second persistent
    base. Its ECS Fargate task + ALB would run 24/7 like the base's other resources, incurring real
    recurring cost — unlike the serverless base (Lambda has no idle cost) or a bare security group
    (free regardless of lifetime). Decided against in favor of a minimal SG-only base (below).
- **CI already ignores each example's pinned module `version` and registry `source`, so Phase 1's
  unpublished module changes are already usable in CI without any version bump:**
  `scripts/deploy/inject_dependencies.py:262-320` (`_rewrite_module_block`) rewrites every example's
  `module` block `source` from the registry (`yaalalabs/ak-containerized/aws`,
  `yaalalabs/ak-serverless/aws`) to the in-repo local path (`ak-deployment/ak-aws/containerized` /
  `serverless`) and comments out the pinned `version = "..."` line, before `terraform init` runs in
  every relevant CI step (`workflow:122-123`, `:190`, `:263-265`). CI therefore always exercises the
  current branch's local module code. This phase requires no module-registry publish and no version-pin
  changes anywhere.

### Requirements

#### Serverless: reuse the existing `openai` base

- `examples/aws-serverless/openai/deploy/outputs.tf` gains one output:
  `security_group_id = module.serverless_agents.security_group_id`, alongside the existing `vpc_id` /
  `private_subnet_ids` outputs there.
- Every other `aws-serverless` weekly example (`adk`, `crewai`, `langgraph`, `scalable-openai`,
  `openai-auth`, `schedule-openai`) gains a new required variable `security_group_id`
  (`type = string`, no default — same shape as their existing `vpc_id`), threaded into their
  `module "serverless_agents"` call as `security_group_id = var.security_group_id`.

#### Containerized: a new, minimal, CI-only security-group base — kept separate from the Terraform modules

- New standalone Terraform root, **not** part of `ak-deployment/ak-aws/containerized` and **not** a
  customer-facing `examples/` entry (explicit requirement: this exists only for integration testing).
  Proposed location: `.github/integration-tests/containerized-security-group-base/` (exact path is an
  open question below).
- Declares exactly one resource: a single `aws_security_group`, created in the shared VPC (`vpc_id` /
  `vpc_cidr` taken as input variables, sourced from the existing serverless base's `vpc_id` output plus
  the known `vpc_cidr`), with:
  - Ingress: port 80 from `vpc_cidr` (covers the ALB role).
  - Ingress: port 8000 from itself, i.e. a self-referencing security-group rule (covers the ECS-service
    role — every weekly containerized example uses `container_port = 8000`).
  - Egress: all traffic (covers the agent-runner role, which only ever needs egress).
- One output: `security_group_id`. Confirmed decision: the **same** ID is passed downstream as all three
  of `alb_security_group_id`, `ecs_service_security_group_id`, and `agent_runner_security_group_id` — a
  single shared SG standing in for all three roles is sufficient to exercise the bring-your-own-SG code
  path; it is not a faithful reproduction of the module's real 3-SG topology (see Non-goals).
- Has its own Terraform backend/state (exact backend key convention is a spec.md detail, following
  whatever pattern other `deploy/` dirs use).
- Deployed the same way the `openai` base is: idempotent `terraform apply`, never destroyed. This is
  safe specifically because it is *only* a security group — free to leave running indefinitely, unlike a
  full ECS+ALB base (see Motivation).
- Every `aws-containerized` weekly example gains three new required variables —
  `alb_security_group_id`, `ecs_service_security_group_id`, `agent_runner_security_group_id` (all
  `type = string`, no default) — threaded into their `module` call as the matching arguments.
  All six examples declare and pass all three uniformly, regardless of `queue_mode`: Phase 1's own
  design already establishes that `agent_runner_security_group_id` is harmlessly ignored by the module
  when `queue_mode = false` (`design.md:139-145`, same precedent as the existing `var.agent_runner`
  variable), so no per-example conditional variable set is needed.

#### CI plumbing

- `.github/integration-test-config.yaml`: `deployment_base` becomes a 2-entry list — the existing
  `aws-serverless` / `examples/aws-serverless/openai` entry stays at index 0; a new second entry is
  appended at index 1 for the containerized SG base (`type`, `path`, `deploy_dir` — exact `type` string
  TBD, e.g. `aws-containerized-sg-base`). **Ordering is significant** — see below.
- `.github/scripts/generate_test_matrix.py`: change the `deployment_base` handling
  (currently `generate_test_matrix.py:64-66`, `base = config['deployment_base'][0]`) to expose the
  **full** list instead of only index 0, under a new output name (e.g. `deployment-bases`, plural).
  Grep confirms no other script currently reads the singular `deployment-base` matrix-generator output
  besides this workflow, which is updated in the same change.
- `.github/workflows/integration-test-weekly.yaml`:
  - `setup` job's outputs gain the new plural `deployment-bases` list (or two explicit named outputs,
    one per known index — naming finalized in spec.md).
  - A new `deploy-containerized-sg-base` job, mirroring `deploy-openai` (`workflow:85-156`): deploys
    (never destroys) the new base.
  - A new `get-containerized-sg-base-outputs` job, mirroring `get-base-outputs` (`workflow:158-193`):
    captures the base's `security_group_id` output.
  - `run-tests`'s Deploy/Destroy steps (`workflow:273-294`, `:316-335`): the existing
    `if [[ "${{ matrix.type }}" == aws-* ]]` block is extended so that, additionally: when
    `matrix.type == 'aws-serverless'`, a `--security-group-id` arg is appended (from the existing
    `get-base-outputs` job's new `security_group_id` output); when `matrix.type == 'aws-containerized'`,
    `--alb-security-group-id` / `--ecs-service-security-group-id` / `--agent-runner-security-group-id`
    args are appended (from the new `get-containerized-sg-base-outputs` job's output, all three set to
    the same value).
- `.github/scripts/get_base_outputs.py`: extended so it can also retrieve a `security_group_id` output
  (either as an added fixed capture alongside `vpc_id`/`private_subnet_ids` when querying the serverless
  base, or via a second invocation against the containerized SG base — exact shape is a spec.md
  decision).
- `.github/scripts/run_single_test.py`: new CLI args `--security-group-id`,
  `--alb-security-group-id`, `--ecs-service-security-group-id`, `--agent-runner-security-group-id`.
  `deploy_aws_resources`/`destroy_aws_resources` (`run_single_test.py:572`, `:637`) gain matching
  `if <arg>: tf_env['TF_VAR_<name>'] = <arg>` blocks, exactly mirroring the existing
  `TF_VAR_vpc_id`/`TF_VAR_private_subnet_ids` pattern (`:591-599`, `:657-666`).

### Non-goals

- Redis/Valkey SGs remain out of scope (unchanged from Phase 1).
- No generic N-base mechanism: GitHub Actions matrix jobs do not cleanly aggregate dynamic, per-leg
  named outputs, so this phase hardcodes exactly two named base job pairs (serverless VPC/SG base,
  containerized SG-only base) addressed by list index, rather than building a fully generic
  loop-over-bases mechanism. Revisit only if a third base is ever needed.
- No change to the `nightly` tier or to the azure/gcp test flows.
- The CI base does not reproduce the containerized module's real 3-distinct-SG topology (separate ALB /
  ECS-service / agent-runner SGs with different rules) — one shared SG standing in for all three is
  judged sufficient to exercise the bring-your-own-SG code path, not to be a realistic production
  topology.

### Open questions

1. Exact directory path/name for the new CI-only Terraform root (proposed:
   `.github/integration-tests/containerized-security-group-base/`).
2. Exact naming for the new job outputs, job IDs, and CLI flags (proposals given above under CI
   plumbing; open to bikeshedding in review).
3. Backend/state key convention for the new root — needs checking against whatever mechanism the
   existing example `deploy/` dirs use for their S3 backend key, in `spec.md`.
4. Exact shape of `get_base_outputs.py`'s extension (one generalized script vs. a second invocation) —
   deferred to `spec.md`.
