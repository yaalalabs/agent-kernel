# Platform scaling and cost sources

How each benchmarked host scales and bills, and where the benchmark can read worker counts, queue depth and cost.
Background for the host bundles in [`../design.md`](../design.md#hosts) and the derived numbers in
[`../spec.md`](../spec.md).

## Repo facts (checked on `develop`, 2026-10-25)

- **ECS autoscaling is off by default.** `scaling_config` in `ak-deployment/ak-aws/containerized/variables.tf:394-411`:
  `enabled = false`, `min_count = 0`, `max_count = 10`, `backlog_target = 10`, `scale_in_cooldown = 120`,
  `scale_out_cooldown = 30`. The benchmark sets `enabled = true` and `min_count >= 1`.
- **Only the ECS agent runner autoscales.** The metric is `BacklogPerTask = ApproximateNumberOfMessages /
  max(runningCount, 1)`, published by a Lambda every minute (`modules/agent-runner/main.tf:470-472`, `:563`). The
  REST/IO service runs a fixed `desired_count` (default 1, `containerized/variables.tf:158`).
- **Lambda SQS batch size is 10** (`ak-aws/serverless/variables.tf:493`), and the serverless `SQSConsumer` handles a
  batch's records one after another (`deployment/aws/serverless/core/sqs_consumer.py:42`). So one invocation runs
  for about `batch_size × agent delay`.
- **The Lambda agent runner timeout is 45 s by default.** The root `agent_runner` variable defaults `timeout` to 45
  (`ak-aws/serverless/variables.tf:376-381`) and is merged into the module (`state.tf:642-648`), overriding the
  module's own default of 30 (`modules/agent-runner/variables.tf:182`). `batch_size × agent delay` must stay under it
  (10 × 4 s already does not).
- **KEDA is off by default in the chart** (`ak-deployment/ak-k8s/chart/values.yaml:347-357`): `keda.enabled: false`,
  `minReplicaCount: 1`, `pollingInterval: 30`, `cooldownPeriod: 300`, `lagThreshold: "5"`. With `minReplicaCount: 1`,
  scaling from N back to 1 is done by the HPA that KEDA creates, so KEDA's `cooldownPeriod` (scale to 0 only) does not
  apply.
- **Kafka commits an offset only after processing** (`ak-py/src/agentkernel/pipeline/transport/kafka.py:104`), so a
  message being processed still counts as consumer-group lag.

## Scaling: what sets the timings

- **ECS target tracking:** scales out after 3 consecutive one-minute datapoints above target, scales in after 15
  below. Then `scale_in_cooldown` (120 s in our Terraform; 300 s Application Auto Scaling default) between scale-in
  activities, and `scale_out_cooldown` (30 s in our Terraform) between scale-outs. A normal scale-in is expected to
  take ~15-25 min. AWS's June 2026 high-resolution (20 s) scaling covers built-in CPU/memory metrics only, not custom
  metrics like `BacklogPerTask` (not verified whether the 3/15 rule changed for custom metrics).
- **K8s HPA:** re-evaluates every 15 s; default scale-up adds at most 4 pods or 100% of current replicas (whichever
  is more) per 15 s; default scale-down stabilization window 300 s. Bare metal has no node autoscaler, so pods go
  `Pending` when nodes are full. KEDA's Kafka scaler won't go past the input topic's partition count unless
  `allowIdleConsumers: true`.
- **Lambda + SQS (default mode):** starts with 5 concurrent invocations, adds up to 300 per minute, up to 1,250 per
  event source mapping and within the account concurrency quota (1,000 by default). Concurrency drops as soon as
  invocations stop. With batch size 10, a burst of 1000 requests shows as roughly 100 concurrent executions.

## Scaling info fetchers per host

| Host | Fetcher (registry name) | `live` | Gives | Resolution |
|---|---|---|---|---|
| ECS | `aws.ecs_api`: `DescribeServices` (`desiredCount`, `runningCount`) + `DescribeTasks` (`createdAt`, `pullStartedAt`, `startedAt`, `stoppedAt`) | yes | desired, running, spans | poll interval; spans exact |
| ECS | `aws.ecs_scaling_activities`: Application Auto Scaling `DescribeScalingActivities` | no | desired | exact |
| EKS, bare metal | `k8s.api`: Deployment `spec.replicas`, `readyReplicas`, pod start/stop, `Pending` pods | yes | desired, running, pending, spans | poll interval; spans exact |
| Lambda | `aws.cloudwatch_metric.ConcurrentExecutions`: `AWS/Lambda` per `FunctionName`, `Maximum` | no | running | 1 min |
| Lambda (written, not bound) | `aws.lambda_log_streams`: one span per log stream (= execution environment), first to last `REPORT` line | no | running, spans | about one invocation |

- Stopped ECS tasks stay visible in `DescribeTasks` for at least 1 hour; scaling activity history is kept 6 weeks.
- `ConcurrentExecutions` counts invocations in progress, not live environments, and may have **no datapoint** (not 0)
  in a minute with no invocations (not verified).
- Only ECS and K8s expose a `desired` count.
- Later platforms (for the pluggability check only): Azure Container Apps List Replicas API and `Replicas` metric
  (1 min); Cloud Run `labels.instanceId` in Cloud Logging and the `instance_count` metric (sampling not verified);
  Azure Functions Flex instance count (30 s, metric name not verified).

## Queue depth

- **SQS:** `GetQueueAttributes` `ApproximateNumberOfMessages` (waiting) and `ApproximateNumberOfMessagesNotVisible`
  (in flight). AWS says these may not be consistent until at least 1 minute after producers stop.
- **Kafka:** consumer-group lag per topic (see the commit fact above).

## Cost

- **Billed:** Cost Explorer `GetCostAndUsage` filtered by a cost allocation tag. The tag must be activated in the
  management account; backfill up to 12 months, one request per 24 h. Data refreshes at least every 24 h; hourly
  granularity is opt-in and kept 14 days. $0.01 per API request. The EKS control plane fee is not covered by the
  automatic `aws:eks:cluster-name` tag.
- **Estimated (usage × list price):**
  - Fargate: per second, 1-minute minimum, from the start of the image pull (`pullStartedAt`) to `stoppedAt`.
  - Lambda: `Billed Duration` × `Memory Size` from `REPORT` lines, plus requests.
  - SQS: billed per API request (a batch of up to 10 messages is one request per 64 KB), empty receives included.
    CloudWatch message counts overcount when batching is used.
  - API Gateway WebSocket: messages metered in 32 KB blocks (ping/pong not billed) plus connection minutes.
  - EKS: node-hours + control plane hours; pod-level split via split cost allocation data (CUR) or OpenCost.
  - Bare metal: node-hours × a configured $/node-hour.
- **Prices:** AWS Price List Query API `GetProducts` (on-demand `pricePerUnit`); later GCP Cloud Billing Pricing API
  (API key) and the unauthenticated Azure Retail Prices API.

## Sources (checked 2026-10-20 to 2026-10-23)

- Kubernetes HPA: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- KEDA ScaledObject spec: https://keda.sh/docs/2.18/reference/scaledobject-spec/
- KEDA Kafka scaler: https://keda.sh/docs/2.17/scalers/apache-kafka
- Application Auto Scaling target tracking: https://docs.aws.amazon.com/autoscaling/application/userguide/target-tracking-scaling-policy-overview.html
- Target tracking 3/15 datapoints and June 2026 faster scaling: https://github.com/aws/containers-roadmap/issues/2113
- ECS high-resolution metrics: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/target-tracking-faster-auto-scaling.html
- ECS stopped tasks ≥ 1 hour: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/stopped-task-errors.html
- Scaling activities (6 weeks): https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-scaling-activities.html
- Lambda SQS scaling: https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html
- Lambda metrics: https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics.html, https://docs.aws.amazon.com/lambda/latest/dg/monitoring-concurrency.html, https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html
- Logs Insights fields, `count_distinct`, paging: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_AnalyzeLogData-discoverable-fields.html, https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax-Stats.html, https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html
- SQS `GetQueueAttributes`: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_GetQueueAttributes.html
- Cost allocation tag backfill: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-allocation-backfill.html
- Cost Explorer hourly granularity and pricing: https://docs.aws.eu/cost-management/latest/userguide/ce-hourly-granularity.html, https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/
- SQS, Fargate, API Gateway pricing: https://aws.amazon.com/sqs/pricing/, https://aws.amazon.com/fargate/pricing/, https://aws.amazon.com/api-gateway/pricing/
- Price List Query API: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html
- EKS split cost allocation: https://docs.aws.amazon.com/cur/latest/userguide/split-cost-allocation-data.md
- GCP / Azure fetchers and prices: https://docs.cloud.google.com/run/docs/monitoring, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-app-containerapps-metrics, https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
