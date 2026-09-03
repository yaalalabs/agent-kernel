---
name: ak-dev-new-queue-transport
description: >
  Step-by-step guide for adding a new queue transport to Agent Kernel's execution pipeline.
  Use this skill when you need to integrate a new message broker (beyond in_memory, SQS,
  Kafka, and NATS JetStream) behind the QueueTransport/TransportConsumer interface. Covers the
  queue-semantics contract every transport must reproduce, factory registration, configuration
  and extras, the QueueTransportContract test suite (fake and live-broker runs), the
  transport example, and Helm chart wiring.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Queue Transport

This guide walks through adding a new queue transport to the pipeline
(`ak-py/src/agentkernel/pipeline/`). Use the shipped implementations as references, in
increasing order of complexity:

- `transport/in_memory.py`: the semantics in their purest form, no broker
- `transport/sqs.py`: a broker with native FIFO groups, visibility timeout, and dedup
- `transport/nats.py`: a broker where per-session ordering is built client-side (partitioned
  subjects, one durable consumer per partition, `max_ack_pending=1`)
- `transport/kafka.py` + `transport/bookkeeping.py`: a broker with no per-message
  acknowledgement model, so receive counts and dedup are rebuilt on a bookkeeping store

Read `.agents/skills/ak-dev-architecture` (the pipeline section) first if you have not.

## The Semantics Contract

Every transport must reproduce the SQS FIFO semantics the pipeline was extracted from
(`docs/specs/495-onprem-kubernetes/research/current-queue-mode.md`):

1. **Per-group FIFO with one in-flight message per group**: `group_id` is the session id; a
   session's turns never run concurrently or out of order, while distinct sessions run in
   parallel.
2. **Bounded at-least-once redelivery with an exact `receive_count`**: the `ConsumerLoop`
   compares it to `max_receive_count` to fire the permanent-failure hook, so it must be exact,
   not approximate.
3. **Publish-time deduplication** on `dedup_id` within a window (SQS parity: 5 minutes).
4. **Attribute round-tripping**: `QueueMessage.attributes` (request id, user id, status code)
   must survive the trip byte-identically.
5. **Batch fetch with a bounded wait**, returning fewer than `batch_size` rather than blocking
   past the wait.
6. **Queue isolation**: INPUT and OUTPUT never see each other's messages.

Where the broker genuinely cannot provide a guarantee, the contract suite has an explicit,
documented opt-out (see `timeout_redelivery` in `pipeline/testing.py`, which Kafka sets to
False because its consumer model has no visibility timeout). Never fake a guarantee; declare
its absence and justify it in the subclass.

## Step 1: Implement the Transport

Create `ak-py/src/agentkernel/pipeline/transport/<name>.py` implementing both ABCs from
`transport/base.py`:

- `QueueTransport`: `send(queue, message)` (map `QueueMessage` onto the broker's record:
  body, attributes as headers/metadata, `group_id` as the ordering key, `dedup_id` as the
  dedup token), `create_consumer(queue)`, and optionally `check_consumer_capacity(queue, n)`
  (startup warning when consumer threads exceed what the broker can serve in parallel).
- `TransportConsumer`: `fetch(batch_size, wait_seconds)`, `ack`, `nack`, `dead_letter`,
  `close()`. **One consumer instance is created per consumer thread** (Kafka needs one client
  object per thread; the design assumes it everywhere), so instance state needs no locking,
  but anything class-level does.

Rules learned from the shipped transports:

- Threads, not asyncio: the pipeline's consumers are threads. If the client library is
  asyncio-only, bridge through one shared event-loop thread
  (`_NatsLoop` in `nats.py` is the maintainer-recommended pattern; do not spawn a loop per
  thread).
- `receive_count` must be exact. Prefer the broker's own counter (`num_delivered`,
  `ApproximateReceiveCount`); if none exists, count attempts in a `BookkeepingStore`
  (`transport/bookkeeping.py`), keyed so a crash-looping poison message cannot reset itself.
- Honor `fetch_wait_slice_seconds` semantics: `ConsumerLoop` slices waits to stay responsive
  to shutdown, so a fetch must tolerate short waits without spinning.
- `close()` must actually release broker resources (consumer-group membership, subscriptions,
  background threads). A leaked consumer keeps CI jobs alive after the tests pass.
- Connection/provisioning caches are class-level and keyed by connection target; provide a
  `reset()` classmethod for test isolation (see `InMemoryTransport.reset`,
  `NatsTransport.reset`).
- Provisioning posture: dev may auto-provision broker objects behind an `auto_provision`
  flag, but production fails fast with an `AKConfigError` naming the missing object and the
  declarative alternative (NACK CRs, Strimzi topics). Agent Kernel never silently creates
  production infrastructure.

## Step 2: Configuration

In `ak-py/src/agentkernel/core/config.py`:

- Add a `_<Name>QueueConfig` model with the broker's connection and tuning fields (mirror
  `_NatsQueueConfig`; every field needs a real description, since they become user docs).
- Add the optional field to `_QueuesConfig` and the type name to its `type` description.
- Keep `input`/`output` blocks backend-neutral: `max_receive_count`, `no_of_consumers`, and
  `batch_size` are shared knobs, never per-backend.

If the client library is heavy or compiled, add an extra in `ak-py/pyproject.toml`
(`[project.optional-dependencies]`) named after the transport.

## Step 3: Factory Registration

`QueueTransportFactory.create()` in `transport/base.py` is an explicit chain: add the branch
for your type, guarded by `require_extra("<name>", "execution.queues.type: <name>")` with the
import inside, and add the name to `_BUILTIN_TYPES`. Fail with `AKConfigError` when the config
block is missing. Anything not in `_BUILTIN_TYPES` resolves as a dotted path (BYO), so a
transport can also live out of tree; built-in status is for transports we test and document.

The factory has a second consumer (#503): the **sandbox queue broker** passes its own
`_QueuesConfig`-shaped `sandbox.broker.queue` block through the optional `queues_config`
parameter on `resolve_type`/`create`/`create_consumer`, so a new transport gets sandbox-broker
support for free. Read the block handed to you, never `AKConfig` (the no-argument path keeps
reading `execution.queues` and must stay byte-for-byte unchanged;
`tests/test_pipeline_factory_seams.py` enforces both properties).

## Step 4: Tests

Three layers, all required:

1. **Transport-specific unit tests** (`ak-py/tests/test_pipeline_<name>_transport.py`):
   envelope/header mapping, orderings, error paths, provisioning create-vs-verify, against a
   fake broker. Build the fake behind the real client's interface so the transport code is
   exercised unmodified (see the fake JetStream behind the real `_NatsLoop`, and the fake
   in-memory Kafka cluster).
2. **The contract suite, in-repo**: subclass `QueueTransportContract`
   (`pipeline/testing.py`) against the fake, implementing `make_transport()`. Tune
   `ack_wait`/`fetch_wait`/`force_redelivery` per backend; document every capability opt-out.
3. **The contract suite, live** (`ak-py/tests/test_transport_contract_live.py`): add an
   env-gated subclass pointing at a real broker (`AK_TEST_<NAME>_...` env var, skipped when
   unset) with per-test unique queues/streams/topics for isolation. The
   `transport-integration-tests` job in `.github/workflows/test-reusable.yaml` starts the
   brokers from the transport examples' compose files and runs this file on every PR: add
   your broker's compose service there.

Timing traps that only live brokers catch (both found on real servers, invisible on fakes):

- If a fetch holds a pull/poll request open per partition, the per-partition window
  (`fetch_wait / partitions`) must stay **below** the visibility timeout, or the server
  redelivers an in-flight message into the still-open request and one fetch returns it twice.
- The contract's fixed group ids (`s0`/`s1`/`s2`) must land on distinct partitions under the
  broker's real partitioner. Partitioners are deterministic: compute the mapping (crc32 for
  the client-side scheme, murmur2 for Kafka) and choose the partition count accordingly
  instead of hoping.

## Step 5: Example

Add `examples/transport/<name>/`: a two-process app (`IOHandler.run()` / `AgentRunner.run()`
behind one `app.py`), a `config.yaml` with commented tuning values, a docker compose stack
with a healthcheck (the CI job relies on `up -d --wait <service>`), a `<name>_tester.py`
harness (bring the stack up, provision what Agent Kernel deliberately does not, inspect
queues), and an `app_test.py` covering rest_sync, a multi-turn session, and the
retry-to-permanent-failure path. Register it in `.github/test-config.yaml` under the
containerized e2e tests.

## Step 6: Deployment and Docs Surfaces

- Helm chart (`ak-deployment/ak-k8s/chart/`): a `transport.<name>` values block, its
  `AK_EXECUTION__QUEUES__<NAME>__*` env injection in `configmap-env.yaml`, a KEDA trigger in
  `scaledobject.yaml` if a scaler exists, and declarative provisioning CRs if the broker has
  an operator.
- Docs: the transport matrix and a "Running Queue Mode on <name>" section in
  `docs/docs/advanced/queue-mode-guide.md`; the transports list in
  `docs/docs/deployment/onprem-kubernetes.md` if the transport is k8s-relevant.
- Skills: the pipeline section of `.agents/skills/ak-dev-architecture/SKILL.md`, and the
  user-facing queue/deploy content in `ak-py/src/agentkernel/skills/` where transports are
  enumerated.

## Definition of Done

- `cd ak-py && uv run pytest`: green, including your contract subclass against the fake.
- Live contract green against a real broker via the compose stack.
- `make lint-check-all`: green.
- Example runs end to end locally (its `app_test.py` passes against a live agent).
- Factory rejects a missing config block and a missing extra with actionable errors.
- Docs and skills surfaces above updated in the same PR.
