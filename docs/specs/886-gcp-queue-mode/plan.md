# #886: Queue mode on GCP — Implementation Plan

Builds [spec.md](spec.md) in order. Each iteration leaves the branch green. Section numbers (§) are
spec sections. Start only after the [§7](spec.md#7-design-amendments-for-re-review) amendments are
re-reviewed.

## Iteration 1: Delivery bookkeeping

- **Goal:** Kafka (and later Pub/Sub) gets durable bookkeeping from a Redis or Valkey response
  store, and the store can remember acked messages.
- **Files:** `ak-py/src/agentkernel/pipeline/transport/bookkeeping.py`,
  `ak-py/tests/test_pipeline_bookkeeping.py`.
- **Steps:**
  1. Add the response-store step to `BookkeepingStoreFactory.create` and update the fallback warning (§2.1).
  2. Add `mark_acked` / `was_acked` to the ABC and both stores; add the `ak:qacked:` driver (§2.2).
  3. Extend `_cfg` and add the tests listed in Testing → "Changed: test_pipeline_bookkeeping.py".
- **Verify:** `cd ak-py && uv run pytest tests/test_pipeline_bookkeeping.py tests/test_pipeline_kafka_transport.py`

## Iteration 2: Pub/Sub transport

- **Goal:** `execution.queues.type: pubsub` builds a transport that passes the full contract against
  the fake broker.
- **Files:** `ak-py/pyproject.toml`, `ak-py/uv.lock`, `ak-py/src/agentkernel/core/config.py`,
  `ak-py/src/agentkernel/pipeline/transport/{base,pubsub}.py`,
  `ak-py/tests/test_pipeline_pubsub_transport.py`, `ak-py/tests/test_config.py`,
  `ak-py/tests/test_packaging_extras.py`.
- **Steps:**
  1. Add the `pubsub` extra and refresh the lock (§4).
  2. Add `_PubSubQueueConfig` and `_QueuesConfig.pubsub` (§3).
  3. Write `PubSubEnvelopeCodec` (§1.4), then the send side and provisioning (§1.7, §1.8).
  4. Write `PubSubTransportConsumer` and `_LeaseKeeper` (§1.5, §1.6).
  5. Add the factory branch and `_BUILTIN_TYPES` entry (§4).
  6. Build the fake broker and the test classes, contract subclass included (Testing → "New: test_pipeline_pubsub_transport.py").
- **Verify:** `cd ak-py && uv run pytest tests/test_pipeline_pubsub_transport.py tests/test_config.py tests/test_packaging_extras.py tests/test_pipeline_factory_seams.py`

## Iteration 3: Emulator example and live contract

- **Goal:** the transport is proven on a real Pub/Sub implementation, in CI on every PR.
- **Files:** `examples/transport/pubsub/` (`app.py`, `config.yaml`, `docker-compose.yaml`,
  `pubsub_tester.py`, `app_test.py`, `build.sh`, `pyproject.toml`, `test-config.yaml`, `tool.py`,
  `README.md`), `ak-py/tests/test_transport_contract_live.py`,
  `.github/workflows/test-reusable.yaml`, `.github/test-config.yaml`.
- **Steps:**
  1. Copy the `examples/transport/nats/` shape: emulator and Valkey services with healthchecks,
     `auto_provision: true`, Valkey session and response store.
  2. `pubsub_tester.py`: `up`, `provision`, `tail`, `publish`, `purge`, `down`, and `latency`
     (sends N messages to an idle consumer and reports the slowest delivery).
  3. `app_test.py`: `rest_sync`, multi-turn, poison message reaching the dead-letter subscription.
  4. Add `TestPubSubTransportContractLive` and the stable-message-id test.
  5. Wire the emulator into `transport-integration-tests` and register the example.
- **Verify:**
  - `docker compose -f examples/transport/pubsub/docker-compose.yaml up -d --wait pubsub`, then
    `AK_TEST_PUBSUB_EMULATOR_HOST=localhost:8085 uv run pytest tests/test_transport_contract_live.py -k PubSub --no-cov -v`.
  - `cd examples/transport/pubsub && ./build.sh local && uv run pytest -s`.
  - **Decision point (amendment 3):** run `pubsub_tester.py latency`. If deliveries stall near
    10 s more than rarely, stop and take the streaming-pull question back to design review.

## Iteration 4: Cloud Run entry point

- **Goal:** `CloudRun.run()` starts the edge on a broker transport and is unchanged on `in_memory`.
- **Files:** `ak-py/src/agentkernel/deployment/gcp/akcloudrun.py`, `ak-py/tests/test_gcp_cloudrun.py`.
- **Steps:**
  1. Implement `run(handlers=None)` with the `async`/`realtime` refusal (§6).
  2. Add the tests (Testing → "New: test_gcp_cloudrun.py").
- **Verify:** `cd ak-py && uv run pytest tests/test_gcp_cloudrun.py tests/test_api_http.py tests/test_pipeline_io_handler.py`

## Iteration 5: Terraform no-op refactors

- **Goal:** the shared groundwork lands with no change to any existing plan.
- **Files:** both roots' `state.tf`, `cloud_run.tf` / `cloud_function.tf`, `api_gateway.tf`,
  `main.tf`; `ak-deployment/ak-gcp/common/versions.tf`.
- **Steps:**
  1. Move the session and thread env entries into `local.session_env` (§5.5).
  2. Change the API Gateway builder to group methods per path (§5.5).
  3. Raise the provider floors to `>= 6.37.0` (§5.5).
- **Verify:**
  - `terraform fmt -check -recursive ak-deployment/ak-gcp` and `terraform validate` in both roots.
  - `terraform plan` of `examples/gcp-serverless/openai` and `examples/gcp-containerized/openai`
    against a live deployment: **no changes**, including the API Gateway config.
  - Read `run.googleapis.com/cpu-throttling` on that live service to settle amendment 5.

## Iteration 6: Terraform queue mode

- **Goal:** queue mode (the default) deploys the edge, a private agent-runner service that Pub/Sub
  pushes requests to, the Pub/Sub objects and IAM. _Reworked 2026-11-09: push replaced the worker pool
  and CREMA first built here (spec §7 item 9)._
- **Files:** `ak-deployment/ak-gcp/common/modules/pubsub/{main,variables,outputs}.tf` + `README.md`,
  `ak-deployment/ak-gcp/common/modules/agent-runner/{main,variables,outputs}.tf` + `README.md`;
  in both roots: `queue_mode.tf` (new), `variables.tf`, `state.tf`, `cloud_run.tf` /
  `cloud_function.tf`, `outputs.tf`, `README.md`; `containerized/run.md`, `common/run.md`.
- **Steps:**
  1. Module `pubsub` (§5.2).
  2. Module `agent-runner`: the runner service, its identity and the push identity (§5.3).
  3. Root variables and their validations (§5.4).
  4. `queue_mode.tf`: modules, runner image, edge IAM, `local.queue_env`, `cpu_idle` (§5.5).
  5. Queue-mode gateway routes (§5.5).
  6. The push path in Python: `PubSubPushReceiver` (§1.9) and `CloudRunAgentRunner` (§6), with
     their unit tests and the live push test on the emulator.
  7. Add the APIs to `run.md` and document the new variables in the root READMEs.
- **Verify:** `terraform validate` in both roots; the `terraform plan` checks from
  Testing → Terraform; `uv run pytest tests/test_pipeline_pubsub_transport.py tests/test_gcp_cloudrun.py`
  and the live push test; a queue-mode apply in the CI project followed by one chat request (done
  in iteration 7).

## Iteration 7: GCP queue-mode example and weekly test

- **Goal:** a deployed two-tier GCP app answers chat over Pub/Sub, and the weekly run keeps proving it.
- **Files:** `examples/gcp-serverless/openai-queue-mode/` (`app.py` with `main()` → `CloudRun.run()`
  and `runner()` → `CloudRunAgentRunner.run()`, `config.yaml`, `pyproject.toml`, `build.sh`, `README.md`,
  `serverless_test.py`, `deploy/{Dockerfile,deploy.sh,main.tf,outputs.tf,providers.tf,terraform.tfvars,variables.tf}`),
  `.github/integration-test-config.yaml`.
- **Steps:**
  1. Copy `examples/gcp-serverless/openai`; set `queue_mode = true`, `create_redis_cluster = true`,
     and `agent_runner.command = ["python", "-c", "from app import runner; runner()"]`.
  2. `config.yaml` declares `execution.queues.type: pubsub`, `execution.response_store.type: redis`,
     `session.type: redis`.
  3. Add the weekly `gcp-serverless` entry; enable `pubsub.googleapis.com` in the CI project.
- **Verify:** `python .github/scripts/run_single_test.py --type gcp-serverless --path examples/gcp-serverless/openai-queue-mode --action deploy`, then `--action test`, then `--action destroy`. Check that the runner scaled to zero after the run, and that a reply still arrives after it has.

## Iteration 8: Tests

- **Goal:** the whole suite and lint are green with every test from spec → Testing in place.
- **Files:** any test file from spec → Testing not finished in iterations 1–4.
- **Steps:**
  1. Cross-check spec → Testing line by line against the test files.
  2. Run the full suite and lint.
- **Verify:** `cd ak-py && uv run pytest`; `make lint-check-all`; the live contract from iteration 3.

## Iteration 9: Sync docs and skills

Run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` before merge. Surfaces this
change invalidates (lines at `develop` @ `25cce1e4`):

- **Docs (deployment):**
  - `docs/docs/deployment/gcp-serverless.md:9-11` and `gcp-containerized.md:9-11`: the
    "queue mode is AWS-only" note; add a queue mode section and the new variables to Key Variables
    (`gcp-serverless.md:225`, `gcp-containerized.md:188`).
  - `docs/docs/deployment/overview.md:58-68` (queue columns), `:85` (GCP row: queue mode over
    `pubsub`), `:225-249` (GCP sections).
- **Docs (queue mode):** `docs/docs/advanced/queue-mode-guide.md`: intro `:14-17`, transport matrix
  `:48-53`, a "Running Queue Mode on Pub/Sub" section after `:306`, summary table `:802-809`.
- **Docs (transport lists):** `docs/docs/core-concepts/configuration.md:86,940` (+ the `pubsub`
  block), `architecture/overview.md:172,337-341`, `architecture/execution-flow.md:227-232,259-260`,
  `api/a2a-server.md:55,57`, `api/mcp-server.md:47,49`, `installation.md:122-132` (the `pubsub`
  extra), `intro.md:27`, `agent-skills.md:131`.
- **Docs site:** `docs/src/pages/features.tsx:867,887`; `docs/src/components/IntegrationsMarquee/data.tsx`
  (a Pub/Sub `Queue` tile after `:140`); `docs/src/components/FeatureExplorer/data.tsx:257-259`.
- **READMEs:** `README.md:41,194`; `ak-py/README.md:305-328` (GCP section), `:768` (transport
  options), a `pubsub` field block after `:940`.
- **Bundled skills:** `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:10-12`, `:74-77`
  (`queue_mode` is no longer AWS-only), `:81`, and a queue-mode subsection in the GCP sections
  `:1215-1339`; `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:559-560,600-601,1309`.
- **Dev skills:**
  - `.agents/skills/ak-dev-architecture/SKILL.md`: `:33` (bookkeeping now also follows the response
    store), `:36` and `:902-917` (five transports), `:1059-1060` (`pubsub.py`), and a
    `deployment/gcp/` entry in the tree at `:1063-1082`.
  - `.agents/skills/ak-dev-new-queue-transport/SKILL.md:4-5,18-27` (add `pubsub.py` as a reference:
    ordering keys with client-side held batches, leases and bookkeeping), `:129-134`.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md:148-154` (new test rows), `:491` (the live
    job also starts the Pub/Sub emulator).
- **No update needed (verified):** `examples/gcp-*/openai*` (they call `RESTAPI.run()` and never
  reach `CloudRun`), the Helm chart (`transport.pubsub` is #922), and scheduling docs (#921).
