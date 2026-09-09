# Agent Kernel on Kubernetes: OpenAI agents in queue mode

Deploys OpenAI Agents SDK based agents as the Agent Kernel two-process pipeline on a
Kubernetes micro-cluster, using [the Helm chart](../../../ak-deployment/ak-k8s/): an
`io-handler` Deployment (REST API + Response Handler) and an `agent-runner` Deployment (the
consumers executing the agents), talking through in-cluster NATS JetStream with Valkey for
sessions and responses. A Kafka variant is one values switch away.

```
app_io_handler.py       IOHandler.run()                     the io image's entry point
app_agent_runner.py     agents + AgentRunner.run()          the runner image's entry point
app_ws_gateway.py       WebSocketGateway.run(validator)     the gateway image's entry point
ws_client.py            demo client for the WebSocket walkthrough (runs on your machine)
config.nats.yaml        baked in as config.yaml by package.sh (default)
config.kafka.yaml       the Kafka variant
deploy/Dockerfile.*     one image per component, python:3.12-slim + staged dependencies
deploy/package.sh       stages dependencies and builds the three images
```

The same wire behavior can be exercised without Kubernetes:
[examples/transport/nats](../../transport/nats/) runs the identical pipeline as two local
processes over docker compose.

## Prerequisites

- Docker, [uv](https://docs.astral.sh/uv/), Helm 3.14+ (or 4), kubectl
- A micro-cluster: [k3d](https://k3d.io) on macOS, microk8s on native Ubuntu, or k3s
  (kind works the same way and is what CI uses)
- An OpenAI API key

## Build the images

```bash
./build.sh                  # or ./build.sh local to use a locally built agentkernel wheel
cd deploy
./package.sh                # or ./package.sh local; add "kafka" for the Kafka variant
cd ..
```

`package.sh` stages each component's dependencies into `dist-<component>/data` (uv
cross-installs Linux wheels, so the build works from macOS too), bakes the chosen config
variant in as `config.yaml`, and builds all three images: `ak-example-io-handler:dev`,
`ak-example-agent-runner:dev`, and `ak-example-ws-gateway:dev` (the last one is only deployed
in the WebSocket walkthrough below).

## k3d (macOS and Linux)

```bash
k3d cluster create ak
k3d image import -c ak ak-example-io-handler:dev ak-example-agent-runner:dev
```

Give the pods the OpenAI key, then install the chart with the dev flavor:

```bash
kubectl create secret generic openai --from-literal=api-key="$OPENAI_API_KEY"

cat > ak-values.yaml <<'EOF'
image:
  tag: dev
  pullPolicy: Never          # the images were imported, never pulled
ioHandler:
  image:
    repository: ak-example-io-handler
agentRunner:
  image:
    repository: ak-example-agent-runner
extraEnv:
  - name: OPENAI_API_KEY
    valueFrom:
      secretKeyRef:
        name: openai
        key: api-key
EOF

helm dependency build ../../../ak-deployment/ak-k8s/chart
helm install ak ../../../ak-deployment/ak-k8s/chart \
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml
kubectl rollout status deployment/ak-agent-kernel-io deployment/ak-agent-kernel-agent-runner
```

The dev flavor has no gateway: port-forward to the io Service and talk to the agents. The
first request also provisions the JetStream streams (`auto_provision: true` in the dev
posture):

```bash
kubectl port-forward service/ak-agent-kernel-io 8000:80 &

curl -s -X POST http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Who is Napoleon?", "session_id": "session-1", "agent": "triage"}'
```

The triage agent hands off to the history agent and the reply comes back through
NATS -> agent-runner -> NATS -> Response Handler -> Valkey -> your waiting request. Watch it
happen:

```bash
kubectl logs deployment/ak-agent-kernel-agent-runner -f
```

Cleanup:

```bash
helm uninstall ak
k3d cluster delete ak
```

kind differs only in the image step: `kind load docker-image ak-example-io-handler:dev
ak-example-agent-runner:dev` (the chart's `chart/ci/kind-smoke-values.yaml` carries these
exact overrides for CI).

## microk8s (native Ubuntu)

The MetalLB addon does not work under Multipass on macOS, so use microk8s on native Ubuntu
only (macOS: k3d above).

```bash
sudo snap install microk8s --classic
microk8s enable hostpath-storage registry metallb   # metallb prompts for an IP range
```

Push the images to the built-in registry instead of importing them:

```bash
docker tag ak-example-io-handler:dev localhost:32000/ak-example-io-handler:dev
docker tag ak-example-agent-runner:dev localhost:32000/ak-example-agent-runner:dev
docker push localhost:32000/ak-example-io-handler:dev
docker push localhost:32000/ak-example-agent-runner:dev
```

Install as under k3d, with the registry prefix and (optionally) a MetalLB-backed
LoadBalancer instead of the port-forward:

```bash
microk8s helm install ak ../../../ak-deployment/ak-k8s/chart \
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml \
  --set global.imageRegistry=localhost:32000 \
  --set image.pullPolicy=IfNotPresent \
  --set serviceLB.enabled=true
microk8s kubectl get service ak-agent-kernel-io-lb   # EXTERNAL-IP from the MetalLB pool
```

## k3s

Closest-to-production baremetal parity: install k3s with its bundled ServiceLB and Traefik
disabled, then run the real `values-baremetal.yaml` flavor (MetalLB, Envoy Gateway,
cert-manager as prerequisites) instead of the dev flavor:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik --disable=servicelb" sh -
```

The chart install is identical to the baremetal instructions in
[ak-deployment/ak-k8s/README.md](../../../ak-deployment/ak-k8s/README.md); the dev-flavor
walkthrough above also works on k3s unchanged (k3s ships a local-path StorageClass).

## The Kafka variant

Kafka expects its topics to exist before the pipeline starts (Agent Kernel never creates
them), and the transport keeps its retry/dedup bookkeeping in the session store. The chart
renders the cluster and topics as Strimzi CRs:

```bash
# once per cluster: the Strimzi operator
kubectl create namespace kafka
kubectl create -f 'https://strimzi.io/install/latest?namespace=kafka' -n kafka
kubectl set env deployment/strimzi-cluster-operator -n kafka STRIMZI_NAMESPACE=default

cd deploy && ./package.sh kafka && cd ..   # bake config.kafka.yaml in as config.yaml
k3d image import -c ak ak-example-io-handler:dev ak-example-agent-runner:dev

helm upgrade --install ak ../../../ak-deployment/ak-k8s/chart \
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml \
  --set transport.type=kafka --set kafka.enabled=true --set kafka.replicas=1 \
  --set kafka.partitions=4 --set kafka.topicReplicas=1 --set nats.enabled=false
```

The chat request is byte-for-byte the same as under NATS: the transport is infrastructure,
not API.

## WebSocket streaming (async / stream modes)

The REST modes above need no gateway tier. For token streaming, the third image
(`ak-example-ws-gateway`, from `app_ws_gateway.py`) runs the WebSocket gateway: it
authenticates each handshake with a demo JWT validator (users `user-1`/`user-2`, signature
verification off, demo only), enqueues chat frames straight to the transport, and receives
each reply chunk from the Response Handler on its authenticated `/internal/push` endpoint.
The connection table rides the session store, which values-dev already puts on Valkey.

Switch the running release to stream mode with the gateway enabled (config unchanged: the
mode override is one env var away):

```bash
k3d image import -c ak ak-example-ws-gateway:dev    # kind: kind load docker-image ...

helm upgrade ak ../../../ak-deployment/ak-k8s/chart \
  -f ../../../ak-deployment/ak-k8s/chart/values-dev.yaml -f ak-values.yaml \
  --set execution.mode=stream \
  --set wsGateway.enabled=true --set wsGateway.replicaCount=1 \
  --set wsGateway.image.repository=ak-example-ws-gateway \
  --set wsGateway.auth.token="$(openssl rand -hex 16)"
kubectl rollout status deployment/ak-agent-kernel-ws-gateway
```

Then connect and stream (the client lives in this directory; `./build.sh` installed its
dependencies):

```bash
kubectl port-forward service/ak-agent-kernel-ws-gateway 18001:8000 &
uv run python ws_client.py ws://localhost:18001/ws "Tell me about Napoleon in two sentences."
```

The client prints a `CHAT_QUEUED` acknowledgement, then the `STREAM_CHUNK` frames as the
runner produces them, the last one carrying `done: true` (in `async` mode a single
`CHAT_RESPONSE` frame arrives instead). Each chunk traveled
gateway -> NATS -> agent-runner -> NATS -> Response Handler -> the gateway pod holding your
socket, resolved through the shared connection store, so the reply finds you on whichever
gateway pod you are connected to.
