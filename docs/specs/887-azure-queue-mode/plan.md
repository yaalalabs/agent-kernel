# #887: Queue mode on Azure — Implementation Plan

Builds [spec.md](spec.md) in order. Each iteration leaves the branch green.

## Iteration 1: Config and dependencies

- **Goal:** `execution.queues.servicebus` loads; the `azure` extra carries the Service Bus SDKs.
- **Files:** `ak-py/src/agentkernel/core/config.py`, `ak-py/pyproject.toml`, `ak-py/uv.lock`, a config test.
- **Steps:**
  1. Add `_ServiceBusQueueConfig` and the `_QueuesConfig.servicebus` field; widen the `type` and `url`
     descriptions (spec §4).
  2. Add `azure-servicebus` and `azure-identity` to the `azure` extra; `uv lock` (spec §5).
  3. Config test: the block loads from YAML and from `AK_EXECUTION__QUEUES__SERVICEBUS__*`; old YAML unchanged.
- **Verify:** `cd ak-py && uv run pytest tests/test_config*.py`

## Iteration 2: Transport, fake and contract

- **Goal:** `ServiceBusTransport` passes `QueueTransportContract` against the fake, and the factory builds it.
- **Files:** `ak-py/src/agentkernel/pipeline/transport/servicebus.py`,
  `ak-py/src/agentkernel/pipeline/transport/base.py`, `ak-py/tests/test_pipeline_servicebus_transport.py`,
  `ak-py/tests/test_pipeline_factory_seams.py`.
- **Steps:**
  1. Write the SDK fake first (spec Testing), then the contract subclass, red.
  2. Implement addressing, auth, send (spec §1 rules 1–3).
  3. Implement the session-held consumer: fetch, settle, renew, close (spec §1 rules 4–6).
  4. Factory branch and `_BUILTIN_TYPES` (spec §2); factory and seam tests.
  5. Unit tests listed in spec Testing.
- **Verify:** `cd ak-py && uv run pytest tests/test_pipeline_servicebus_transport.py tests/test_pipeline_factory_seams.py tests/test_transport_contract.py`

## Iteration 3: Terraform `queue_mode`

- **Goal:** `ak-azure/containerized` plans an edge, a runner, a namespace and two queues with `queue_mode = true`,
  and an unchanged plan with `false`.
- **Files:** `ak-deployment/ak-azure/containerized/{queue_mode.tf,container_app.tf,variables.tf,outputs.tf,README.md}`.
- **Steps:**
  1. Variables and validation (spec §6).
  2. `queue_mode.tf`: namespace, queues, runner app with the KEDA rule (`identity_id = "System"`), role
     assignments, locals.
  3. `container_app.tf`: edge env merge, `redis-url` secret, grace period, all gated on `queue_mode`.
  4. Outputs; README inputs/outputs tables.
- **Verify:** `terraform fmt -check -recursive && terraform validate` in `ak-azure/containerized`; then
  `terraform plan` from a scratch root that sources the module by local path, once per `queue_mode` value.
  The `false` plan must match a plan of `develop`.

## Iteration 4: Example and weekly wiring

- **Goal:** `examples/azure-containerized/openai-queue-mode/` deploys, answers `rest_sync` through APIM, and
  runs the live contract.
- **Files:** the example directory (spec §7), `.github/scripts/run_single_test.py`,
  `.github/integration-test-config.yaml`, `.github/workflows/integration-test-weekly.yaml`, and the module's
  `servicebus_namespace_id` output.
- **Steps:**
  1. Copy `openai-cosmos` and `examples/k8s/openai-queue-mode/` into the new shape; split the entry points.
  2. `deploy/` with `queue_mode = true`, the Data Owner grant for the deploying principal, the two outputs.
     Leave the registry `version` pin alone (the release chore bumps it).
  3. `app_test.py` (rest_sync multi-turn) and `servicebus_contract_test.py`.
  4. Export `AK_TEST_SERVICEBUS_NAMESPACE` from `test_azure_deployment` when the output exists; then refresh the
     az login, `build.sh local`, and `uv run --no-sync pytest`.
  5. Weekly entry in `integration-test-config.yaml`.
- **Verify:** a manual `run_single_test.py --type azure-containerized --path examples/azure-containerized/openai-queue-mode`
  with `--action deploy`, `test`, then `destroy`, against the module by local path. The contract tests prove
  that Data Owner can create queues through `ServiceBusAdministrationClient` and that a lost session lock
  redelivers with `delivery_count + 1` (the two behaviours the fake can only assume). Also confirm the runner
  scales out on queue length (the KEDA rule's `System` identity reads the queue with its Data Owner role). Check the namespace
  is gone after destroy, so a leaked one doesn't break the next weekly run with "already exists".

## Iteration 5: Tests

- **Goal:** the full suite and lint are green, and the risky consumer path is covered.
- **Files:** none new beyond iterations 1–4, unless a gap shows up.
- **Steps:**
  1. Run the full `ak-py` suite: the in-memory, SQS, NATS and Kafka contract subclasses are unaffected by the
     factory change.
  2. Confirm spec Testing is covered item by item, especially session reuse vs one-in-flight and lost-lock
     pruning.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all` at the repo root.

## Iteration 6: Sync docs and skills

- **Goal:** every list that reads as the complete set of transports names `servicebus`, and the Azure deploy
  docs describe queue mode. Mentions that are only examples stay as they are.
- **Files:**
  - `docs/docs/advanced/queue-mode-guide.md`: both transport tables and a short "Running Queue Mode on Azure
    Service Bus" section.
  - `docs/docs/deployment/azure-containerized.md`: a Queue Mode section (`queue_mode`, `agent_runner_command`,
    Redis requirement, no WebSocket or scheduling yet).
  - `docs/docs/core-concepts/configuration.md`: the two `type` lists (the page documents no other transport's
    block, so no `servicebus` block).
  - One-word list fixes: `docs/docs/api/a2a-server.md`, `docs/docs/api/mcp-server.md`,
    `docs/docs/integrations/agui.md`, `docs/docs/deployment/overview.md`, `docs/docs/agent-skills.md`,
    `docs/src/pages/features.tsx`, `docs/src/components/FeatureExplorer/data.tsx`.
  - An "Azure Service Bus" `Queue` tile in `docs/src/components/IntegrationsMarquee/data.tsx` (reuses `VscAzure`).
  - Skills: `.agents/skills/ak-dev-architecture/SKILL.md`, `.agents/skills/ak-dev-new-queue-transport/SKILL.md`,
    bundled `ak-cloud-deploy` (an Azure queue mode subsection; `queue_mode` is no longer AWS-only) and
    `ak-add-capabilities`.
  - Cut, nothing on them becomes false: `azure-serverless.md` (unchanged), `scheduling.md` (Service Bus does not
    support scheduling yet, so its list stays right), and the two sync-skill sweeps (replaced by the grep below). Not touched: `docs/versioned_docs/`, Helm docs.
- **Verify:** `cd docs && npm run build`; `git grep -n -i "Kafka, or NATS\|SQS/Kafka/NATS[^/]\|Kafka or NATS"`
  over `docs/docs docs/src ak-py/src/agentkernel/skills .agents/skills` finds nothing.
