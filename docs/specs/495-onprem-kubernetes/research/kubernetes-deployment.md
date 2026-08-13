# Kubernetes Deployment Landscape: Baremetal + EKS Flavors, Charts, Autoscaling, Testability

Status: web research, 2026-08-07. Versions verified via web search unless marked otherwise.
Target workload: two first-party Deployments (IO/API container: FastAPI/uvicorn + output-queue
consumer, WebSocket-capable; agent-runner container: input-queue consumer) plus backing services
(Redis/Valkey, Kafka or NATS, optional Postgres).

## Executive summary

- **Standardize on Gateway API, not Ingress.** ingress-nginx retired March 2026 with no patches of
  any kind afterwards (official Kubernetes Steering + Security Response Committee statement,
  2026-01-29). A new on-prem product in 2026 should ship `Gateway`/`HTTPRoute` resources only.
- **Default gateway implementation: Envoy Gateway** on baremetal; the same Gateway API objects are
  satisfied by AWS Load Balancer Controller v3 on EKS (Gateway API GA since LBC v3.0.0). Traefik v3
  is the strongest alternative (bundled with k3s).
- **MetalLB** (v0.16.1) in L2 mode as the baremetal default (zero network-team prerequisites), BGP
  as a documented option. One `LoadBalancer` Service for the gateway only; everything else ClusterIP.
- **Charts: single umbrella chart + per-flavor values files** (`values-baremetal.yaml`,
  `values-eks.yaml`); backing services as optional, condition-gated dependencies. **Bitnami charts
  are no longer viable** (catalog paywalled/frozen behind Broadcom subscription since Sep 2025):
  use the official `valkey-helm`, official NATS chart (`nats-io/k8s`), Strimzi operator for Kafka.
- **KEDA** (v2.20.x) for queue-depth autoscaling of the agent runner (first-party Kafka-lag and
  NATS-JetStream-pending scalers); plain HPA for the IO Deployment.
- **Local/CI testing: k3s (or k3d) is the closest-to-prod baremetal simulation; kind for CI.**
  microk8s works on native Ubuntu but on macOS requires a Multipass VM **and its MetalLB addon
  does not work under Multipass on macOS**: a hard limitation for Mac-based dev.

## 1. Baremetal flavor

### MetalLB

- Current: v0.16.1 (2026-05-27).
- **L2 mode** (default recommendation): one node answers ARP/NDP per service IP; failover on node
  loss; no requirements on the customer network. Throughput of one service IP capped at one node's
  NIC: acceptable because only the gateway gets a LoadBalancer IP.
- **BGP mode**: true ECMP across nodes, requires BGP-capable routers + network-team coordination.
  FRR-based implementation in modern MetalLB. Values-file switch; document for high-throughput sites.

### Gateway: the ingress-nginx situation (decision-forcing)

- 2025-11-12: ingress-nginx entered best-effort maintenance; retirement announced for March 2026.
- 2026-01-29 (kubernetes.io official statement): after retirement, **no bug fixes, no security
  patches, no updates of any kind**. Endorsed migration paths: Gateway API or a third-party
  Ingress controller; none are drop-in.
- Gateway API current: **v1.6.0** (2026-06-30): HTTPRoute, GRPCRoute, TLSRoute, TCPRoute, UDPRoute
  all Standard channel.
- Implementations (Aug 2026): Envoy Gateway v1.8.3 (bundles Gateway API v1.5.1 CRDs; policy CRDs:
  ClientTrafficPolicy, BackendTrafficPolicy, SecurityPolicy); Traefik v3.7.10 (Gateway API v1.6.1,
  100% HTTPRoute conformance); Cilium 1.20 (couples gateway to CNI choice); Istio (heavyweight
  unless a mesh is wanted).
- **Recommendation**: Gateway API Standard channel (v1.5+ semantics), Envoy Gateway as the bundled
  default on baremetal, implementation pluggable via `gatewayClassName` in values. Traefik as the
  documented alternative for k3s-class clusters.

### WebSockets through the gateway

- HTTPRoute carries WS upgrades; Envoy enables the `websocket` upgrade type by default.
- The operational issue is **idle timeouts on long-lived agent streams**: Envoy Gateway
  `ClientTrafficPolicy.spec.timeout.http.idleTimeout`/`streamIdleTimeout` (listener-scoped);
  `BackendTrafficPolicy` for upstream timeouts. Known bug: `requestBuffer` + WebSocket upgrade
  deadlocks connections (envoyproxy/gateway #8578): never enable request buffering on WS routes.
  Prefer a dedicated listener/route for WS with a raised stream idle timeout, plus app-level
  ping/pong keepalives in the FastAPI layer.
- **No sticky sessions**: connection state is externalized (connection store), any IO pod serves any
  reconnect; session affinity only fights rolling deploys. Design for reconnect-on-redeploy.

### TLS

- cert-manager v1.21.1 (2026-07-29); first-class Gateway API integration (annotate the `Gateway`
  with `cert-manager.io/cluster-issuer`).
- On-prem default: ClusterIssuer backed by the customer's internal CA (CA/Vault/external issuers);
  ACME only when internet-reachable; self-signed bootstrap issuer for air-gapped evals.

## 2. EKS flavor

- **AWS Load Balancer Controller v3.x** (v3.2.0 current): Gateway API GA since v3.0.0. L7 routes
  (HTTPRoute/GRPCRoute) → ALB; L4 routes → NLB. Builds against Gateway API v1.5.0, aligning with
  Envoy Gateway 1.8's bundled CRDs: a shared v1.5 Standard-channel baseline works across flavors.
- **Flavor switch is values-only** because both flavors consume identical Gateway + HTTPRoute
  resources: baremetal = `gatewayClassName: envoy-gateway` + MetalLB + cert-manager; EKS =
  ALB/NLB gateway class + ACM cert ARNs + subnet/scheme annotations. Keep a legacy
  `Service type=LoadBalancer` fallback (NLB on EKS, MetalLB on baremetal) as a values option.
- WebSockets on EKS: ALB supports WS natively; `idle_timeout.timeout_seconds` (default 60s, max
  4000s) via LB-attributes annotation. NLB TCP idle timeout default 350s, configurable 60-6000s
  (prior knowledge, unverified this session).
- **Storage**: EKS: EBS CSI (gp3) for RWO (Kafka, Postgres, ClickHouse); EFS only if RWX genuinely
  needed (it isn't, for this stack). Baremetal: OpenEBS LocalPV (better product default) or
  Rancher local-path-provisioner (fine for micro-clusters). Both pin pods to nodes; replicate at
  the application layer (Kafka replication), not the storage layer. Always abstract via
  `storageClassName` in values.
- **AWS credentials**: EKS Pod Identity for new EC2-based workloads (AWS's 2026 recommendation),
  IRSA for Fargate/older clusters; never static keys on EKS. On baremetal: customer-provided
  credentials Secret (or STS via OIDC federation) behind one values block.

## 3. Helm chart conventions

- **Helm 4.0** (Nov 2025): OCI registries are the default distribution model; install-by-digest.
  Target Helm 4, keep charts Helm 3-installable during transition.
- **Recommended shape: hybrid umbrella**:
  - One umbrella chart whose first-party templates cover only the two Deployments, the
    Gateway/HTTPRoute objects, ConfigMaps/Secrets, and the KEDA ScaledObject.
  - Backing services as optional dependency subcharts gated by `condition:` flags
    (`valkey.enabled`, `nats.enabled`, `kafka.enabled`) so production customers can point at
    external/managed instances instead.
  - Per-flavor values files over a neutral `values.yaml`; templates never fork per flavor.
- **Bitnami is dead as a dependency source** (verified): after 2025-09-29 most Bitnami OCI chart
  packages moved behind the Broadcom "Bitnami Secure Images" subscription; free Debian images
  frozen into `docker.io/bitnamilegacy` (no updates since 2025-08-28). Replacements:
  - Valkey: official `valkey-io/valkey-helm` (created explicitly in response to the Bitnami
    changes). Defaulting to Valkey also sidesteps Redis licensing questions.
  - Kafka: **Strimzi operator** 1.1.0 (~June 2026; dates approximate), Kafka 4.2.x/4.3.0,
    KRaft-only.
  - NATS: official charts at `nats-io/k8s`, chart line ~2.14.x (Synadia-maintained).
- **Operator vs chart**: operators buy day-2 ops at the cost of cluster-scoped CRDs + an extra
  controller to mirror in air-gapped installs. Rule of thumb: **operator for Kafka** (Strimzi:
  plain-chart Kafka is what customers get wrong), **plain chart for Valkey and NATS** (simple
  StatefulSets), CloudNativePG or plain chart for optional Postgres.
- Footprint note: choosing NATS over Kafka removes the operator requirement entirely and shrinks
  the baremetal footprint materially (see `nats-jetstream.md` / `kafka.md`).

## 4. Autoscaling

- KEDA v2.20.2 current. Plain HPA is CPU/memory only; queue depth is the correct signal for the
  agent runner (LLM-bound work idles the CPU while requests back up).
- First-party KEDA scalers exist for Kafka consumer lag, NATS JetStream pending messages, and
  Redis lists/streams: the scaler choice tracks the queue backend selected in values.
- Scale-to-zero: KEDA drives 0↔1, HPA 1..N. Caveats for this workload: cold start (image pull +
  Python import) argues for `minReplicaCount: 1` in production; set `cooldownPeriod` long enough
  to ride out gaps between conversation turns; long-running agent executions need graceful drain
  (generous `terminationGracePeriodSeconds`, stop claiming work on SIGTERM) or scale-in kills
  in-flight runs.
- The IO Deployment scales on plain HPA (CPU/requests).

## 5. Micro-cluster testability

Versions: k3s v1.36.2+k3s1 (2026-05-27), kind v0.32.0, microk8s tracks upstream per channel.

| Option | Strengths | Weaknesses |
|---|---|---|
| **k3s / k3d** | Single <100 MB binary, production-grade, multi-node; disable bundled ServiceLB (Klipper) + Traefik to run MetalLB + Envoy Gateway for true flavor parity; k3d wraps it in Docker for macOS/CI | Bundled defaults must be disabled for parity |
| **microk8s** | One-command addons: `metallb`, `hostpath-storage`, `registry`, `observability` | macOS requires a Multipass VM, and **the MetalLB addon does not work under Multipass on macOS** (macOS network filtering); legacy `ingress` addon is EOL ingress-nginx |
| **kind** | CI standard (`helm/kind-action` + `helm/chart-testing-action`), deterministic, boots in seconds | No LoadBalancer out of the box (add cloud-provider-kind or MetalLB-over-Docker: works on Linux CI, not macOS Docker Desktop) |
| **minikube** | Best tutorials/addons | Heavier, single-node bias, not for CI |

Recommendation:

- (a) **macOS local dev**: k3d or minikube; not microk8s (VM tax + MetalLB limitation). Use
  port-forward/NodePort to reach the gateway locally.
- (b) **CI (GitHub Actions)**: kind via `helm/kind-action`, `ct lint/install`, one job per flavor
  values file; MetalLB in L2 over the Docker network when a test genuinely needs a LB IP.
- (c) **Closest-to-production baremetal simulation**: k3s on a Linux VM or small metal box, with
  ServiceLB/Traefik disabled and MetalLB + Envoy Gateway + OpenEBS LocalPV installed from our own
  chart: i.e. `values-baremetal.yaml` runs unmodified. microk8s on native Ubuntu is a close
  second (better only for snap/Ubuntu-centric teams).

## 6. Observability stack (on-prem profile)

- Metrics: **kube-prometheus-stack** chart 88.x (Prometheus operator + Prometheus + Grafana +
  node-exporter + kube-state-metrics): still the default answer.
- Logs: Grafana Loki 3.7.x vs **VictoriaLogs v1.50.0**: VictoriaLogs is GA, substantially lighter
  (single small binary + cluster mode), Grafana datasource plugin available; the pragmatic pick
  when footprint matters. Loki if the customer standardizes on the Grafana ecosystem.
- Traces: Tempo 2.9/2.10 (3.0 line emerging, GA status unverified); S3-compatible backend pairs
  with the MinIO already needed for Langfuse.
- Collection: one **OpenTelemetry Collector** (v0.158.0) as the single funnel: OTLP in from AK's
  tracing providers (Langfuse/OpenLLMetry/Logfire), fan out to Tempo/Prometheus/logs backend.
  DaemonSet (node logs) + Deployment gateway is the standard topology.
- **Langfuse self-hosted v3** (AK already supports Langfuse as a tracing provider) is heavy; treat
  as an optional profile: requires Postgres + ClickHouse ≥ 24.3 + Redis/Valkey + S3-compatible
  storage (MinIO), two app tiers (web/worker). Documented minimums total roughly **9+ CPU /
  22+ GiB for the Langfuse profile alone**. Official chart: `langfuse/langfuse-k8s`; its bundled
  single-replica subcharts are smoke-test conveniences only.

## 7. Air-gapped / private registry (brief)

- Mirror all images (app, gateway, MetalLB, KEDA, cert-manager, backing services, observability)
  into the customer registry (Harbor; zot as lighter pure-OCI alternative). Ship a
  machine-readable image manifest per release; every subchart must expose
  `global.imageRegistry`-style overrides.
- Publish charts as **OCI artifacts** in the same registry (ChartMuseum is legacy: Harbor removed
  it in 2.8); pin by digest.
- Plan for: offline Gateway API CRD installation (versioned independently of controllers),
  bootstrap CA for cert-manager, disabling phone-home/telemetry defaults in third-party charts.

## Version quick reference (2026-08-07)

| Component | Version | Note |
|---|---|---|
| MetalLB | 0.16.1 | L2 default, BGP/FRR optional |
| ingress-nginx | **EOL March 2026** | no patches post-retirement |
| Gateway API | v1.6.0 | TCP/UDPRoute now Standard |
| Envoy Gateway | v1.8.3 | bundles Gateway API v1.5.1 CRDs |
| Traefik | v3.7.10 | Gateway API v1.6.1 |
| cert-manager | v1.21.1 | Gateway API integration |
| AWS LB Controller | v3.2.0 | Gateway API GA since v3.0.0 |
| Helm | 4.0 | OCI-first |
| Strimzi | 1.1.0 (~June 2026) | Kafka 4.2.x/4.3.0, KRaft-only |
| NATS chart | ~2.14.x | nats-io/k8s |
| Valkey chart | valkey-io/valkey-helm | official, post-Bitnami |
| KEDA | 2.20.2 | 2.21 ~Sept 2026 |
| k3s / kind | v1.36.2+k3s1 / v0.32.0 | |
| kube-prometheus-stack | 88.x | |
| Loki / VictoriaLogs | 3.7.4 / v1.50.0 | |
| OTel Collector | v0.158.0 | |

Unverified / lower confidence: InGate successor's demise (inferred from omission); Strimzi exact
release dates; NATS chart exact patch version; Tempo 3.0 GA status; Helm 3 post-4.0 support
window; NLB configurable idle-timeout details.

## Sources

- https://www.kubernetes.dev/blog/2025/11/12/ingress-nginx-retirement/
- https://www.kubernetes.io/blog/2026/01/29/ingress-nginx-statement/
- https://kubernetes.io/blog/2026/08/03/gateway-api-v1-6-release/
- https://kubernetes.io/blog/2026/04/21/gateway-api-v1-5/
- https://endoflife.date/metallb
- https://gateway.envoyproxy.io/news/releases/v1.8/
- https://github.com/envoyproxy/gateway/issues/8454 / https://github.com/envoyproxy/gateway/issues/8578
- https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/gateway-api/
- https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/gateway-api/
- https://cert-manager.io/docs/releases/
- https://aws.amazon.com/blogs/networking-and-content-delivery/aws-load-balancer-controller-adds-general-availability-support-for-kubernetes-gateway-api/
- https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/gateway/gateway/
- https://helm.sh/docs/overview/ / https://www.thestack.technology/helm-4-changes-the-stack/
- https://www.chainguard.dev/supply-chain-security-101/a-practical-guide-to-migrating-helm-charts-from-bitnami
- https://valkey.io/blog/valkey-helm-chart/ / https://github.com/valkey-io/valkey-helm
- https://github.com/nats-io/k8s / https://artifacthub.io/packages/helm/nats/nats
- https://github.com/strimzi/strimzi-kafka-operator/releases
- https://keda.sh/docs/2.20/operate/cluster/ / https://endoflife.date/keda
- https://docs.k3s.io/blog/2026/05/27/K3s-1.36-release
- https://kind.sigs.k8s.io/docs/user/quick-start/
- https://microk8s.io/docs/addon-hostpath-storage / https://discuss.kubernetes.io/t/addon-metallb/11790
- https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack
- https://docs.victoriametrics.com/victorialogs/
- https://github.com/open-telemetry/opentelemetry-collector-releases/releases
- https://langfuse.com/self-hosting / https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse
- https://openebs.io/docs/3.3.x/concepts/localpv
