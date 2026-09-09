# NATS JetStream as the Queue Backend

Status: web research, 2026-08-07, verified against primary sources. Scope: replacing SQS FIFO
(input + output queues) with NATS JetStream in an on-prem Kubernetes deployment. The semantics
contract being mapped is in `current-queue-mode.md`.

## Executive summary

- JetStream's consumer model maps **almost one-to-one** onto AK's `QueueConsumer` contract:
  `ack_wait` = visibility timeout, `max_deliver` = max receive count (server-enforced),
  `msg.metadata.num_delivered` = exact receive count on every delivery, `term()` = permanent
  failure, `Nats-Msg-Id` + duplicate window = dedup ID. The retry/permanent-failure logic ports
  directly.
- The one DIY part is **per-session ordering with parallel consumers** (SQS MessageGroupId has no
  native equivalent): the standard recipe is deterministic subject mapping with a partition token
  + one filtered consumer per partition. Kafka has the same partition-bound model.
- **nats-py is asyncio-only**; the maintainer-recommended pattern for thread-based consumers is a
  dedicated event-loop thread with `asyncio.run_coroutine_threadsafe`.
- Operational footprint is dramatically below Kafka: single <20 MB Go binary, idles at 15-30 MB
  RAM, official Helm chart, NACK CRDs for declarative streams/consumers, no operator required.
- **Licensing settled**: the 2025 Synadia/CNCF dispute ended May 2025 with the NATS trademark
  assigned to the Linux Foundation; the project remains CNCF/Apache-2.0. No redistribution risk.

## Versions (verified 2026-08-07)

| Component | Version | Note |
|---|---|---|
| NATS Server | v2.14.4 (2026-07-30) | 2.14 added high-throughput JS publishing, server-side scheduling |
| nats-py | v2.15.0 (2026-06-05) | official asyncio client |
| nats-jetstream (modular client) | 0.3.0 beta | Python ≥3.11; only place priority groups exist in Python |
| NATS Helm chart (`nats/nats`) | 2.14.2 | chart version tracks server since 2.12 |
| NACK operator | v0.23.0 | Stream/Consumer/KV/ObjectStore CRDs |
| KEDA | v2.20.2 | `nats-jetstream` scaler |

## Python client

- `nats-py` 2.15.0: official CNCF client, actively maintained, **asyncio-only** (no sync API; no
  third-party sync client with JetStream support found).
- JetStream pull API (verified in source): `js.pull_subscribe(subject, durable=...)` then
  `fetch(batch, timeout=...)`: a direct equivalent of long-poll receive with batch size.
  `ConsumerConfig`: `durable_name`, `ack_wait`, `max_deliver`, `backoff` (per-retry delays),
  `filter_subject(s)`, `max_ack_pending`. `Msg`: `ack()`, `nak(delay=...)`, `in_progress()`
  (extends the ack timer, like ChangeMessageVisibility), `term()`, `msg.metadata.num_delivered`.
- `priority_groups` / `priority_policy` (`overflow`, `pinned_client`) are **not** in stable
  nats-py; only in the beta `nats-jetstream` 0.3.0 package.
- **Thread-based consumers**: one background thread runs the event loop (`loop.run_forever()`);
  worker threads call `asyncio.run_coroutine_threadsafe(coro, loop).result()`. A NATS maintainer
  (wallyqs) published a thread-safe component gist for exactly this. One connection multiplexes
  all threads, so AK's N-threads-per-container model keeps working.

## Semantics mapping (SQS FIFO → JetStream)

| SQS FIFO concept | JetStream equivalent | Built in? |
|---|---|---|
| Queue | Stream with `WorkQueuePolicy` retention | Yes |
| Long poll + batch | Durable pull consumer, `fetch(batch, timeout)` | Yes |
| Visibility timeout | `ack_wait` (+ `in_progress()` to extend) | Yes |
| ApproximateReceiveCount | `msg.metadata.num_delivered` (exact) | Yes |
| max_receive_count | `max_deliver` (server-enforced) + `backoff` schedule | **Yes** |
| Permanent-failure delete | `term()` (stops redelivery; removes from work-queue stream; emits advisory) | Yes |
| DLQ | Via `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES` advisory (~50 LoC pattern) | Partly |
| MessageDeduplicationId | `Nats-Msg-Id` header + stream `duplicate_window` (default 2 min; set 5 for SQS parity) | Yes |
| MessageGroupId ordering | **No direct equivalent**: partition-per-subject pattern | DIY |
| Message attributes | Arbitrary headers; subject also carries routing tokens | Yes |

### Streams and horizontal scaling

- Two streams, e.g. `AGENT_REQUESTS` (`chat.req.>`) / `AGENT_REPLIES` (`chat.out.>`), retention
  `WorkQueuePolicy` (message removed on terminal ack: closest to SQS delete-on-success), file
  storage. Constraints: consumers on a work-queue stream must have **non-overlapping filter
  subjects** (server-rejected otherwise); an unconsumed message stays forever → set `max_age` as
  a safety net.
- Scaling without ordering: **one durable pull consumer shared by all replicas/threads**; the
  server load-balances fetches. No partitions, no rebalancing.

### Per-session ordering (the DIY part; 2026 state)

- ADR-42 priority groups (server 2.11+) give `pinned_client` exclusive consumption with
  server-orchestrated failover, but Kafka-style multi-group partitioning is explicitly future
  work: **server-side consumer groups do not exist yet**.
- Deterministic subject mapping (server 2.10+): stream ingest transform
  `chat.req.*` → `chat.req.{{partition(N,1)}}.{{wildcard(1)}}` hashes the session token to a
  fixed partition number.
- Synadia's Orbit **pcgroups** library (elastic partitioned consumer groups) is **Go-only**: no
  Python port found.
- **Practical Python recipe**: publish to `chat.req.<session_id>`; transform adds partition
  token; create N durable consumers with non-overlapping filters (`chat.req.0.>` …
  `chat.req.N-1.>`: legal on a work-queue stream); one active processor per partition via
  `max_ack_pending=1` per partition consumer (works from stable nats-py; multiple replicas can
  pull the same partition consumer for failover: the server serializes them). Parallelism =
  partition count, same as Kafka; idle partitions cost ~nothing, so choose N generously (e.g. 32).
- Ordered consumers (`ordered_consumer=True`) are the wrong tool (ephemeral, ack-less,
  single-instance readers).

### Retry, failure, DLQ

- AK's current app-level pattern (check receive count, run permanent-failure handler, delete)
  ports directly: check `num_delivered`, run handler, `term()`.
- `nak(delay=n)` for delayed redelivery; `backoff=[...]` for a per-retry schedule.
- On `max_deliver` exhaustion the server publishes
  `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.<stream>.<consumer>`; the documented DLQ pattern
  captures the advisory into a small stream, direct-gets the original by sequence, republishes to
  a `dlq.>` stream, and deletes from the source (a max-delivered message on a work-queue stream is
  NOT auto-removed: it just stops being delivered). Since AK runs its own permanent-failure
  handler before deletion, the advisory-based DLQ may be unnecessary.
- Note: rare `NumDelivered` anomalies reported in clustered setups (nats-server #5171); server's
  `max_deliver` enforcement is authoritative regardless.

## Kubernetes deployment

- Official chart `nats/nats` 2.14.2 (`https://nats-io.github.io/k8s/helm/charts/`):
  `config.jetstream.enabled=true` + `fileStore.pvc.size`; `config.cluster.enabled=true`,
  `replicas=3` for production; config-reloader sidecar by default; `promExporter.enabled` adds a
  prometheus-nats-exporter sidecar + optional `podMonitor`.
- Dev: single-pod single-server with a small file-store PVC is the chart's default topology:
  runs on any micro-cluster with a default StorageClass (microk8s `hostpath-storage` addon).
  (microk8s not explicitly documented by NATS; standard k8s mechanics, expected to work.)
- Production: 3-node cluster, streams/consumers at `replicas: 3` (Raft). Manage declaratively via
  NACK CRDs (control-loop mode): fits GitOps for customer installs.
- Footprint: single static Go binary <20 MB; core server idles at 15-30 MB RAM; JetStream adds
  memory with load (hundreds of MB sustained). Chart README recommends 2 CPU / 8 Gi as production
  JS minimum; a modest 3 × (1 CPU / 1-2 Gi) cluster handles chat-scale workloads. Dramatically
  below Kafka's baseline.

## Autoscaling (KEDA)

- `nats-jetstream` scaler: `natsServerMonitoringEndpoint` (HTTP :8222 monitoring, headless
  service), `account`, `stream`, `consumer`, `lagThreshold`, `activationLagThreshold`. Scales on
  pending (not-yet-delivered) messages; consumer must be a pull consumer.
- Gotchas (KEDA tracker; open/closed status unverified): messages awaiting **redelivery are not
  counted** as lag (#3787); clustered NATS: only the consumer's Raft leader reports accurate
  counts (#3860); a non-existent consumer name can scale to `maxReplicaCount` (#7657) → create
  consumers via NACK before the ScaledObject.
- With partitioned ordering, partition count caps useful parallelism → `maxReplicaCount` ≤
  partitions (analysis, not documented claim).

## Operational burden vs Kafka

- One static binary, one config file; no JVM, no quorum-management tooling, no heap/page-cache
  tuning. Rolling upgrades with built-in lame-duck mode.
- Monitoring: built-in :8222 endpoint (`varz`/`jsz`), exporter sidecar via one chart flag,
  official Grafana dashboards, `nats` CLI for admin.
- Honest downsides: JetStream Raft needs occasional operator awareness (replacing a permanently
  lost peer); thinner third-party ecosystem than Kafka; per-key ordered parallel consumption is
  DIY in Python.

## NATS core pub/sub for WebSocket push routing

Core (non-JetStream) NATS is at-most-once, in-memory, interest-based pub/sub on the same server
and client library: a natural fit for routing reply chunks to whichever IO pod holds the client's
WebSocket: each pod makes a cheap ephemeral subscription per connected session
(`push.session.<session_id>`) or per pod (`push.pod.<pod_id>`); workers publish chunks; only the
interested pod receives; subscriptions die with the connection (no store cleanup). Keep durability
in the JetStream output stream; use core subjects purely as the hot delivery path.

## Could not verify / caveats

- microk8s not explicitly covered by NATS docs (expected to work).
- Current open/closed status of KEDA issues #3787, #3860, #7657.
- Third-party sync Python clients (none appear to support JetStream).
- `nats-jetstream` beta package's priority groups: experimental.

## Sources

- https://github.com/nats-io/nats.py/releases / https://pypi.org/pypi/nats-py/json
- https://gist.github.com/wallyqs/bde8b412a8f5b296ccfc746d4c93437c (event-loop-thread pattern)
- https://github.com/nats-io/nats-server/releases / https://nats.io/blog/nats-server-2.12-release/
- https://github.com/nats-io/nats-architecture-and-design/blob/main/adr/ADR-42.md
- https://nats.io/blog/orbit-partitioned-consumer-groups/ / https://www.synadia.com/blog/partitioned-consumer-groups
- https://www.synadia.com/blog/process-jetstream-messages-strict-order / https://github.com/nats-io/nats-server/issues/7106
- https://natsbyexample.com/examples/jetstream/workqueue-stream/go/ / https://docs.nats.io/nats-concepts/jetstream/streams
- https://docs.nats.io/using-nats/developer/develop_jetstream/consumers / https://www.synadia.com/blog/jetstream-reliable-delivery-dlq-replay
- https://github.com/nats-io/nats-server/discussions/5110 (term on work queues)
- https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive (dedup window)
- https://artifacthub.io/packages/helm/nats/nats / https://github.com/nats-io/k8s/blob/main/helm/charts/nats/README.md
- https://github.com/nats-io/nack
- https://keda.sh/docs/2.20/scalers/nats-jetstream/ + kedacore/keda #3787, #3860, #7657
- https://docs.nats.io/running-a-nats-service/introduction
- https://www.cncf.io/announcements/2025/05/01/cncf-and-synadia-align-on-securing-the-future-of-the-nats-io-project/ (licensing outcome)
- https://github.com/nats-io/nats-server/discussions/5171 (NumDelivered anomaly)
