# Reading the results

Caveats and expected effects that help people read the benchmark graphs. **These are not requirements.** The
benchmark records and reports only; it must not try to detect, prevent or fix anything here.

## Bottlenecks outside AK's workers

- **Load-generator machine:** at 1000+ concurrent WebSockets its CPU, sockets or network can saturate and make AK look
  slower than it is.
- **The front door:** API Gateway WebSocket quotas (Lambda); the ALB scaling up gradually under a sudden spike
  (ECS/EKS); a fixed-capacity ingress or load balancer (bare metal).
- **Other limits:** Lambda concurrency quota, Kafka partition count (caps useful runner replicas), bare-metal node
  capacity.
- They show up in the graphs (Tx below the planned rate, latency rising while workers are idle) and are handled by
  people.

## Measurement caveats

- **Clock offsets:** client times come from the load-generator clock, stage times from cloud clocks. NTP-level offsets
  shift the client↔cloud legs a little. End-to-end latency and Tx/Rx use the client clock only.
- **Fetchers disagree:** fetchers for the same tier have different resolution and lag; the lines differ and are kept
  as they are.
- **Log-based counts see only busy workers.**
- **Metrics and logs arrive late**, which is why those fetchers run after the run.
- **Lambda counts are low by design:** one environment works through a batch of 10 messages, so 1000 requests show as
  roughly 100 concurrent executions. `ConcurrentExecutions` has 1-minute resolution and counts invocations in
  progress, so it reads low with a very short agent delay.

## Run length

- Every step ends only after its cool-down. On ECS a step that scaled out takes roughly 20-40 min, so four steps × two
  test types can take several hours per host. Lambda and K8s scale down faster.
- Small steps may not scale at all; their cool-down ends almost at once.
- Lambda steps end a little late because the end is read from a CloudWatch metric. The extra minutes are idle time.
- A step that hit the maximum cool-down starts the next step with more than the minimum workers, which shows in that
  step's "before" worker count.
