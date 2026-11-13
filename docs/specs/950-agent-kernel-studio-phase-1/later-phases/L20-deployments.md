# 20 · Deployments

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Operate-Deployments` (main, Production), `Operate-Deployments-Staging`, `Operate-Deployments-Local`, `Operate-Deployments-ChangeTarget` |
| Canvas page | Operate |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. The environment tabs are prototype links. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The operations view of where the system runs. The same project runs in one local process, on Kubernetes with
the Helm chart, or on a cloud with Terraform. A topology diagram shows the queue pipeline for the selected
environment, and a configuration table shows the settings that drive it. The Deploy tab in the builder (08) is
where a deploy is started; this page is where it is watched and audited.

## Layout

- `AppShell` with Deployments active. Page header "Deployments", tabs Local, Staging, Production (active).
- A summary card, a topology card, then "Configuration" beside "Deploy history".

## Content

**Summary.** AWS mark, "Production · AWS ECS Fargate · eu-west-1", status "Healthy". Chips: "Queue mode",
"Transport: SQS FIFO", "Execution: async + delta", "Session: Redis", "Secrets: AWS SSM", "Tracing: Langfuse".
A line "Last deploy 2 h ago · v0.9.14 · by Claude Code, approved by Amitha D. and Priya N." with an `AIBadge`.
Actions: "View logs", "Rollback", primary "Deploy".

**Topology.** A left-to-right diagram of boxes, each with a title, a replica count and a health dot, joined by
arrows:

1. Clients (web, Slack, WhatsApp)
2. API Gateway
3. IO handler · REST and response handler · 2 replicas
4. SQS input queue · depth 12
5. Agent runner · 3 replicas · KEDA 1 to 10
6. SQS output queue, with a return arrow to the IO handler
7. From the IO handler: WebSocket gateway · 2 replicas, back to Clients

Dependencies below the main row, joined by dashed lines: "Redis · sessions, threads, attachments, response
store", "EventBridge Scheduler", "SSM Parameter Store", "Langfuse".

**Configuration.** Key and value pairs:

| Key | Value |
|-----|-------|
| `execution.mode` | async |
| `execution.message_type` | delta |
| `execution.queues.type` | sqs |
| `execution.queues.input.no_of_consumers` | 5 |
| `execution.queues.input.max_receive_count` | 3 |
| `session.type` | redis |
| `thread.type` | redis |
| `multimodal.storage_type` | redis |
| `websocket_api.push_auth_token` | set (masked) |
| `secret.provider.type` | aws_ssm |
| tracing | Langfuse |

A control "Open config.yaml".

**Deploy history** (`DataTable`). Version, time, actor, status, duration, a "Details" link. The latest row:
"v0.9.14 · 2 h ago · Claude Code · Succeeded · 6 min 12 s". Four earlier rows, one "Failed" and one "Rolled
back".

## Behaviour

- The tabs link the three environment artboards. "Deploy" goes to `Builder-Deploy`. "Open config.yaml" goes to
  `Builder-Config`. The target name opens `Operate-Deployments-ChangeTarget`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Operate-Deployments-Staging` | first | "Staging · Kubernetes (Helm) · onprem-staging", status "Deploying v0.9.15 · 63%" with a progress bar. Chips: "Transport: NATS JetStream", "Execution: async + delta", "Session: Valkey", "Secrets: Kubernetes Secrets", "Autoscaling: KEDA". The topology uses NATS JetStream in place of SQS and names the gateway "ws-gateway". Configuration shows the Helm values keys. |
| `Operate-Deployments-Local` | first | "Local · single process · in_memory transport". A command card `uv run python app.py`. A note "The in-memory transport reproduces FIFO, retry and dedup semantics without a broker". The topology is one box: "IO handler (REST, response handler and agent runner threads)". |
| `Operate-Deployments-ChangeTarget` | second | A modal with six target cards and their supported modes: AWS Lambda (serverless), AWS ECS Fargate (containers, selected), Azure Functions, Azure Container Apps, Google Cloud Run, Kubernetes (Helm); a "Region" select; a toggle "Generate Terraform / Helm values"; "Cancel" and "Apply". |

## Tweaks

- `topology`: diagram or table.

## Handoff notes

- The topology is the runtime's real pipeline: request handler, input queue, agent runner, output queue,
  response handler, with an optional WebSocket gateway tier.
- The Production approval by two people is BR-005.
- Replica counts, queue depth and the deploy history are fixture data.
