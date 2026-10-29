# #780: A2A and MCP go through the queue, and only the queue — Implementation Plan

Builds [spec.md](spec.md) in eight iterations. The suite stays green after every iteration. Unit
tests ship with the code they cover; iteration 7 adds the end-to-end checks and the full run.

| # | Iteration | Spec section | Leaves working |
|---|---|---|---|
| 1 | a2a-sdk cap | §6 | the A2A server imports, so A2A tests can run |
| 2 | `RestHandler.request` | §1 | A2A/MCP's "enqueue, then wait" exists; REST unchanged |
| 3 | `protocol` tag through runners and response handler | §2 | tagged replies land in the store in every mode |
| 4 | A2A and MCP executors | §3, §4 | A2A/MCP run through the queue |
| 5 | Startup checks | §5 | non-queue entry points refuse A2A/MCP |
| 6 | k8s example + chart CI | §7 | A2A/MCP over NATS on kind |
| 7 | Tests | Testing | end to end proven on the in-memory queue |
| 8 | Sync docs and skills | Docs list | docs and skills match the code |

## Iteration 1: a2a-sdk cap

- **Goal:** `agentkernel.api.a2a.handler` imports against the locked SDK.
- **Files:** `ak-py/pyproject.toml`, `ak-py/uv.lock`
- **Steps:**
  1. Pin `a2a-sdk[http-server]>=0.3.6,<1` (§6).
  2. Run `cd ak-py && uv lock`, and confirm the lock resolves a 0.3.x version.
- **Verify:** `cd ak-py && ./build.sh && uv run python -c "import agentkernel.api.a2a.handler"`, then `uv run pytest`.

## Iteration 2: `RestHandler.request`

- **Goal:** one reusable "enqueue, then wait for the reply" without the HTTP, on REST's own loop and budget.
- **Files:**
  - `pipeline/__init__.py`
  - `pipeline/envelope.py`
  - `pipeline/request_handler.py`
  - `ak-py/tests/test_pipeline_request_handler.py`
- **Steps:**
  1. Add `ATTR_PROTOCOL` and `QueueMessage.protocol_of` (§2).
  2. Write `QueuedReply`, `ReplyTimeoutError` and `RestHandler.request` following rules 1-11 (§1).
  3. Add `QueuedReply` and `ReplyTimeoutError` to the lazy exports.
  4. Write the `request` and `QueuedReply` tests (Testing).
- **Verify:** `uv run pytest tests/test_pipeline_request_handler.py tests/test_thread_pipeline_recording.py`

## Iteration 3: the `protocol` tag through the runners and response handler

- **Goal:** a tagged message produces one stored reply, whatever `execution.mode` is.
- **Files:**
  - `pipeline/agent_runner.py`
  - `pipeline/response_handler.py`
  - new `ak-py/tests/test_pipeline_protocol_routing.py`
- **Steps:**
  1. Add `ATTR_PROTOCOL` to `_FORWARDED_ATTRIBUTES`.
  2. Add the hand-off guards in `StreamAgentRunner` and `RealtimeAgentRunner`, in both `process`
     and `on_permanent_failure`.
  3. Add the protocol branches to `ResponseHandler.process` and `on_permanent_failure`, and extract
     `_store_failure_record` (§2, rules 1-7).
  4. Write the routing tests.
- **Verify:** `uv run pytest tests/test_pipeline_protocol_routing.py tests/test_pipeline_agent_runner.py tests/test_pipeline_response_handler.py tests/test_realtime_pool.py`. The last three must pass unedited.

## Iteration 4: A2A and MCP executors

- **Goal:** neither executor imports `AgentService`; both answer through the queue.
- **Files:**
  - `api/a2a/a2a.py`
  - `api/mcp/akmcp.py`
  - new `ak-py/tests/test_api_a2a.py`
  - `ak-py/tests/test_api_mcp.py`
  - `ak-py/tests/test_cross_surface_parity.py`
- **Steps:**
  1. Add `PROTOCOL`, `_client` and `get_client()` to each class, with the lazy import.
  2. Rewrite `A2A.Executor.execute` from the outcome table (§3), and remove `_execute_agent`.
  3. Rewrite `MCP.Executor.execute` from the outcome table (§4).
  4. Swap the `AgentService` patches for fake-client injection with `ResponseBuilder`-built bodies,
     and update the image expectation (Testing, "Changed test files").
- **Verify:** `uv run pytest tests/test_api_a2a.py tests/test_api_mcp.py tests/test_cross_surface_parity.py`, then `grep -n AgentService ak-py/src/agentkernel/api/a2a/a2a.py ak-py/src/agentkernel/api/mcp/akmcp.py`, which should print nothing.

## Iteration 5: startup checks

- **Goal:** every ❌ entry point raises `AKConfigError`; IOHandler checks for a shared store and
  warns on an empty registry.
- **Files:**
  - `api/http.py`
  - `pipeline/io_handler.py`
  - `deployment/aws/containerized/ecs_io_handler.py`
  - `ak-py/tests/test_api_http.py`
  - `ak-py/tests/test_pipeline_io_handler.py`
  - `ak-py/tests/test_ecs_io_handler.py`
- **Steps:**
  1. Add `RESTAPI.agent_protocol_surfaces` and `reject_unqueued_protocols`, and call the latter in
     `run` after `_reject_pipeline_only_handlers` (§5).
  2. Add the IOHandler shared-store check and `_warn_if_no_agents` (§5, IOHandler 1-2).
  3. Make `RESTAPI.reject_unqueued_protocols()` the first statement of `ECSIOHandler.run`.
  4. Write the refusal, store-check, warning and ECS tests.
- **Verify:** `uv run pytest tests/test_api_http.py tests/test_pipeline_io_handler.py tests/test_ecs_io_handler.py`

## Iteration 6: k8s example and chart CI

- **Goal:** the kind smoke sends one A2A `message:send` and one MCP tool call through NATS, on
  every flavor.
- **Files (all under `examples/k8s/openai-queue-mode/` unless noted):**
  - new `app_agents.py` and `protocol_client.py`
  - `app_agent_runner.py`, `app_io_handler.py`
  - `deploy/package.sh`, `pyproject.toml`, `build.sh`
  - `config.nats.yaml`, `config.kafka.yaml`, `README.md`
  - `.github/workflows/chart-test.yaml` (repo root)
- **Steps:**
  1. Move the agents into `app_agents.py`, and import it from both entry points.
  2. Make `package.sh` copy it into both images.
  3. Add the extras and the direct a2a-sdk pin, the `build.sh` extras, the `a2a`/`mcp` config
     blocks, and `protocol_client.py`, plus the README section (§7).
  4. Widen the chart-test path filters, and add the "A2A and MCP requests through NATS" step (§7).
- **Verify:**
  - Locally: `./build.sh local && (cd deploy && ./package.sh local)`; `make lint-check-all`.
  - On a k3d or kind cluster: `deploy/deploy.sh local`, then
    `kubectl port-forward service/ak-agent-kernel-io 8000:80 &` and
    `uv run python protocol_client.py`. Both replies should print.
  - In CI: the `Chart Test` workflow's `kind-smoke` passes for `dev`, `baremetal` and `eks`.

## Iteration 7: Tests

- **Goal:** prove the whole path on the in-memory queue, then run the full suite.
- **Files:** new `ak-py/tests/test_protocol_pipeline_roundtrip.py`
- **Steps:**
  1. Write the pump-thread round trip from spec Testing: A2A through `BaseClient` over
     `httpx.ASGITransport`, MCP through `fastmcp.Client(MCP.get())`, and one `stream`-mode case.
     Assert it ran on the pump thread and kept the same session.
  2. Check that every row of spec Testing's two tables has its test (iterations 2-5 plus this one).
- **Verify:** `cd ak-py && uv run pytest`, then `make lint-check-all` from the repo root.

## Iteration 8: Sync docs and skills

- **Goal:** no doc or skill still says A2A/MCP use `AgentService` directly or run in the IO process.
- **Dev skills:**
  - `.agents/skills/ak-dev-architecture/SKILL.md`
    - `:159` and `:257`: AgentService's callers become the CLI only; A2A and MCP move to the queue.
    - `:214` / `:233`: the `PROTO` node's edge goes to the pipeline queue, not `AS`.
    - `:886-893` (activation rule 1): replace "CLI/A2A/MCP use `AgentService` directly" with the
      `reject_unqueued_protocols` refusal.
    - `:1328`: the execution-flow sentence.
    - Pipeline module table: add `PROTOCOL` and `protocol_of` to the `envelope.py`
      rows (`:868`, `:881`); add the protocol hand-off to `agent_runner.py` (`:873`); add
      protocol-before-mode to `response_handler.py` (`:875`); add `request` to
      `request_handler.py` (`:876`); add the new fail-fast and warning to `io_handler.py` (`:878`).
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md`
    - `:94`: the `test_api_mcp.py` row now covers queued replies and `ToolError`.
    - Add rows for `test_pipeline_protocol_routing.py`,
      `test_api_a2a.py` and `test_protocol_pipeline_roundtrip.py` next to `:148-151`.
    - Extend the `test_pipeline_io_handler.py` row (`:151`).
- **User skill:** `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`, the MCP section
  (`:504-526`) and the A2A section (`:530-550`): the queue requirement, agents loaded in the IO
  process, and the latency floor.
- **Docs site:**
  - `docs/docs/api/a2a-server.md:76` and `docs/docs/api/mcp-server.md` (the "Starting" and
    "Custom Tools" sections): queue-only, entry points, latency, and agents in the IO process.
    MCP also gets the `stateless_http` advice for multi-replica deployments.
  - `docs/docs/architecture/execution-flow.md:11`, `:22`, `:85`.
  - `docs/docs/architecture/overview.md:136`, `:192`, `:373`.
  - `docs/docs/advanced/queue-mode-guide.md`: a short "A2A and MCP" section.
  - `docs/docs/deployment/onprem-kubernetes.md`: a one-line pointer to the k8s example's new
    A2A/MCP section.
- **Example READMEs:** `examples/api/a2a/multi`, `examples/api/mcp/multi` and
  `examples/aws-containerized/mcp/multi` (slower replies; the last runs the in-memory pipeline on
  ECS direct mode).
- **Checked, needing no change:**
  - `.agents/skills/ak-dev-new-queue-transport/SKILL.md` and `ak-deployment/ak-k8s/README.md`
    don't mention A2A or MCP.
  - `QueueTransportContract` already round-trips arbitrary attributes (`pipeline/testing.py:88-92`).
- **Before merge:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  flows over the branch, and reconcile anything they find beyond this list.
- **Follow-up issues to open** (design decisions 2 and 3):
  - ECS queue-mode support for A2A and MCP;
  - faster reply pickup for every surface.
