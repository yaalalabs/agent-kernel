# Apache Kafka as the Queue Backend

Status: web research, 2026-08-07. Versions verified against upstream sources on that date unless
marked otherwise. Scope: replacing SQS FIFO (input + output queues) with Kafka, consumed by AK's
synchronous consumer threads. The semantics contract being mapped is in
`current-queue-mode.md`.

## Executive summary

- Kafka reproduces the required semantics, **but not one-for-one**. Per-session ordering maps
  cleanly (record key = `session_id`). Visibility timeout, `ApproximateReceiveCount`, and
  per-message deletion do not exist in the classic consumer model and must be rebuilt in
  application code. The simplest correct pattern: **commit-after-process + blocking in-process
  retry with backoff + dead-letter topic**, which matches SQS FIFO's per-group blocking behavior
  anyway.
- Kafka 4.2+ **share groups** (KIP-932, GA broker-side) give almost exactly SQS semantics
  (per-record ack, lock duration = visibility timeout, delivery-attempt limit), but provide **no
  ordering guarantees** and the Python `ShareConsumer` is preview-only: unusable for the
  FIFO-per-session requirement today. Watch, don't build on.
- Client: **confluent-kafka** (librdkafka binding): the only first-tier synchronous Python
  client; Apache-2.0; wheels incl. Linux/macOS ARM64.
- Deployment: **Strimzi operator** (1.1.0, KRaft-only) is the standard on k8s; the Bitnami Kafka
  chart is a dead end (catalog frozen Aug/Sep 2025).
- A single-broker dev cluster runs on a laptop micro-cluster (~1-1.5 GiB RAM total). Production
  3-broker is a real stateful system: meaningfully heavier to operate than NATS or SQS.

## Versions (verified 2026-08-07)

| Component | Version | Note |
|---|---|---|
| Apache Kafka | 4.3.1 (2026-06-25) | KRaft only (ZooKeeper removed in 4.0) |
| confluent-kafka (Python) | 2.15.0 (2026-06-30) | tracks librdkafka 2.15.0 |
| kafka-python | 3.0.10 (2026-08-04) | revived, active again |
| aiokafka | 0.14.0 (2026-04-29) | asyncio-only |
| Strimzi | 1.1.0 (2026-06-27) | k8s 1.30-1.36; Kafka 4.2.x/4.3.0 |
| KEDA | 2.20.2 | Kafka lag scaler |

## Python client choice

**Recommendation: confluent-kafka.**

- Consumer model fits AK's design directly: N threads per container, each owning one `Consumer`,
  blocking `poll(timeout)` / `consume(num_messages=batch_size, timeout=...)`: librdkafka runs its
  own background I/O threads; synchronous classmethod-based loops are the intended usage.
- Fastest KIP uptake among Python options (ships preview KIP-932 `ShareConsumer`, KIP-848
  next-gen rebalance via `group.protocol=consumer`).
- kafka-python is **no longer abandoned** (revived, 3.0.x, Production/Stable): a viable
  pure-Python fallback but lags librdkafka. aiokafka is asyncio-only, contradicting the
  thread-based consumer architecture.

## Semantics mapping (SQS FIFO → Kafka)

| SQS FIFO concept | Kafka equivalent | Fidelity |
|---|---|---|
| Queue | Topic (`agent-input`, `agent-output`) | Direct |
| MessageGroupId = session_id | Record **key** = session_id (hash → partition) | Good, with caveats |
| Message attributes | Record **headers** (KIP-82); key doubles as session_id | Direct |
| MessageDeduplicationId | **None**; app-level dedup needed | Gap |
| Visibility timeout | **None** in classic groups; commit-after-process redelivers on crash | Gap |
| ApproximateReceiveCount / max_receive_count | **None**; app-tracked counter | Gap |
| DLQ + permanent-failure hook | Dead-letter **topic** + app hook (convention) | Pattern |
| Per-message delay | **None** (pause/resume or retry topics) | Gap |
| Delete message | No per-message delete; retention expiry (`retention.ms`) | Different model |
| Long polling | blocking `poll(timeout)` | Direct |

### Ordering per session

- `key=session_id` → one partition per session (murmur2); within a partition, one consumer in the
  group, offset order. Reproduces "session in order, sessions in parallel".
- Keep `enable.idempotence=true` (default since 3.0) to preserve per-partition order under
  producer retries.
- **Parallelism is capped by partition count** (one partition ↔ at most one group member; each
  consumer thread is a member). With R replicas × N threads, need `partitions >= R*N`. Partitions
  can be added but never removed, and **adding partitions changes key→partition mapping** (briefly
  breaks in-flight session ordering): size generously up front (e.g. 24-48 for the input topic).
- Rebalancing on scale-in/out: use `partition.assignment.strategy=cooperative-sticky` or KIP-848
  (`group.protocol=consumer`) for incremental rebalances; either way an uncommitted batch can be
  redelivered (at-least-once).

### Retry / redelivery (the big gap)

Recommended pattern: blocking in-process retry + DLQ topic:

1. `enable.auto.commit=false`; process, then commit: crash-safety comes free (uncommitted work is
   redelivered on rebalance).
2. On processing failure: retry in place with backoff up to `max_receive_count`, then run the
   permanent-failure hook, produce the record (+error metadata headers) to a `*.dlq` topic,
   commit, move on.
3. Cautions:
   - Backoff inside the poll loop must not exceed `max.poll.interval.ms` (default 5 min) or the
     consumer is evicted; `pause()` the partition and keep polling while backing off, then
     `resume()` (what Spring Kafka does).
   - **Head-of-line blocking**: a retrying message blocks the whole partition (all sessions hashed
     there), not just its own session: worse than SQS FIFO, which blocks one message group.
     Mitigate with many partitions and a small retry budget. Unavoidable if per-session order is
     to be kept.
   - **Receive-count durability**: an in-memory attempt counter resets if the pod crashes
     mid-retry, so a poison message that *crashes* the process (rather than raising) loops
     forever. Persist the count keyed by `(topic, partition, offset)` in Redis/Valkey (already in
     the stack) to reproduce SQS's crash-surviving `ApproximateReceiveCount`.
4. Non-blocking tiered retry topics (Spring `@RetryableTopic` style) remove head-of-line blocking
   **but sacrifice per-key ordering**: unsuitable for the session-ordered input topic.
5. Prior art for max-retries + DLQ: Spring Kafka `DefaultErrorHandler` +
   `DeadLetterPublishingRecoverer` (`<topic>.DLT`); Kafka Connect KIP-298
   (`errors.retry.timeout`, `errors.deadletterqueue.topic.name`, context headers). The DLQ is
   always "just another topic" plus convention; nothing broker-managed.
6. **Share groups (KIP-932)**: GA broker-side in 4.2 (`share.version` flag). Near-SQS semantics
   (acquire lock `share.record.lock.duration.ms` default 30 s; ACCEPT/RELEASE/REJECT acks;
   delivery count; `group.share.delivery.attempt.limit` default 5, then archived, **no built-in
   DLQ**). But: **no ordering guarantees** (key-based ordering explicitly a possible future KIP)
   and Python `ShareConsumer` is Preview, not for production. Not usable for this design today.

### Deduplication

- No broker equivalent of SQS's 5-minute content dedup. The idempotent producer only dedups
  broker-side retries of the same produce request within one producer session: not an app calling
  `produce()` twice with the same request_id.
- Transactions (EOS) cover Kafka-in→Kafka-out only, not external side effects (LLM calls, WS
  pushes): not a substitute.
- **Practical pattern**: consumer-side dedup keyed by `request_id` (and chunk suffix), via Redis
  `SET key NX EX 300`: reproduces the SQS window; robust across rebalances/restarts.

### Attributes and delay

- Headers carry `request_id`, `user_id`, `endpoint_url` (byte-valued, not broker-filterable:
  same as SQS attributes in practice). Default max record size ~1 MB: ample.
- No native per-message delay; in-process backoff with `pause()`/`resume()` suffices for retry
  backoff needs.

## Kubernetes deployment

- **Strimzi 1.1.0**: `Kafka` + `KafkaNodePool` CRs; KRaft-only; dual-role (controller+broker)
  single node for dev. Minimal dev footprint: broker ~512 Mi request / 1-2 Gi limit + operator pod
  (few hundred MiB) → **~1-1.5 GiB RAM, well under 1 CPU** for a working dev cluster. Installs on
  microk8s with stock manifests or Helm chart; needs a storage class (`hostpath-storage` addon) or
  `type: ephemeral` for throwaway clusters.
- **Production**: 3 brokers + 3 controllers (or 3 dual-role nodes for small installs), RF=3,
  `min.insync.replicas=2`. Modest profile for this workload: 4-8 GiB RAM, 1-2 CPU per broker with
  fast local disks (published sizing guidance targets far heavier workloads; treat 6 GB heap /
  32 GB hosts as growth ceiling, not entry price: needs a load test to pin down).
- **Bitnami Kafka chart: avoid**: catalog frozen since 2025-09-29; charts at
  `docker.io/bitnamicharts` no longer receive updates.

## Autoscaling (KEDA)

- Kafka scaler scales on consumer-group lag: `lagThreshold` (default 10) per replica,
  `activationLagThreshold` for scale-from-zero.
- **Partition count caps scaling**: KEDA won't exceed partition count by default
  (`allowIdleConsumers: true` overrides). With N threads/pod, effective parallelism saturates at
  `partitions / N` pods: set `maxReplicaCount` accordingly or size partitions `>= maxReplicas*N`.
- Gotchas: fresh consumer groups with `offsetResetPolicy: latest` report invalid lag until one
  poll+commit happens; `excludePersistentLag` off by default (a stuck partition inflates the
  signal); known near-max-replica stall issue (kedacore/keda #4791, fix status unverified).
- Keyed messages skew lag: one hot session = one hot partition; scale-out can't help a single hot
  partition.

## Operational burden (on-prem customer)

- Two coupled upgrade treadmills: Strimzi releases frequently, supports a narrow Kafka window
  (1.1.0 already dropped Kafka 4.1.x), and tracks a k8s version window (1.30-1.36). Rolls are
  automated and zero-downtime with RF=3, but someone owns the cadence.
- Stateful: PVCs (expandable, never shrinkable), retention bounds disk (24-72 h for these topics
  is plenty); disk-full is the classic self-inflicted Kafka outage.
- Monitoring: Prometheus JMX Exporter via `metricsConfig` + Strimzi-deployed Kafka Exporter
  (consumer lag); example dashboards shipped. Newer JMX-free Strimzi Metrics Reporter is early
  access.
- TLS/users automated by Strimzi's User Operator + CA rotation.
- Honest comparison: a well-automated but real distributed system (operator + 3-6 stateful pods +
  exporters). Standard and defensible for on-prem, but budget for runbooks and support.

## Unverified / open items

- kafka-python 3.x share-group support (irrelevant if confluent-kafka chosen).
- Exact Strimzi cluster-operator default resource requests.
- Exact Kafka 4.2.0 release date (share-group GA-in-4.2 itself confirmed).
- Minimum viable production sizing for this specific workload (needs load test).
- KEDA #4791 fix status in 2.20.x.

## Sources

- https://pypi.org/project/confluent-kafka/ / https://github.com/confluentinc/confluent-kafka-python/blob/master/CHANGELOG.md
- https://pypi.org/project/kafka-python/ / https://pypi.org/project/aiokafka/ / https://github.com/aio-libs/aiokafka/issues/1089
- https://kafka.apache.org/blog/2026/05/22/apache-kafka-4.3.0-release-announcement/ / https://kafka.apache.org/blog/2026/06/25/apache-kafka-4.3.1-release-announcement/
- https://cwiki.apache.org/confluence/display/KAFKA/KIP-932%3A+Queues+for+Kafka
- https://www.confluent.io/blog/kafka-queue-semantics-share-consumer-ga/
- https://www.morling.dev/blog/kip-932-queues-for-kafka/ / https://blog.2minutestreaming.com/p/apache-kafka-share-group-queues-kip-932
- https://docs.spring.io/spring-kafka/reference/retrytopic/how-the-pattern-works.html
- https://www.confluent.io/blog/kafka-connect-deep-dive-error-handling-dead-letter-queues/
- https://github.com/strimzi/strimzi-kafka-operator/releases / https://strimzi.io/downloads/ / https://strimzi.io/kraft/
- https://knative.dev/blog/articles/single-node-kafka-development/
- https://docs.confluent.io/platform/current/kafka/deployment.html
- https://github.com/bitnami/containers/issues/83267 / https://github.com/bitnami/charts/issues/35164
- https://keda.sh/docs/2.20/scalers/apache-kafka/ / https://github.com/kedacore/keda/issues/4791
- https://strimzi.io/blog/2019/10/14/improving-prometheus-metrics/ / https://strimzi.io/blog/2025/10/06/strimzi-metrics-reporter/
