# #710: AG-UI on the queue pipeline — Implementation Plan

Nine iterations. Each leaves the branch working and testable. Refactors that only remove duplication
are deliberately held to iteration 8, after the behaviour is proven — the duplication they remove is
written knowingly in iterations 2 and 3.

Two decisions taken up front, so no iteration stalls on them:

- **Envelope budget: 64 KB** — clear of the 8 KB reply-context budget, well under SQS's 256 KB body
  ceiling, and roomy enough for a `forwardedProps` carrying a selected record.
- **The live-broker contract run gates the change** — a fake redis client cannot prove `blpop`
  blocks, and blocking is the whole mechanism. See iteration 7.

---

## Iteration 1: The marker and the sharedness predicate

- **Goal:** the pipeline can distinguish AG-UI traffic and every response store declares whether a
  second process can read it. Nothing consumes either yet.
- **Files:** `pipeline/envelope.py`, `pipeline/agent_runner.py`, `pipeline/response_store/base.py`,
  `pipeline/response_store/in_memory.py`
- **Steps:**
  1. Add `ATTR_AGUI` beside the existing constants (spec §1).
  2. Add it to `_FORWARDED_ATTRIBUTES`. `_is_forwarded` needs no change.
  3. Add the `shared` property to `ResponseStore`, default `True` (spec §2).
  4. Override it to `False` on `InMemoryResponseStore`.
- **Verify:** `uv run pytest` — the whole suite must still pass. Nothing branches on either addition
  yet, so a failure here means an unintended interaction.

## Iteration 2: Chunk streaming on redis and valkey

- **Goal:** a shared store can carry a chunk stream, with semantics identical to the in-memory one.
- **Files:** `core/util/driver/redis_like.py`, `pipeline/response_store/redis.py`,
  `pipeline/response_store/valkey.py`, `pipeline/response_store/base.py`,
  `pipeline/response_store/testing.py` (new)
- **Steps:**
  1. Add `blpop` to the shared driver, with the zero-timeout clamp (spec §3).
  2. Lift the `chunk_timeout` fallback onto the ABC as `_chunk_timeout`, so all three stores share it.
  3. Implement the four methods on `redis.py`, then **copy them to `valkey.py`**. The duplication is
     intentional and temporary — iteration 8 removes it, once the semantics are pinned by tests.
  4. Write `ResponseStoreContract` (spec, Testing/New files), including the docstring stating that
     `add_chunk` is not required to be idempotent.
  5. Subclass it in `tests/test_response_store_in_memory.py` and `tests/test_response_store_valkey.py`;
     add `tests/test_response_store_redis.py`.
- **Verify:** `uv run pytest -k response_store`. The in-memory subclass passing unchanged is the
  signal that the redis-like semantics match rather than merely working.

## Iteration 3: Pipeline dispatch

> **Runs after iteration 4.** `_process_agui` validates an `AGUIRunRequest` and applies an
> `AGUIRunEnvelope`, both of which iteration 4 creates; iteration 4 has no reverse dependency.
> Corrected during implementation rather than renumbering, so the iteration names stay stable.

- **Goal:** a marked message streams and its chunks reach the store, whatever `execution.mode` says.
- **Files:** `pipeline/agent_runner.py`, `pipeline/response_handler.py`
- **Steps:**
  1. Add `AgentRunner._process_agui` and the branch at the top of `process` (spec §4). Write the
     chunk loop plainly, even though `StreamAgentRunner.process` has a similar one — iteration 8
     decides whether they share.
  2. Guard `handler.service.session` before dereferencing it; a `None` becomes a `RunError`, not an
     `AttributeError`.
  3. Add the `ATTR_AGUI` branch to `ResponseHandler.process` and `on_permanent_failure` (spec §5),
     reusing `_store_chunk`.
- **Verify:** `uv run pytest -k "agent_runner or response_handler"`, driving `QueueMessage`s directly.
  Runs on `in_memory` — no broker needed.

## Iteration 4: The inbound envelope and the handler split

- **Goal:** the client's three values can cross a process boundary, and both handlers share one
  definition of which cache each lives in. The direct handler still behaves exactly as before.
- **Files:** `integration/agui/run_input.py`, `integration/agui/handler.py`, `core/chat_service.py`
- **Steps:**
  1. Add `AGUIRunEnvelope` with `build` / `apply`, and `AGUIRunRequest` (spec §6).
  2. Split `set_agui_session_keys`: validation and the 400s into `build`, the three `AGUIState`
     writes into `apply`. Point the direct handler at `apply(session, build(run_input))`.
  3. Extract `_resolve_run_inputs` from `AGUIRequestHandler._run` — everything up to agent resolution, parse and
     `to_requests`. What follows stays in the direct handler.
  4. Add `"agui"` to `RequestBuilder.known_fields`.
  5. Enforce the 64 KB budget in `build`, raising HTTP 400 naming the field and the budget.
- **Verify:** `uv run pytest -k agui`. The existing AG-UI tests are the regression gate — this
  iteration must not change the direct path's behaviour.

## Iteration 5: The queue-mode handler

- **Goal:** end to end. An AG-UI client works against `IOHandler.run(handlers=[...])`.
- **Files:** `integration/agui/pipeline.py` (new), `integration/agui/__init__.py`
- **Steps:**
  1. Write `AGUIPipelineRequestHandler` with `requires_pipeline = True` (spec §7).
  2. Implement `_validate_topology`'s three checks (spec §8).
  3. Implement `_events_from_store`, reusing the direct handler's bracket and mapping an
     `agui_state` chunk to `StateSnapshotEvent`.
  4. Offload attachments before enqueue.
  5. Export the class.
- **Verify:** a first pass of `tests/test_agui_pipeline.py` over the `in_memory` topology — the
  protocol bracket holds and both preconditions raise.

## Iteration 6: The STREAM route precondition

- **Goal:** the SSE route this change turns on refuses a topology it cannot serve, instead of hanging.
- **Files:** `pipeline/request_handler.py`
- **Steps:** extend `_reject_unroutable`'s STREAM branch to require `store.shared` on a broker
  transport (spec, Consumer changes).
- **Verify:** `uv run pytest -k request_handler`. Kept separate because it is the only step that
  changes behaviour for a non-AG-UI surface.

## Iteration 7: Tests

- **Goal:** every requirement has a case, and the mechanism is proven against a real broker.
- **Files:** `tests/test_agui_pipeline.py`, `tests/test_pipeline_agent_runner.py`,
  `tests/test_pipeline_response_handler.py`, `tests/test_pipeline_request_handler.py`,
  `tests/test_shared_drivers.py`, `tests/test_response_store_contract_live.py` (new)
- **Steps:**
  1. Write the four decisive cases from the spec's Testing section — capability-is-not-sharedness,
     the marker surviving the hop, the envelope reaching the tools and keeping its lifetime, and the
     state baseline ordering.
  2. Add the marker-precedes-mode case **with and without** `ATTR_USER_ID`, parametrised over all
     four execution modes.
  3. Add the accepted blind spot: a dotted-path store declaring the capability constructs fine on a
     broker.
  4. Add the live-broker contract run, env-gated in the shape of
     `tests/test_transport_contract_live.py`, and wire it into `test-reusable.yaml`'s existing
     broker job.
- **Verify:** `uv run pytest` for the suite, and the live job for the blocking semantics. **The
  change is not done until the live run has passed** — a fake client returns instantly and would
  pass a `blpop` that never blocks.

## Iteration 8: Deferred refactors

- **Goal:** remove the duplication iterations 2 and 3 wrote knowingly. Behaviour must not move.
- **Files:** `pipeline/response_store/redis_like.py` (new), `pipeline/response_store/redis.py`,
  `pipeline/response_store/valkey.py`, `pipeline/agent_runner.py`
- **Steps:**
  1. Lift the redis/valkey body into `_RedisLikeResponseStore`, mirroring `_RedisLikeThreadStore`
     (`integration/thread/store/redis_like.py:24`). The two subclasses keep their constructors and
     their driver choice.
  2. Look at `_process_agui` and `StreamAgentRunner.process` side by side and decide whether the
     chunk loop becomes a shared method. Either outcome is acceptable; if they stay separate, say
     why in a comment.
- **Verify:** `uv run pytest` with **no test changes**. A refactor that needs a test edited is not a
  refactor — the existing store tests patch the driver module rather than store internals, so they
  should survive untouched.

> **Outcome (done during the PR #755 review round, not as a standalone iteration).** Step 1 was done
> for a reason better than tidiness: `close_stream` recreated the chunk key its own reader had just
> deleted, and applying that fix to two byte-identical copies is how the copies drift. The shared
> class is `RedisLikeResponseStore`. Step 2 resolved the other way — the two chunk loops stay
> separate, because they read different inputs (`AgentHandler.run_stream_sync` versus
> `ChatService.process_stream_chat_sync`) and differ in what they hold back and what they record.
> What they genuinely shared was the *dispatch*, and that was hoisted above both instead:
> `AgentRunner.process` is now the dispatcher and `_process_run` the subclass hook.

## Iteration 9: Sync docs and skills

- **Goal:** the documented architecture matches what shipped.
- **Files and what changes:**
  - `.agents/skills/ak-dev-architecture/SKILL.md` — the AG-UI section gains the queue-mode sibling;
    the response-store row gains `shared` and the redis/valkey chunk capability; and the coupling
    rule's **"Two sites"** for `pipeline` → `integration` lazy imports becomes three
    (`AgentRunner._process_agui` joins `_outbound_adapter` and `_record_thread_reply`).
  - `docs/docs/integrations/agui.md` — mounting the queue-mode handler, and what it requires.
  - `docs/docs/advanced/queue-mode-guide.md` — response-store options now include chunk streaming.
  - `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md` — verify whether its response-store
    guidance needs the `shared` distinction; state explicitly if it does not.
- **Verify:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows
  before merge, and confirm each surface above was either changed or deliberately left.

## Iteration 10: Move the AG-UI example onto the queue

- **Goal:** the shipped example demonstrates queue mode, and the frontend does not change to prove
  it. Added after iteration 9: the capability is only real once the example a reader copies uses it.
- **Files:** `examples/api/agui/app.py`, `app_runner.py` (new), `config.broker.yaml` (new),
  `docker-compose.yaml` (new), `README.md`, `pyproject.toml`
- **Steps:**
  1. **First, the risk check.** Switch `app.py` to `IOHandler.run(handlers=[AGUIPipelineRequestHandler(...)])`
     and run the existing `app_test.py` unchanged. `IOHandler` owns its own `uvicorn.Server` and
     installs signal handlers, so the subprocess start/teardown the test relies on is the thing most
     likely to break. Everything else is downstream of this working.
  2. Confirm the demo UI router still serves: `IOHandler` goes through `RESTAPI.build_app`, which
     includes `_custom_routers` (`api/http.py:163-166`), so `RESTAPI.add(ui_router)` should survive.
  3. Add mode B — `app_runner.py` (`AgentRunner.run()`), `config.broker.yaml` (nats + valkey) and a
     compose file, so a reader can see the two-process topology the design is actually for.
  4. README: "Two ways to run it", and the four things to watch in mode B — the runner's log while
     the socket is held elsewhere, the task list surviving the hop, a killed runner redelivering,
     and a `dynamodb` response store refused at boot.
- **Verify:** `uv run pytest` in the example (mode A, no containers), then mode B by hand against
  the compose stack with the unchanged frontend.
- **Decision taken in this iteration:** "the documented default" is gone from `design.md`, the
  handler's docstring and the AG-UI docs page. The direct handler is now described as *supported for
  deployments that want no queue*, and the example is named as what a reader copies. It is not
  deprecated; the Non-goals still record why removing it was rejected.
