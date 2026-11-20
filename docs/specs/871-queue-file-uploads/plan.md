# #871: File uploads on real queues: implementation plan

The order to build [spec.md](spec.md) in. Each iteration leaves the branch working and tested. The *how* lives in the spec. This file only orders it.

## Iteration 1: DynamoDB store knows its size limit

- **Goal:** saving a file over 400 KB to DynamoDB raises a clear `ValueError`, not an AWS error.
- **Files:** `ak-py/src/agentkernel/core/multimodal/storage/dynamodb.py`, new `ak-py/tests/test_multimodal_dynamodb_store.py`.
- **Steps:**
  1. Add `MAX_ITEM_BYTES` and the size check in `_put` (spec: `DynamoDBAttachmentStore` change).
  2. Add the two tests (under and over the cap) with a fake driver.
- **Verify:** `cd ak-py && uv run pytest tests/test_multimodal_dynamodb_store.py tests/test_attachment_offload.py -q`

## Iteration 2: Edge checks and startup warning

- **Goal:** on a broker transport, files that can't cross the queue get a 400, and nothing is queued. Startup warns about an unshared store.
- **Files:** `ak-py/src/agentkernel/pipeline/request_handler.py`, `ak-py/src/agentkernel/integration/thread/thread_chat.py`.
- **Steps:**
  1. Add `_reject_unqueueable_attachments` and call it in `RequestHandler.run_chat` (spec: `_reject_unqueueable_attachments`, "Where they are called").
  2. Call it in `ThreadRequestHandler.run_chat` before `_record_user_message` (spec: `ThreadRequestHandler` change).
  3. Add `_warn_if_store_is_unshared` to `RequestHandler.__init__`.
- **Verify:** the rejection tests and the startup-warning test from spec Testing pass, and the existing `tests/test_pipeline_request_handler.py` and `tests/test_thread_pipeline_recording.py` stay green.

## Iteration 3: Save files at the edge, open the upload route

- **Goal:** uploads up to `api.max_file_size` work on broker transports (on a `dynamodb` store, up to its 400 KB item limit, about 300 KB of file), and the queue message carries only IDs.
- **Files:** `ak-py/src/agentkernel/pipeline/request_handler.py`.
- **Steps:**
  1. Add `_offload_attachments` and call it after the check in `run_chat` (spec: `_offload_attachments`).
  2. Remove the `in_memory` guard on the multipart route in `get_router`.
- **Verify:** the size-capped-transport round trips (JSON, multipart, SSE), the link, and the schedule tests from spec Testing pass. `test_multipart_route_absent_on_broker_transports` is replaced by `test_multipart_route_served_on_broker_transports`.

## Iteration 4: Terraform

- **Goal:** cloud deployments in queue mode expose the upload route.
- **Files:** `ak-deployment/ak-gcp/containerized/state.tf`, `ak-deployment/ak-gcp/serverless/state.tf`, and `ak-deployment/ak-aws/containerized/state.tf` **only once #870 (PR #962) is merged**. Until then, AWS stays as it is and the PR description says so.
- **Steps:** apply the conditions in spec: Terraform changes, and update the comments beside them.
- **Verify:** `terraform validate` in each changed module. Version pins are left to CI.

## Iteration 5: Tests

From spec Testing, gathered in one place so nothing is missed:

- New: `TestBrokerUploads` in `ak-py/tests/test_pipeline_request_handler.py`, one thread test in `ak-py/tests/test_thread_pipeline_recording.py`, and `ak-py/tests/test_multimodal_dynamodb_store.py`.
- Replaced: `test_multipart_route_absent_on_broker_transports` → `test_multipart_route_served_on_broker_transports`.
- Patch targets: `QueueTransportFactory.resolve_type`, `AttachmentStorageManager.store_is_shared`, `MultimodalPreHook._described`, `agentkernel.core.multimodal.storage.dynamodb.DynamoDBDriver`.
- **Verify:** `cd ak-py && uv run pytest -q`, then `make lint-check-all` from the repo root.

## Iteration 6: Sync docs and skills

Each surface below states something this change makes false:

- `docs/docs/api/rest-api.md:432`: "`/api/v1/chat-multipart` is not registered, because of broker message-size limits." Replace it with: served on every transport, and broker transports need `multimodal` with a shared store: `redis`, `dynamodb`, or a custom store whose `shared` is `True`.
- `.agents/skills/ak-dev-architecture/SKILL.md:1239`: "multipart route only on `in_memory`". Replace it with the edge offload and the new checks.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md:176`: "multipart-on-`in_memory` only". Replace it with the broker upload tests.
- `ak-deployment/ak-aws/containerized/README.md`, `ak-deployment/ak-gcp/containerized/README.md`, `ak-deployment/ak-gcp/serverless/README.md`, `ak-deployment/ak-azure/containerized/README.md`: uploads in queue mode need `multimodal` with a shared store (Redis, DynamoDB, or a custom `shared` store), and the edge and runner must share those settings. The AWS README also says ECS queue mode gets no uploads until #870 lands: its REST container still serves the older ECS handler, so the gateway route and the edge save both wait for it. Give the gateway body limit: AWS 10 MB, GCP 32 MB, Azure "check your APIM tier" (spec: External facts).
- Check, and change only if they mention the in-memory-only upload route: `docs/docs/architecture/execution-flow.md`, `docs/docs/advanced/threads.md`, `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`.
- Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows before merge to catch anything missed above.
