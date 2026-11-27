# #954: Pluggable cost management — Implementation Plan

Build order for [`spec.md`](spec.md); requirements are in [`design.md`](design.md). `§n` refers to spec.md sections.
Each iteration leaves `ak-py` green. Run all commands from `ak-py/`. "Lint" means `make lint-check-all` from the
repo root.

Without a `cost` block, behaviour stays unchanged through every iteration (spec Non-changes). So iterations 1–2 can merge
before any gateway exists.

## Iteration 1: Config, models, errors, extras

- **Goal:** `AKConfig.cost` parses and validates. The `cost` package imports. Nothing reads it yet.
- **Files:** `core/config.py`; `cost/__init__.py`, `cost/model.py`, `cost/errors.py`; `ak-py/pyproject.toml`; `uv.lock`.
- **Steps:**
  1. Add the `_Cost*` config models, `_CostBudgetLimit` / `_CostBudgetPeriod`, the validators, and `AKConfig.cost`
     after `identity` (Config changes).
  2. Add `cost/model.py`, with `BudgetLimit` / `BudgetPeriod` aliased from config (deviation 15), and
     `cost/errors.py` (§1, §2).
  3. Add `cost/__init__.py`, which follows the lazy `_LAZY_EXPORTS` shape (§1).
  4. Add the `cost` and `cost-agentgateway` extras, and add `langchain-litellm` to `langgraph` (Config changes). Then run
     `uv lock` and pin the `psycopg` / `langchain-litellm` versions.
- **Verify:** `uv run pytest tests/test_cost_models.py tests/test_cost_config.py`, lint, and `make lock-bounds-check`
  (not part of `lint-check-all`).

## Iteration 2: Core seams

- **Goal:** every run carries a `request_id` and makes a `RunMeter` check, and `ErrorCategory.BUDGET` exists. The
  check is a no-op until iteration 7.
- **Files:** `core/model.py`, `core/base.py`, `core/runtime.py`, `core/service.py`, `core/chat_service.py`,
  `core/meter.py` (new), `core/util/error_util.py`, `pipeline/agent_runner.py`.
- **Steps:**
  1. Request id plumbing, row by row from the §3.1 table.
  2. Add `RunMeter`, `NoOpRunMeter`, `RunMeterFactory` (`get` / `peek` / `reset`) and `BudgetDecision` (§3.2).
     `get()` imports `CostManager` lazily. Until iteration 7, a configured `cost` block fails that import with an
     `ImportError`, which is loud enough and needs no guard.
  3. Add the Runtime check in `run` and `stream` (§3.3).
  4. Add `BUDGET` and `_classify` via `peek()` (§3.4).
  5. Fix the existing tests this breaks in the same iteration. Add `request_id=None` to the fake handlers in
     `test_chat_service_core.py`, `test_chat_service_streaming.py` and `test_hitl_chat_service.py`. Add an autouse
     `RunMeterFactory.reset()` to the four `test_runtime*.py` files. Add the pipeline `body.request_id` assertions,
     the `test_error_util.py` `BUDGET` cases, and the `test_session_identity.py` reserved-key case.
- **Verify:** the runtime, deny-shape and request-id cases of `tests/test_cost_runtime.py`, using a fake meter on
  `RunMeterFactory._instance`. Then
  `uv run pytest tests/test_runtime*.py tests/test_chat_service_*.py tests/test_hitl_chat_service.py tests/test_pipeline_agent_runner*.py tests/test_error_util.py tests/test_session_identity.py`.

## Iteration 3: Gateway seam and LiteLLM

- **Goal:** the `LLMGateway` ABC, the factory, `GatewayHTTP`, the contract suite, and LiteLLM in both modes.
- **Files:** `cost/gateway/{base,factory,http,litellm}.py`; `cost/testing.py` (`LLMGatewayContract`).
- **Steps:**
  1. Add the ABC, with the `gateway_user_id` transform (coupling rule 5) and the default
     `UnsupportedCapabilityError` methods (§4).
  2. Add `GatewayHTTP` and `LLMGatewayFactory`, including the dotted-path branch (§4).
  3. Add `LiteLLMGateway`: capabilities, headers, `fetch_usage`, `fetch_usage_since`, `sync_budget_definitions` /
     `sync_budgets`, `probe`, `is_budget_refusal` (§5.1).
  4. Defer the contract case "AK headers overwrite a caller's same key". It goes through `GatewayLiteLLM.headers`,
     which lands in iteration 8.
- **Verify:** `uv run pytest tests/test_cost_gateway_litellm.py`.

## Iteration 4: Agentgateway and Langfuse

- **Goal:** the two remaining built-in gateways pass `LLMGatewayContract`.
- **Files:** `cost/gateway/agentgateway.py` (with `RequestLogDatabase`), `cost/gateway/langfuse.py`, and
  `LLMGatewayFactory` branches.
- **Steps:** §5.2 (SQLite and Postgres, migration probe, SQL), then §5.3 (headers and limits, `model_base_url`, v2 reads).
- **Verify:** `uv run pytest tests/test_cost_gateway_agentgateway.py tests/test_cost_langfuse_compat.py`.

## Iteration 5: Attribution and pricing

- **Files:** `cost/attribution.py`, `cost/pricing.py`, and the `AttributorContract` / `PricingSourceContract` suites
  in `cost/testing.py`.
- **Steps:** §9 (`Attributor`, `DefaultAttributor`, `AttributorFactory`), then §10 (passthrough and static sources,
  `PricingSourceFactory`).
- **Verify:** `uv run pytest tests/test_cost_attribution.py tests/test_cost_pricing.py`.

## Iteration 6: Spend ledger

- **Goal:** a per-user ledger document with compare-and-set on every backend.
- **Files:** `core/util/driver/redis_like.py` (`compare_and_set`); `cost/ledger/{base,factory,in_memory,redis_like,redis,valkey,dynamodb,cosmosdb,firestore}.py`;
  `SpendLedgerContract`.
- **Steps:**
  1. Add the generic driver method (§12.4 redis row) and its `test_shared_drivers.py` cases.
  2. Add `LedgerDocument` and the `SpendLedger` ABC (§12.1, §12.2).
  3. Add the backends and `SpendLedgerFactory` (§12.4).
  4. `LedgerSpendFlow` waits until iteration 7, because it needs the gateway and the policy timeouts.
- **Verify:** the per-backend contract cases in `uv run pytest tests/test_cost_ledger.py tests/test_shared_drivers.py`.

## Iteration 7: Budgets, view and `CostManager`

- **Goal:** with a `cost` block, the Runtime check enforces budgets, and `CostManager` is the live `RunMeter`.
- **Files:** `cost/budget.py`, `cost/view.py`, `cost/manager.py` (with `NativeBudgetSync`), and the remaining contract
  suites.
- **Steps:**
  1. Add `BudgetPolicy`, `NoBudgetPolicy`, `StaticBudgetPolicy`, `BudgetPolicyFactory` and `SpendReader`, with the
     `on_error` exceptions and the 10 s bound (§11.1–11.3).
  2. Add `LedgerSpendFlow` with the settle line, batch commits and `CATCH_UP_BUDGET` (§12.3).
  3. Add `NativeBudgetSync`: the synchronous part, the `ak-cost-budget-sync` background thread, lazy default upserts
     (§11.4), probes (§11.5) and refusal walking (§11.6).
  4. Add `UsageView` and `DefaultUsageView`: authorise, push down, sub-window on truncation, aggregate (§13).
  5. Add `CostManager`: the construction order, the capability checks table, `user_id_for` / `attribution_for` /
     `current_attribution`, and `run_async_sync` startup (§15).
- **Verify:** `uv run pytest tests/test_cost_budget.py tests/test_cost_ledger.py tests/test_cost_view.py tests/test_cost_runtime.py`.
  Include the `ErrorCategory.BUDGET` chain and cycle cases against a real gateway refusal.

## Iteration 8: Gateway client and Agent Kernel's own calls

- **Goal:** every LLM call Agent Kernel makes goes through the gateway when cost is configured.
- **Files:** `cost/client.py`; `core/multimodal/hooks.py`, `core/multimodal/tools.py`;
  `integration/thread/{recorder,manager,naming}.py`; `guardrail/openai.py`.
- **Steps:**
  1. Add `GatewayLiteLLM` and `CostManager.attribution_headers()` (§6).
  2. Route the multimodal hook (§8.1) and `analyze_attachments` (§8.2) through it.
  3. Thread naming: pass attribution down, fall back to `ak-system`, and check the signature for BYO strategies (§8.3).
     Update `test_thread_manager.py` here (the `_complete` patch gains `attribution`, plus the new cost cases).
  4. OpenAI guardrails get the base URL, key and per-call headers (§8.4).
  5. Add the deferred header-overwrite case to `LLMGatewayContract`.
- **Verify:** `uv run pytest tests/test_cost_client.py tests/test_thread_*.py tests/test_multimodal_*.py tests/test_cost_gateway_*.py tests/test_cost_langfuse_compat.py`.

## Iteration 9: Framework bindings

- **Goal:** each supported framework has a gateway-routed model or run-options path.
- **Files:** `framework/{openai,adk,smolagents,crewai,maf,langgraph}/cost.py` and each package's `__init__.py`
  (guarded import); `framework/claude/claude.py`; `CostRunOptions` in `cost/client.py`.
- **Steps:**
  1. Add §7.1–7.6 one framework at a time, each with its context-propagation test case. The LangChain seam is
     confirmed first against the locked `langchain-litellm`. If it differs, take §7.6's fallback.
  2. Claude `env` injection (§7.7).
  3. `CostRunOptions.wrap` for OpenAI, Pydantic AI and ADK (§7.8).
- **Verify:** `uv run pytest tests/test_cost_bindings.py tests/test_cost_claude_env.py tests/test_claude_runner.py`.

## Iteration 10: Usage REST API

- **Files:** `cost/handler.py`; the lazy export in `cost/__init__.py`.
- **Steps:** add `UsageRESTRequestHandler`, with its check order, exception-to-status mapping and the 93-day window
  (§14).
- **Verify:** `uv run pytest tests/test_cost_handler.py`, including "importing `agentkernel.cost` loads no FastAPI".

## Iteration 11: AWS Terraform

- **Files:** in `ak-deployment/ak-aws/{serverless,containerized}/`: `variables.tf`, `state.tf`, `outputs.tf`,
  `README.md`, and the wired modules' `variables.tf` / `main.tf`. Serverless wires request-handler and agent-runner.
  Containerized wires rest-service and agent-runner.
- **Steps:** copy the thread-table wiring row by row from the spec's Deployment table, then add the README section
  (rules 1–4).
- **Verify:** in both stacks, `terraform fmt -check` and `terraform init -backend=false && terraform validate`. Then
  run `terraform plan` from `examples/aws-serverless/openai` with the flag on and off. The diff should show only the
  table, the policies, the attachments and the env var.

## Iteration 12: Example

- **Files:** `examples/api/cost-litellm/`: Docker Compose with the LiteLLM proxy and Postgres, `config.yaml`, an
  `app.py` with `GatewayLitellmModel` and `UsageRESTRequestHandler`, `app_test.py`, and a README.
- **Steps:** build it as the spec's Documentation section describes. `app_test.py` makes one call, reads
  `/api/v1/usage`, then exceeds a tiny budget.
- **Verify:** `docker compose up`, then `uv run pytest app_test.py` in the example. Then lint, which covers
  `examples/`.

## Iteration 13: Tests

Every new test file has already landed with its component in iterations 1–10. This iteration closes the remaining
gaps:

1. `tests/test_cost_litellm_live.py`, gated on `AK_TEST_LITELLM_URL`, run against the example's proxy. It pins the
   **unverified** LiteLLM claims: the `startTime` ordering, the budget "already exists" text, the refusal body shape
   and the cached-token key path.
2. Add the `cost.gateway.api_key` / `admin_key` / `database.url` rows to `test_secret_consumers.py`. Its table is
   hand-maintained, one function per consumer, so it does not fail before then.
3. Check every row of the spec's "Existing tests that change" table against the iteration that made the change.
4. Targeted: the command in spec.md's Testing section. Full suite: `uv run pytest`. Expect the pre-existing env-dependent e2e failures described in `AGENTS.md`. Then run
   `make lint-check-all`.

## Iteration 14: Sync docs and skills

| Surface | Change |
|---|---|
| `docs/docs/advanced/cost.md` (new) | the topics in spec.md's Documentation section |
| `docs/sidebars.js:153-156` | add `'advanced/cost'` to the Advanced Features list (after `advanced/identity-and-access`, `:153`) |
| `docs/docs/advanced/secrets.md` | the three new secret fields (near the framework consumers, `:85`) |
| `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` | menu item 17 "Cost Management" after `:53`, and a `####` section under Step 3 (`:55`) |
| `ak-py/src/agentkernel/skills/ak-build/SKILL.md` | the coverage rule: LLM calls go through `GatewayLiteLLM`, a binding, or `attribution_headers()`, under Common Gotchas (`:553`) |
| `.agents/skills/ak-dev-architecture/SKILL.md` | a new `## Cost Management` section after Identity and Access (`:827`); entries under Directory Structure (`:1302`), the `AKConfig` key sections (`:279`, add `cost`), and Execution Flow (`:1705`, the budget check before pre-hooks) |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | the contract-suite list (`:37-40`) gains the six cost suites, and the test-file table gains the `test_cost_*.py` rows |
| `.agents/skills/ak-dev-new-framework-integration/SKILL.md` | a step for "add a gateway binding in `framework/<fw>/cost.py`", plus a Checklist (`:427`) entry |
| `ak-deployment/ak-aws/*/README.md` | done in iteration 11 |

No update is needed for the GCP, Azure or `ak-k8s` Helm surfaces, which are out of scope for #954 (spec Deployment).
Before merge, confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows.
