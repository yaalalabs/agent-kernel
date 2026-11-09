# Pub/Sub and Cloud Run facts behind the #886 design

Facts from Google Cloud's own documentation, gathered 2026-11-08. Each item is marked:

- **Verified**: the statement was read on the cited page.
- **Inferred**: reasoned from verified text; the spec must confirm it before relying on it.
- **Unverified**: not found in the docs.

`cloud.google.com/...` doc URLs now redirect to `docs.cloud.google.com/...`, so the links below
use the new host.

## Takeaways for the design

| Finding | Design consequence |
|---|---|
| `delivery_attempt` is approximate, can reset, and exists only with a dead-letter policy | `receive_count` comes from the bookkeeping store, as on Kafka. The server dead-letter policy is only the backstop. |
| No publish-side dedup; publisher retries get new message IDs | Dedup is a consume-side claim on `dedup_id`, as on Kafka |
| A pull can return several messages with the same ordering key, but only one batch per key is outstanding | The transport serves one message per key at a time and holds the rest of the batch |
| Redelivering a message redelivers every later message for that key, even acknowledged ones | Acknowledged messages are remembered, so a cascade redelivery does not run them again |
| Attribute values are capped at 1024 bytes, and a message at 100 attributes | The envelope cannot rely on Pub/Sub attributes for `reply_` context, which can be up to 8192 bytes |
| Ack deadline is 10–600 s; client libraries extend leases | The transport extends the deadlines of messages it holds |
| Worker pools are GA, have no HTTP endpoint, and scale manually or through CREMA | The agent runner is a worker pool running `AgentRunner.run()` unchanged |
| Push: request timeout = ack deadline (≤ 600 s), no exactly-once, backoff can't be disabled | Pull everywhere, one consumer model (`ConsumerLoop`) |
| Cloud Scheduler: no one-time jobs; a Pub/Sub target is static `data` + `attributes` | A Cloud Scheduler provider cannot meet the trigger contract on its own (see design Open questions) |

## Pub/Sub

1. **Ordering keys.**
   - A pull response can hold several messages with the same key, in order. "Only one batch of messages can be outstanding for an ordering key at a time."
   - Push allows one outstanding message per key.
   - "Redeliveries of a message trigger redelivery of all subsequent messages for that key, even acknowledged ones." This covers ack-deadline expiry. Nack also causes redelivery, so the same cascade is inferred to apply.
   - Order may not be preserved for messages sent to a dead-letter topic.
   - https://docs.cloud.google.com/pubsub/docs/ordering. Verified.
2. **`delivery_attempt`.**
   - "calculated at best effort and is approximate": 1 + nacks + ack-deadline expiries, and it "may also reset to zero".
   - Populated only when a dead-letter policy is set; otherwise Python's `Message.delivery_attempt` is `None`.
   - `max_delivery_attempts` is 5–100 (default 5), "honored on a best effort basis".
   - https://docs.cloud.google.com/pubsub/docs/handling-failures, https://docs.cloud.google.com/pubsub/docs/reference/rest/v1/projects.subscriptions/pull. Verified.
3. **Deduplication.**
   - There is no publish-side dedup or idempotency key: "A subscription might receive multiple copies of the same message due to publish side duplicates", and publisher retries arrive with new message IDs.
   - Exactly-once delivery prevents redelivery before the ack deadline and after a successful ack. It does not remove publish-side duplicates.
   - It is regional and pull only, works with ordering, and has significantly higher latency.
   - https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery. Verified.
4. **Ack deadline and redelivery.**
   - The subscription ack deadline is 10–600 s (default 10 s).
   - `modifyAckDeadline` takes 0–600 s per call; 0 "might immediately make the message available for delivery".
   - The retry policy is either immediate, or exponential backoff with a minimum and maximum each between 0 and 600 s.
   - Client libraries extend leases by default for up to 1 hour.
   - https://docs.cloud.google.com/pubsub/docs/subscription-properties, https://docs.cloud.google.com/pubsub/docs/lease-management. Verified.
5. **Unary pull.**
   - Supported through the low-level generated client: `subscriber.pull(request={"subscription": ..., "max_messages": N})`. It is recommended where "low latency and high throughput are not the most important factors".
   - A call returns up to 1000 messages and may return fewer, or none. Zero messages "must not be used as an indicator" that the backlog is empty.
   - It may wait "for a bounded amount of time". The bound is undocumented (unverified).
   - https://docs.cloud.google.com/pubsub/docs/pull. Verified.
6. **Push to Cloud Run.**
   - 102, 200, 201, 202 and 204 count as an ack.
   - `ackDeadlineSeconds` (max 600) is also the push request timeout.
   - Push backoff runs from 100 ms to 60 s and cannot be disabled.
   - Authentication is an OIDC token checked by Cloud Run.
   - Ordering gives one outstanding message per key; exactly-once is not supported.
   - https://docs.cloud.google.com/pubsub/docs/push. Verified.
7. **Emulator.**
   - Supports ordering keys (except seek-to-timestamp on ordered subscriptions), dead-letter topics, retry policies, push and pull.
   - Has no IAM and keeps messages indefinitely.
   - Exactly-once is not mentioned (unverified; assume unsupported).
   - https://docs.cloud.google.com/pubsub/docs/emulator. Verified.
8. **Limits.**
   - Message data up to 10 MB.
   - Up to 100 attributes per message, keys up to 256 bytes, values up to 1024 bytes.
   - Ordered publish is limited to 1 MBps per ordering key.
   - https://docs.cloud.google.com/pubsub/quotas. Verified.
9. **Message ID across redeliveries.**
   - A redelivery is assumed to carry the same `message_id` as the original delivery, since the ID is assigned at publish.
   - Inferred: the spec must confirm this on the emulator, because bookkeeping is keyed by it.

## Cloud Run

10. **CPU allocation.**
    - Request-based billing (the default) allocates CPU only while a request is being processed.
    - Instance-based billing "allocates CPU even outside of request processing" and needs at least 512 MiB of memory.
    - In Terraform this is `cpu_idle = false` on `google_cloud_run_v2_service`. When `resources` is set, `cpu_idle` must be explicit.
    - Idle instances can still be shut down unless min instances keep them.
    - https://docs.cloud.google.com/run/docs/configuring/billing-settings, https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service. Verified.
11. **Worker pools.**
    - A Cloud Run resource for continuous, non-HTTP background work, with no endpoint. Preview from 2025-06-25, GA on 2026-04-14.
    - Scaling is manual (`manual_instance_count`).
    - Backlog autoscaling comes from **CREMA**:
      - an open-source, KEDA-based autoscaler that runs as its own Cloud Run service with CPU always allocated;
      - its `gcp-pubsub` scaler in `SubscriptionSize` mode scales a pool from 0;
      - many Cloud Monitoring metrics arrive 2+ minutes late.
      - No launch stage is stated for CREMA.
    - Terraform resource: `google_cloud_run_v2_worker_pool`, in the GA `google` provider since 6.37.0.
    - What `scaling_mode = AUTOMATIC` does for a worker pool is undocumented (inferred: do not rely on it).
    - https://docs.cloud.google.com/run/docs/deploy-worker-pools, https://docs.cloud.google.com/run/docs/configuring/workerpools/crema-autoscaling, https://docs.cloud.google.com/run/docs/tutorials/autoscale-workerpools-pubsub, https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_worker_pool. Verified, except the inferred point.
12. **Services do not scale on backlog.**
    - Services scale on requests, CPU and concurrency.
    - A service doing background work "cannot scale from zero" without requests.
    - https://docs.cloud.google.com/run/docs/about-instance-autoscaling. Verified.
13. **Memorystore reachability.**
    - Memorystore for Redis is reachable from Cloud Run over a Serverless VPC Access connector or over Direct VPC egress (recommended; needs a /26 or larger subnet).
    - Which of the two worker pools support is unverified: the spec must confirm it.
    - https://docs.cloud.google.com/memorystore/docs/redis/connect-redis-instance-cloud-run. Verified.

## Cloud Scheduler and Secret Manager

14. **Cloud Scheduler.**
    - A job can target a Pub/Sub topic directly. `PubsubTarget` has `topicName`, `data` and `attributes`: no ordering key, and no per-run substitution is documented.
    - There are no one-time jobs: "If you need to run a job only once, consider using Cloud Tasks", which schedules up to 30 days ahead.
    - Schedules use five-field unix-cron with a tz-database `timeZone`. Delivery is at-least-once.
    - https://docs.cloud.google.com/scheduler/docs/reference/rest/v1/projects.locations.jobs, https://docs.cloud.google.com/scheduler/docs/overview. Verified. The absence of an ordering key and of substitution is inferred from the target's field list.
15. **Secret Manager.**
    - `access_secret_version(request={"name": "projects/P/secrets/S/versions/latest"})`.
    - https://docs.cloud.google.com/secret-manager/docs/access-secret-version. Verified. Relevant only to the G9 follow-up.
