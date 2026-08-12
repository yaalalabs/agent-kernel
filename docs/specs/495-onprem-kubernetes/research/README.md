# Research — #495 On-Prem Kubernetes Queue Mode

Supporting investigation behind `../design.md`. Written 2026-08-07.

| File | One-line takeaway | Status |
|---|---|---|
| `current-queue-mode.md` | The queue seams (`QueueHandler`/`QueueConsumer`) already exist and are cloud-neutral; only SQS implements them. Six queue-semantics requirements extracted; config lacks a `type` discriminator; the WS push path (API Gateway + DynamoDB) is the most AWS-coupled piece; no k8s/Helm assets exist anywhere in the repo. | Verified against `develop` |
| `kafka.md` | Kafka works but needs app-built retry/dedup machinery (no visibility timeout, no receive count, no dedup window); per-session order via record key; head-of-line blocking per partition; confluent-kafka client; Strimzi operator; heaviest ops burden. Share groups (KIP-932) would fix retry semantics but have no ordering and no production Python client. | Web research, sources cited |
| `nats-jetstream.md` | JetStream maps almost 1:1 to the existing consumer contract (`ack_wait`, `max_deliver`, `num_delivered`, `term`, `Nats-Msg-Id` dedup); per-session ordering is DIY via partition subject mapping; nats-py is asyncio-only (event-loop-thread pattern); tiny footprint, official chart, Apache-2.0 confirmed. NATS core pub/sub doubles as the WS push path. | Web research, sources cited |
| `kubernetes-deployment.md` | Standardize on Gateway API (ingress-nginx is EOL) with Envoy Gateway default; MetalLB L2 on baremetal, AWS LB Controller v3 on EKS — same chart, per-flavor values; Bitnami charts dead (use valkey-helm, nats/nats, Strimzi); KEDA for queue-depth autoscaling; k3s/k3d + kind over microk8s for testing; observability + Langfuse profiles sized. | Web research, sources cited |
