# Sandbox Queue Broker on Kubernetes: the NATS chart shape

The #503 fully-in-cluster shape: the Agent Kernel two-process pipeline AND the sandbox
broker worker, all deployed by [the Helm chart](../../../ak-deployment/ak-k8s/) over NATS
JetStream. Agents run in the `agent-runner` pods; their sandbox executions travel the
sandbox queues to the `sandbox-worker` pod, which runs them as pods in a **hardened
namespace** (Pod Security Admission `restricted`, default-deny egress, a pinned non-root
securityContext) under a ServiceAccount bound to nothing.

```
app_io_handler.py         IOHandler.run()              the io image's entry point
app_agent_runner.py       agents + AgentRunner.run()   the runner image's entry point
app_sandbox_worker.py     QueueBrokerWorker.run()      the sandbox worker image's entry point
config.nats.yaml          baked in as config.yaml by package.sh (sandbox block included)
sandbox-values.yaml       chart overlay: images + sandboxWorker + hardening
deploy/Dockerfile.*       one image per component, python:3.12-slim + staged dependencies
deploy/package.sh         stages dependencies and builds the three images
app_test.py               the automated walkthrough (kind + helm; self-skips without them)
```

This example builds on [examples/k8s/openai-queue-mode](../../k8s/openai-queue-mode/) (read
its README for the pipeline itself and the cluster options); the Kafka half of #503, where
the agent side lives OUTSIDE the cluster, is [../broker-kafka](../broker-kafka/).

## Prerequisites

- Docker, [uv](https://docs.astral.sh/uv/), Helm 3.14+ (or 4), kubectl
- A micro-cluster: [k3d](https://k3d.io) on macOS, kind, microk8s, or k3s
- An OpenAI API key

## Build and deploy

```bash
./build.sh                  # or ./build.sh local to use a locally built agentkernel wheel
cd deploy && ./package.sh && cd ..    # or ./package.sh local

k3d cluster create ak
k3d image import -c ak ak-sbx-io-handler:dev ak-sbx-agent-runner:dev ak-sbx-sandbox-worker:dev
# kind instead: kind load docker-image ak-sbx-io-handler:dev ak-sbx-agent-runner:dev ak-sbx-sandbox-worker:dev

kubectl create secret generic openai --from-literal=api-key="$OPENAI_API_KEY"

helm dependency build ../../../ak-deployment/ak-k8s/chart
helm install ak ../../../ak-deployment/ak-k8s/chart \
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f sandbox-values.yaml
kubectl rollout status deployment/ak-agent-kernel-io deployment/ak-agent-kernel-agent-runner \
  deployment/ak-agent-kernel-sandbox-worker
```

The overlay creates the `ak-sandboxes` namespace with the PSA `restricted` label, a
default-deny egress NetworkPolicy over every sandbox pod, the worker's ServiceAccount + Role
(pods and `pods/exec` in `ak-sandboxes`, nothing else), and the `ak-sandbox-pod`
ServiceAccount that sandbox pods run as, deliberately bound to nothing.

## The walkthrough: bounded wait, promotion, recovery

Port-forward the REST API:

```bash
kubectl port-forward service/ak-agent-kernel-io 8000:80 &
```

**1. A short execution completes inside the bounded wait** (`broker.wait_timeout: 8`): the
runner pod enqueues the request on `SANDBOX_REQUESTS`, the worker creates a pod in
`ak-sandboxes`, executes, sends the completion over `SANDBOX_COMPLETIONS` into Valkey, and
the runner's poll picks it up, all within one chat turn:

```bash
curl -s -X POST http://localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{
  "prompt": "Run python in the sandbox to compute sum(range(10**6)) and reply with only the number.",
  "session_id": "s1", "agent": "coder"}'
```

Watch the sandbox pod appear (and stay, for session reuse) in the hardened namespace:

```bash
kubectl get pods -n ak-sandboxes
```

**2. A long execution promotes: the turn ends with a pending task.** The tool waits 8
seconds, then returns a pending task handle and the agent tells you so:

```bash
curl -s -X POST http://localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{
  "prompt": "Run python in the sandbox: import time; time.sleep(30); print(\"DONE-4242\"). If the sandbox reports the execution as pending, reply with exactly PENDING and the task id.",
  "session_id": "s1", "agent": "coder"}'
```

Meanwhile the execution keeps running in the worker; its completion record lands in the
response store whenever it finishes, whether or not anyone is waiting.

**3. Recover the result on the next turn with `check_sandbox_task`.** Wait ~30 seconds,
then ask the same session:

```bash
curl -s -X POST http://localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{
  "prompt": "Check that pending sandbox task now and reply with only the output it captured.",
  "session_id": "s1", "agent": "coder"}'
```

The reply is `DONE-4242`: `check_sandbox_task` returns the finished task's bounded output
(the wait-then-check recovery contract; no completion events, no re-invocation).

**4. See the hardening bite.** Egress is default-denied for sandbox pods, so a network
request from sandboxed code fails:

```bash
curl -s -X POST http://localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{
  "prompt": "Run python in the sandbox that fetches https://example.com with a 5 second timeout and prints the status code. If it fails for any reason, reply with only the word OFFLINE.",
  "session_id": "s1", "agent": "coder"}'
```

And the namespace itself rejects non-compliant pods (`kubectl get ns ak-sandboxes
--show-labels` shows the PSA label); the provider's hardened securityContext defaults plus
the `security_context` block in config.nats.yaml are what let the sandbox pods pass it.

Cleanup:

```bash
helm uninstall ak
kubectl delete namespace ak-sandboxes   # chart-created; pods in it are gone with it
k3d cluster delete ak
```

## Production notes

- Swap `python:3.12-slim` for your security team's hardened image; keep it non-root and
  give it whatever interpreters your agents need. The image is the operator's contract:
  `install_packages` is pip against that image, and OS packages belong in the image build.
- Set `auto_provision: false` and manage the four JetStream streams (chat + sandbox) as
  NACK CRs: `natsResources.enabled` in the chart renders all four (the sandbox pair is
  included whenever `sandboxWorker.enabled` is set).
- Size `sandbox.broker.queue.nats.ack_wait` above your largest profile `policy.timeout`,
  or a still-running execution gets redelivered and runs twice (at-least-once semantics).
- With KEDA installed, `keda.enabled: true` also scales the sandbox worker on the
  `SANDBOX_REQUESTS` backlog.
