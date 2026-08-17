---
slug: /aws-queue-mode-scalability
title: "Scaling Agent Kernel on AWS: Decoupling Request Handling from Agent Execution"
authors: [yaala]
tags: [agent-kernel, aws, scalability, sqs, lambda, ecs, queue-mode, enterprise-ai]
image: /img/card.png
description: Agent Kernel now decouples request handling from agent execution on AWS with a durable SQS queue pipeline, giving Lambda and ECS deployments independent scaling, backpressure, and automatic retries with zero agent-code changes.
---

# Scaling Agent Kernel on AWS: Decoupling Request Handling from Agent Execution

**Request handling and agent execution don't scale the same way — running them as one unit means one is always sized for the other's traffic.**

Agent Kernel's own deployment docs are direct about the tradeoff: the simplest AWS setup — one ECS service, or one Lambda function, handling both the REST API and the full agent turn — is scoped for "moderate traffic, simplest setup." Getting to "high throughput, long-running agents, backpressure control" means putting a queue between the two. Agent Kernel now ships that durable queue pipeline on AWS, for both Lambda and ECS, with zero changes to agent code.

<!-- truncate -->

## The Problem With Scaling as One Unit

An HTTP request is cheap and fast to handle. An agent turn is not: it can chain multiple LLM calls, wait on tool execution, and take anywhere from a second to several minutes. When request intake and agent execution share the same container or the same Lambda invocation, they're forced to scale together, sized for whichever workload is heavier, instead of on their own curves.

It also means there's nothing standing between the caller and the model provider. Without a queue to absorb a burst, request volume maps straight onto provider call volume — a spike in traffic is a spike in simultaneous provider calls, with nothing capping how hard the provider gets hit or smoothing the burst into a manageable rate. That's a fine trade at moderate, steady traffic. It stops being fine the moment concurrent long-running turns start arriving in bursts, which is exactly when scaling matters most.

## Putting a Queue in the Middle

The fix is unglamorous and well-worn: put a durable queue between the caller and the agent. Every chat request now travels a fixed five-stage path:

```
Request Handler → Input Queue → Agent Runner → Output Queue → Response Handler
```

The queue transport and the process topology are chosen entirely by configuration, not by rewriting agent code. Locally, all five stages run as threads inside one process against an in-memory transport, so the exact same pipeline semantics: per-session ordering, bounded retry, deduplication, are testable on a laptop. On AWS, the queues become durable **SQS FIFO queues**, and the stages split across Lambda functions or ECS services depending on which deployment you pick.

Splitting the pipeline this way buys you several things at once:

- **Independent scaling** — the request/response path and the Agent Runner pool scale on their own curves instead of being sized as one unit.
- **Backpressure** — a traffic spike lengthens the queue instead of fanning out into a pile of simultaneous provider calls.
- **Per-session ordering** — `MessageGroupId = session_id` keeps a conversation's turns strictly in order while unrelated sessions process fully in parallel.
- **Crash resilience** — a message only leaves the queue once it's fully processed, so a worker crashing or hanging mid-turn simply leaves the turn there for the next worker.
- **Automatic bounded retries** — unacknowledged messages redeliver up to `max_receive_count`, absorbing provider rate limits and transient failures without the caller noticing. After that, the caller gets a graceful error instead of a hang.
- **Deduplication** — `MessageDeduplicationId = request_id` means a retried message can never be processed, or appended to conversation history, twice.

None of this is exotic. What matters is that Agent Kernel now gives it to you as a configuration switch rather than infrastructure you build yourself.

## Two Deployment Shapes, One Pipeline

### Lambda: Scaling You Don't Have to Configure

On Lambda, the five stages map to three functions. A **Request Handler** enqueues onto the Input SQS FIFO queue with the session ID as the message group. An Event Source Mapping triggers the **Agent Runner** Lambda, which runs the agent and writes the reply to the Output Queue, reporting partial failures via `batchItemFailures` so only the messages that actually failed come back for retry. A second ESM triggers the **Response Handler**, which writes the result to DynamoDB (`rest_sync`/`rest_async`) or pushes it straight over a WebSocket connection (`async`/`stream`).

The appeal here is that Lambda scales the Agent Runner 1:1 with queue batches automatically. There's no scaling policy to write and no capacity to plan for; concurrency grows and shrinks with the backlog on its own.

### ECS: Long-Running Services, Explicit Scaling

ECS trades Lambda's zero-config scaling for containers that stay warm, which matters for consistent latency and workloads that don't fit serverless limits well. The same five stages become two services: an **IO container** running a REST/WebSocket API thread alongside an Output Queue consumer thread, and an **Agent Runner** service whose threads long-poll the Input Queue directly. Both are internally multi-threaded — five input consumers and two output consumers by default — so a single container is already handling several sessions concurrently before the ECS service itself scales out.

Because ECS doesn't get Lambda's built-in batch-triggered scaling, it needs an explicit policy. CPU and memory are a poor proxy here: agent workloads are I/O-bound, waiting on the model provider, not burning CPU. So the Agent Runner scales on **backlog per task** instead: a scheduled Lambda reads the Input Queue depth every minute, divides it by the running task count, and publishes the result as a custom CloudWatch metric. An ECS Target Tracking policy then holds that number at or below a target you set:

```hcl
scaling_config = {
  enabled            = true
  min_count          = 1
  max_count          = 10
  backlog_target     = 5
  scale_in_cooldown  = 180
  scale_out_cooldown = 60
}
```

`backlog_target` is the one knob that matters: a lower value (1-2) keeps latency tight by scaling out aggressively; a higher value (5-10) trades some queue depth for cost efficiency. It's also possible to scale the Agent Runner to zero (`min_count = 0`) for spiky or infrequent workloads, letting the fleet park at no cost between bursts.

## The Same Guarantee, Delivered Four Ways

Every one of the four client communication modes: REST Sync, REST Async (poll), Streaming (SSE/WebSocket chunks), and Async (WebSocket push), rides the identical Input Queue → Agent Runner → Output Queue shape. Only the last hop changes: `rest_sync`/`rest_async` land in a DynamoDB response store the caller reads back from; `async`/`stream` skip the database entirely and push straight down an open WebSocket connection, one message per full reply or one per streamed token chunk. Nothing about the queue contract, the retry semantics, or the ordering guarantee changes based on which mode a client is using.

One safety detail worth calling out: the app-level `max_receive_count` is deliberately set one below the SQS redrive policy's `maxReceiveCount`. That way, on the final retry, Agent Kernel writes a graceful error to the response store *before* SQS quietly moves the message to a dead-letter queue, so an HTTP caller never sits there waiting on a reply that's already been given up on.

## Config In, Not Code Change

Turning this on is a Terraform flag, not an agent rewrite:

```hcl
queue_mode     = true
execution_mode = "rest_sync"   # or rest_async | async | stream
```

The `yaalalabs/ak-containerized/aws` and `yaalalabs/ak-serverless/aws` Terraform modules provision the queues, IAM policies, response store, and (for ECS) the scaling stack automatically. Your agent definitions never reference a queue, a consumer thread, or a retry count — they run exactly as they do against the in-memory transport on your laptop.

## What's Next

SQS + Lambda and SQS + ECS validate a shape that generalizes: input queue, independently-scaling runner, output queue, pluggable response delivery. That same contract now also ships as a **Kafka transport** (`pip install agentkernel[kafka]`) for on-premise and self-hosted deployments, with the identical per-session ordering, dedup, and bounded-retry semantics, just backed by partitions and consumer groups instead of SQS FIFO queues. A Kubernetes-native topology (Helm charts, plus NATS JetStream as another pluggable transport) is next, so the scaling model here isn't tied to one cloud, or to AWS at all.

## Get Started

Agent Kernel is open source under Apache 2.0.

- Queue Mode Guide: https://kernel.yaala.ai/docs/advanced/queue-mode-guide
- AWS Containerized Deployment: https://kernel.yaala.ai/docs/deployment/aws-containerized
- GitHub: https://github.com/yaalalabs/agent-kernel

`pip install agentkernel` and let the queue absorb your next traffic spike instead of your Agent Runner.
