---
slug: /kubernetes-on-prem-helm-chart
title: "Your Cluster, Your Data, One Helm Chart: Agent Kernel on On-Prem Kubernetes"
authors: [yaala]
tags: [agent-kernel, kubernetes, helm, on-prem, self-hosted, nats, kafka, keda, queue-mode, multi-cloud, cloud-agnostic, enterprise-ai]
image: /img/blog/kubernetes-onprem-banner.png
description: Agent Kernel now ships an official Helm chart that runs its queue-execution pipeline on any Kubernetes cluster, from a laptop k3d cluster to bare metal and EKS, with NATS, Kafka, or SQS as the broker, KEDA autoscaling, WebSocket delivery, a sandbox worker tier, and air-gapped installs. Same agents, zero code changes.
---

# Your Cluster, Your Data, One Helm Chart: Agent Kernel on On-Prem Kubernetes

![Your cluster. Your data. One Helm chart. Agent Kernel on Kubernetes: a glowing honeycomb of pods with a ship's wheel at its centre sits inside a locked perimeter ring while AI agents drift in from outside. Callouts: air-gapped deployments, sandboxed code execution, scales with demand, bare metal, EKS, or laptop](/img/blog/kubernetes-onprem-banner.png)

**Some workloads are never leaving the building.**

Patient records. Trade surveillance feeds. Customer data that a regulator, a sovereign-cloud mandate, or a signed contract says must stay on hardware you control. The teams responsible for that data are also, very often, the teams that already run Kubernetes: a platform group with a cluster, a GitOps pipeline, an on-call rota, and a firm opinion about anything that tries to route around them.

Until now, Agent Kernel met those teams halfway. The Terraform modules for AWS, Azure, and GCP take an agent from laptop to production in one apply, but on-prem meant a Docker image and a set of environment variables, with the topology left as an exercise. That gap is closed. **Agent Kernel now ships an official Helm chart** that deploys the full queue-execution pipeline to any Kubernetes cluster running 1.29 or later: bare metal in your data center, a managed EKS cluster, or a k3d cluster on your laptop. The chart is published as an OCI artifact with every release, versioned like the Python package, and your agent code does not change by a single line. Air-gapped clusters are supported out of the box, and the same chart ships a sandbox broker tier, so the code your agents write runs in sandboxed pods inside your cluster too.

<!-- truncate -->

## Why This Matters

- **Data residency stops being a blocker.** The agents, the broker, the session store, and the sandbox all run inside your cluster. Nothing in the pipeline needs a managed cloud service.
- **Your platform team stays in charge.** The chart plugs into what they already run: Gateway API for ingress, cert-manager for certificates, KEDA for autoscaling, Prometheus for metrics. It deliberately installs none of those prerequisites itself, so nothing lands on the cluster behind their backs.
- **It is the same pipeline you would run on AWS.** Per-session ordering, bounded retries, deduplication, graceful failure replies: identical semantics, because the transport is configuration, not code.
- **A quiet Tuesday and a busy Saturday need different fleets.** The agent tier scales on queue depth, the signal that actually tracks LLM-bound work, instead of CPU, which sits idle while requests back up.
- **Air gaps are a first-class case.** Two registry values (one for the application images and Valkey, one for the NATS subchart) and a per-release image manifest are all a disconnected cluster needs.

## The Same Pipeline, Now in Pods

If you read the [AWS queue-mode post](/blog/aws-queue-mode-scalability), the shape will look familiar. Every chat request still travels the five-stage path:

```
Request Handler → Input Queue → Agent Runner → Output Queue → Response Handler
```

On Kubernetes the chart splits those stages across two Deployments, with a third one optional:

| Deployment | What it runs |
|---|---|
| `io-handler` | The REST API (Request Handler) and the Response Handler that reads replies back off the output queue |
| `agent-runner` | The consumers that execute your agents: LLM calls, tools, retries |
| `ws-gateway` (optional) | WebSocket delivery for the `async` and `stream` execution modes |

Traffic enters through a Gateway API `HTTPRoute`, REST to the io-handler and WebSocket to the gateway. Valkey holds responses and sessions, NATS JetStream is the default broker, and both ship as condition-gated dependencies of their official charts, so a dev cluster gets them for free and a production cluster can point at the instances it already operates.

## Your Images, the Chart's Wiring

The chart runs *your* images. Your `config.yaml`, baked into the image, declares what runs: which agents, which framework, which execution mode. The chart injects where it runs as `AK_*` environment variables. It is the same application and infrastructure split the ECS Terraform deployment uses, so an image built for one feels familiar on the other.

Each image has a one-line entry point:

| Image | Entry point |
|---|---|
| io-handler | `IOHandler.run()` |
| agent-runner | register your agent modules, then `AgentRunner.run()` |
| ws-gateway | `WebSocketGateway.run(auth_validator=...)` |

The [end-to-end example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/k8s/openai-queue-mode) builds all three from `python:3.12-slim` and walks the deployment on k3d, microk8s, and k3s. Kubernetes is not even required to exercise the wire behavior: the same pipeline runs as two local processes over docker compose under `examples/transport/nats`.

## Three Flavors, Zero Forked Templates

Deployment flavors are values files over one set of templates. Every difference between a laptop and a data center is a value, never a fork.

| Values file | Posture |
|---|---|
| `values-dev.yaml` | Micro-clusters (k3d, kind, microk8s, k3s): single replicas, auto-provisioned JetStream, TLS off, port-forward entry. The smallest profile is one pod with in-process queues and no backing services at all. |
| `values-baremetal.yaml` | Envoy Gateway class, cert-manager issuer annotations, NACK-managed JetStream objects, OpenEBS hostpath storage, MetalLB as the load balancer. |
| `values-eks.yaml` | AWS Load Balancer Controller gateway classes, ACM certificates, EBS gp3 storage, Pod Identity. `nats`, `kafka`, and `sqs` are all valid brokers here. |

The flavor files ship inside the chart, which is what `helm pull --untar` unpacks, so the values you start from always match the chart version you installed.

## Pick Your Broker

`transport.type` selects the broker. The pipeline semantics do not move:

- **`nats`**, the default and the recommendation on-prem. JetStream work-queue streams with one durable consumer per partition. Dev clusters auto-provision the streams at startup; production manages them declaratively through the chart's NACK custom resources and fails loudly if an object is missing, rather than creating one on the fly.
- **`kafka`**, paired with the Strimzi operator. The chart renders the Kafka cluster, its node pool, and the topics as Strimzi resources, so the broker is part of the same release as the application.
- **`sqs`**, for EKS. No broker to operate at all: pods authenticate through Pod Identity and the queues live in AWS.

Whichever you choose, a conversation's turns stay in order, a crashed runner leaves the turn on the queue for the next one, a retried request is not enqueued twice, and a turn that exhausts its retries produces a graceful error reply instead of a silent hang.

## WebSockets That Survive a Rollout

Streaming and push delivery are where most Kubernetes deployments of chat systems get awkward, because a socket is pinned to a pod and pods are disposable. The chart's `ws-gateway` tier is built around that fact instead of against it.

Gateway pods own the client sockets and enqueue chat frames directly onto the transport. When the Response Handler has a reply, or a single streamed token chunk, it looks up which gateway pod holds that user's connections in a shared connection store on the session backend and pushes to an authenticated internal endpoint on that pod. Replies reach every connection a user has open, on whichever pod holds it. Because the io-handler and agent-runner pods are never on the socket path, they can roll, scale, or crash without dropping a single connection.

## Scaling on the Signal That Matters

An agent turn is I/O-bound. The runner spends most of its life waiting on a model provider while requests pile up behind it, so CPU utilisation is the one metric that tells you nothing. The `agent-runner` tier therefore scales on queue depth through KEDA: Kafka consumer lag, NATS JetStream pending messages, or SQS queue length, chosen automatically by the transport you configured.

Two guardrails are baked into the defaults. `minReplicaCount` is 1, because a runner cold start (image pull plus Python imports) is slow enough that scaling from zero would hurt the first customer of the morning. For the NATS and Kafka transports, `maxReplicaCount` defaults to the partition count divided by consumers per pod, since past that point a new replica finds no free partition to claim; for SQS it defaults to 10. The `io-handler` tier, which is request-bound, scales on plain CPU.

Scaling down is as careful as scaling up. Runners observe SIGTERM, stop claiming work, and finish their in-flight turns within `terminationGracePeriodSeconds`, which defaults to two minutes and should exceed your longest agent turn.

## A Sandbox Worker Tier, Inside the Same Chart

If your agents run code through the [Execution Broker](/blog/agent-kernel-execution-broker), the chart also deploys the queue-backed sandbox worker. Enable `sandboxWorker` and a third consumer tier appears: it takes sandbox execution requests off their own queues on the same transport, runs each one through a sandbox provider (typically the `kubernetes` provider, one pod per sandbox, running as a ServiceAccount the chart binds to nothing, so the RBAC you grant it is the security boundary), and returns completions into the shared response store. The tier brings its own ServiceAccount and RBAC, KEDA scaling on the sandbox backlog, and values-gated namespace hardening: Pod Security Admission, default-deny egress, and resource quotas.

It also installs standalone. If your agents run in Lambda or ECS but code execution has to happen inside your own cluster, disable `ioHandler` and `agentRunner`, and the chart deploys only the sandbox worker. The agent side and the worker then meet solely on the shared sandbox queues and response store.

## Built for Air Gaps

Disconnected clusters get two things. `global.imageRegistry` prefixes the application images and the Valkey subchart's; the NATS subchart reads `global.image.registry` instead, so set both and every image the chart renders comes from your private registry. And every release attaches an `images.txt` manifest listing those images for mirroring, generated by templating every flavor with every optional tier enabled. One exception: on the Kafka flavor the Strimzi operator pulls the broker images itself, so they are mirrored and configured through Strimzi, not this chart. The chart itself is an OCI artifact, so it copies into the same registry and installs by digest from there.

## Observability Without Surprises

Metrics and tracing ship as documented recipes rather than chart dependencies: a kube-prometheus-stack install, exporters for whichever broker you chose, and an OpenTelemetry Collector funnel that feeds the Langfuse, OpenLLMetry, and Pydantic Logfire tracing providers Agent Kernel already supports. Your existing monitoring stack keeps its job.

## Get Started

You need Helm 3.14 or newer (Helm 4 works too), a cluster on Kubernetes 1.29 or later, and your application images loaded where the cluster can pull them.

```bash
helm pull oci://ghcr.io/yaalalabs/charts/agent-kernel --untar   # unpacks the flavor values files
helm install ak oci://ghcr.io/yaalalabs/charts/agent-kernel \
  -f agent-kernel/values-dev.yaml \
  --set ioHandler.image.repository=<io image> \
  --set agentRunner.image.repository=<runner image> --set image.tag=<tag>

kubectl port-forward service/ak-agent-kernel-io 8000:80
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Hello", "session_id": "s1", "agent": "triage"}'
```

Without a `--version` flag Helm resolves the latest published chart; add one to pin a release, and the [deployment guide](/docs/deployment/onprem-kubernetes) always shows the current pinned command. One thing to know when you find the chart on GitHub: the package page shows a `docker pull` command, because GitHub renders that box for every artifact in its container registry. Charts are installed with `helm`, as above.

Agent Kernel is open source under Apache 2.0.

- On-Prem / Kubernetes deployment guide: https://kernel.yaala.ai/docs/deployment/onprem-kubernetes
- Chart README, with values, prerequisites, and flavors: https://github.com/yaalalabs/agent-kernel/tree/develop/ak-deployment/ak-k8s
- End-to-end example on k3d, microk8s, and k3s: https://github.com/yaalalabs/agent-kernel/tree/develop/examples/k8s/openai-queue-mode
- The chart on GHCR: https://github.com/yaalalabs/agent-kernel/pkgs/container/charts%2Fagent-kernel
- Queue Mode Guide: https://kernel.yaala.ai/docs/advanced/queue-mode-guide

`helm install` it on the cluster you already trust, and let the agents come to the data instead of the other way round.
