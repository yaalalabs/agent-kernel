# Sandbox Provider Landscape (2026)

Research date: 2026-07-14. Survey of sandbox/code-execution backends a pluggable `Sandbox`
abstraction in Agent Kernel could integrate: cloud sandbox-as-a-service (startup, platform, and
hyperscaler-native), self-hosted/OSS runtimes, and in-process/language-level options. Gathered via
parallel research streams (WebSearch/WebFetch); each section is cited inline.

**Known gap**: Google Vertex AI's code-execution offerings (Vertex AI code interpreter tool,
Agent Engine code execution) are **not researched** in this document — the dedicated research task
for this was stopped before completing. Treat "Google Vertex AI" as a placeholder needing a
follow-up pass before it's used as a citable source for design decisions. Everything else below
went through at least one completed research pass, with per-item confidence flagged where a claim
came from a secondary source rather than a primary fetch.

## Contents

- [Quick comparison](#quick-comparison)
- [A. Cloud sandbox-as-a-service](#a-cloud-sandbox-as-a-service)
  - [A1. Independent/startup providers](#a1-independentstartup-providers) — E2B, Modal, Daytona, Runloop, Morph, Scrapybara, Blaxel
  - [A2. Platform/edge providers](#a2-platformedge-providers) — Cloudflare, Vercel, Northflank, Fly.io
  - [A3. Hyperscaler-native](#a3-hyperscaler-native) — Azure Container Apps dynamic sessions, AWS Bedrock AgentCore, Google Vertex AI (gap)
- [B. Self-hosted / open-source](#b-self-hosted--open-source) — Docker/Podman, gVisor, Firecracker, Kata, microsandbox, Anthropic sandbox-runtime, bubblewrap, nsjail, Judge0, Piston
- [C. In-process / language-level](#c-in-process--language-level) — Pyodide, langchain-sandbox, wasmtime/WASI, componentize-py, Wasmer, Deno, RestrictedPython, smolagents' interpreter, PyPy sandbox, PEP 578
- [D. Cross-cutting capability matrix](#d-cross-cutting-capability-matrix)
- [E. Industry comparison posts (2025-2026)](#e-industry-comparison-posts-2025-2026)
- [F. Implications for Agent Kernel's `Sandbox` abstraction](#f-implications-for-agent-kernels-sandbox-abstraction)
- [G. Known gaps / follow-ups](#g-known-gaps--follow-ups)

---

## Quick comparison

| Provider | Category | Isolation | Python SDK | Self-hostable | Pause/resume state | Startup latency claim | License / funding |
|---|---|---|---|---|---|---|---|
| E2B | Startup cloud | Firecracker microVM | `e2b`, sync-first | Yes (infra OSS, Apache-2.0) + BYOC | FS + memory | ~150ms (unverified this pass) | Apache-2.0; $21M Series A (Jul 2025) |
| Modal Sandboxes | Startup cloud | gVisor | `modal`, sync + async twins | No (client only) | FS always; memory experimental | not stated as a number | Proprietary; $355M Series C, $4.65B valuation (May 2026) |
| Daytona | Startup cloud | Namespaces (containers) or true VM | `daytona`, sync | Yes (AGPL-3.0; core dev reportedly moved private Jun 2026, unverified) | Container: FS only; VM: FS+memory | "under 90ms" (confirmed) | AGPL-3.0; $24M Series A (Feb 2026) |
| Runloop | Startup cloud | VM (unnamed hypervisor) | `runloop_api_client`, async recommended | No | Disk only | "a few seconds" | Proprietary; $7M seed (Jul 2025) |
| Morph (MorphVM) | Startup cloud | KVM microVM (secondary-sourced) | `morphcloud`, sync | No | Full state (memory+FS) | "<250ms" snapshot/branch (confirmed) | Proprietary; $20M or $5.75M seed (conflicting) |
| Scrapybara | Startup cloud (desktop/browser) | Unconfirmed (inferred VM) | `scrapybara`, sync + async | No | Instance-level, no reusable snapshot found | "under 1 second" | Proprietary; ~$500K pre-seed (YC F24) |
| Blaxel | Startup cloud | microVM (confirmed) | `blaxel`, async-only | Partially (sandbox runtime OSS, control plane proprietary) | Full state, automatic on scale-to-zero | "under 25ms" resume (most aggressive claim) | Proprietary; $7.3M seed (2025) |
| Cloudflare Sandbox SDK | Platform/edge | Container (via Durable Object) | No (TS only) | No | Ephemeral by default; explicit backup/overlay | slow first-run (2-3 min build); steady-state unknown | Beta; part of Cloudflare Workers |
| Vercel Sandbox | Platform/edge | Firecracker microVM | **Yes** (sync `Sandbox` + async `AsyncSandbox`) | No | Persistent sandboxes auto-save/resume by default | "milliseconds" (marketing) | GA; Vercel platform |
| Northflank | Platform/edge | microVM (Kata Containers or gVisor) | No (REST/CLI/JS client) | **Yes (BYOC — customer's own VPC on AWS/GCP/Azure/Oracle)** | Unverified (marketing only) | "sub-second" / "200ms" (marketing) | Proprietary; claims 80k+ developers, $ unconfirmed |
| Fly.io Machines | Platform/edge | Firecracker (widely known, not re-confirmed this pass) | No official SDK | No | `suspend` = memory snapshot | resume "<1s"; create "low double-digit seconds" | Proprietary; long-standing GA product |
| Azure Container Apps dynamic sessions | Hyperscaler-native | Hyper-V boundary per session | No Python SDK (REST); LangChain/LlamaIndex community tools exist | No | No pause/resume; session-identifier reuse with idle-timeout | not benchmarked | Azure consumption billing |
| AWS Bedrock AgentCore Code Interpreter | Hyperscaler-native | Managed container ("sandbox environment") | boto3/AWS SDK (not a dedicated Python package) | No | Not a documented feature (session-scoped) | not benchmarked | AWS-standard Bedrock pricing |
| Google Vertex AI code execution | Hyperscaler-native | **UNRESEARCHED — see gap note above** | — | — | — | — | — |
| Docker/Podman | Self-hosted | Namespaces/cgroups (shares host kernel) | `docker`/`podman-py` | Yes | Backend-dependent | N/A | Apache-2.0 |
| gVisor | Self-hosted | User-space kernel (syscall interception) | None (OCI runtime) | Yes | N/A | N/A | Apache-2.0; ~18.9k★ |
| Firecracker | Self-hosted | KVM microVM | None (REST/Unix socket) | Yes | Snapshot/restore first-class (~125ms boot claim) | ~125ms | Apache-2.0; ~35.5k★; powers AWS Lambda/Fargate |
| Kata Containers | Self-hosted | Full VM (KVM, pluggable hypervisor) | None (OCI runtime) | Yes | N/A | N/A | Apache-2.0; ~8.3k★ |
| microsandbox | Self-hosted | libkrun microVM | `microsandbox`, async | Yes (local free forever) | Volumes/snapshots mentioned, depth unverified | "<100ms" on Apple Silicon | Apache-2.0 (local); ~6.9k★, beta |
| Anthropic sandbox-runtime | Self-hosted | bubblewrap/Seatbelt + seccomp + proxy | None (TS/CLI) | Yes | N/A | very low overhead, no VM | Apache-2.0; ~4.7k★ |
| bubblewrap | Self-hosted | Unprivileged namespaces | None (CLI) | Yes | N/A | N/A | LGPL-2.1+ (unconfirmed); 8k+★ |
| nsjail | Self-hosted | Namespaces + seccomp (Kafel) | None (CLI) | Yes | N/A | N/A | Apache-2.0 |
| Judge0 | Self-hosted | Isolate (namespaces+cgroups) via Docker Compose | None (REST) | Yes | N/A | N/A | GPL-3.0; ~4.3k★ |
| Piston | Self-hosted | Isolate-in-Docker | None (REST/WS; unofficial `pistonpy`) | Yes | N/A | N/A | MIT; ~2.8k★ |
| Pyodide | In-process | WASM VM | JS/Node API (not Python-native) | Yes (embed anywhere) | Session-lived; IDBFS for durable persistence | ~2-5s cold | MPL-2.0; ~14.7k★ |
| langchain-sandbox (PyodideSandbox) | In-process | Deno permissions + Pyodide WASM | `langchain_sandbox`, sync + async | Yes | Optional via pickled `session_bytes` | several seconds/run | MIT; **archived Jan 2026, unmaintained** |
| wasmtime-py + CPython-WASI | In-process | WASI capability sandbox, fuel-metered | `wasmtime` (embeds WASM in Python, not Python-in-WASM) | Yes | None built-in | unconfirmed | Apache-2.0; ~533★ |
| RestrictedPython | In-process | AST transform + guard hooks | `RestrictedPython` | Yes | None built-in | ~0 (compile-time) | Zope-style OSS; ~735★; **2 sandbox-escape CVEs** |
| smolagents `LocalPythonExecutor` | In-process | Custom AST walker | Built into `smolagents` | Yes | Per-agent-run only | ~0 | Apache-2.0; ~28.3k★ (smolagents); **explicitly not a security boundary** |

---

## A. Cloud sandbox-as-a-service

### A1. Independent/startup providers

#### E2B (e2b.dev)

**Isolation**: Firecracker microVMs — "a fast, secure Linux VM created on demand for your agent."
Widely cited elsewhere as Firecracker-based; current docs describe pause/resume of full
memory+filesystem state, consistent with a microVM snapshot model.
([docs](https://e2b.mintlify.app/docs.md))

**Python SDK** (`pip install e2b`, sync-first, async variant also exists):

```python
from e2b import Sandbox
sandbox = Sandbox.create()  # needs E2B_API_KEY
result = sandbox.commands.run('ls -l')
print(result.stdout)
```

Streaming:
```python
result = sandbox.commands.run(
    'echo hello; sleep 1; echo world',
    on_stdout=lambda data: print(data),
    on_stderr=lambda data: print(data),
)
```

Files:
```python
with open("path/to/local/file", "rb") as file:
    sandbox.files.write("/path/in/sandbox", file)
content = sandbox.files.read('/path/in/sandbox')
```

Packages — runtime install or baked into a custom **Template**:
```python
from e2b import Template
template = (Template().from_template("code-interpreter-v1")
            .pip_install(['cowsay']).npm_install(['cowsay']))
```

Lifecycle — a distinguishing feature: pause/resume preserves **both filesystem and in-memory
state** (running processes, loaded variables):
```python
sandbox = Sandbox.create()   # Running
sandbox.pause()               # Running -> Paused
sandbox.connect()             # Paused -> Running (resume)
sandbox.kill()                # -> Killed (terminal)
```
`create_snapshot` also exists for filesystem-only, lighter cold-boot-on-resume snapshots.
Timeouts: `Sandbox.create(timeout=12_000, secure=True)` (ms); `secure=True` requires pre-signed
URLs for upload.

**Pricing**: per-second billing, ~$0.0504/vCPU-hour + ~$0.0000045/GiB-s RAM (secondary-source
aggregation, not independently re-derived from the primary pricing page — flag for confirmation).
Free "Hobby" tier: $100 one-time credit / ~100 sandbox-hours/month, 1-hour max session, 20
concurrent sandboxes. Pro $150/month (500 hours, 24h sessions, 100 concurrent). No GPU tier.

**Self-hostable**: Yes — infra published as OSS. `e2b-dev/e2b`: ~12,968★, Apache-2.0.
`e2b-dev/infra`: ~1,244★, Apache-2.0. Also offers **BYOC**.

**Maturity**: $21M Series A (Insight Partners, Jul 2025); claims 88% of Fortune 100 have signed
up. ([blog](https://e2b.dev/blog/series-a), [VentureBeat](https://venturebeat.com/ai/how-e2b-became-essential-to-88-of-fortune-100-companies-and-raised-21-million))

**Capabilities**: arbitrary shell exec, full FS R/W, PTY/interactive terminal, SSH, cloud volumes,
custom domains, MCP server support, prebuilt Jupyter-style stateful "Code Interpreter" template,
network/secured-access controls, OTel telemetry.

---

#### Modal Sandboxes (modal.com)

**Isolation**: **gVisor**, explicitly confirmed: "Sandboxes are built on top of gVisor, a
container runtime by Google that provides strong isolation properties."
([sandbox-networking](https://modal.com/docs/guide/sandbox-networking.md))

**Python SDK** (`modal`, dual sync/async — every method has an `.aio()` twin):
```python
sb_app = modal.App.lookup("my-app", create_if_missing=True)
sb = modal.Sandbox.create(app=sb_app)
p = sb.exec("python", "-c", "print('hello')", timeout=3)
print(p.stdout.read())
for line in sb.exec("bash", "-c", "for i in {1..10}; do date +%T; sleep 0.5; done", timeout=5).stdout:
    print(line, end="")
sb.terminate()
```
Async twin uses `.aio()` on every call (`await modal.Sandbox.create.aio(...)`, etc.).

Files (v1.4+ dedicated API):
```python
sb.filesystem.write_text("Hello World!\n", "/tmp/test.txt")
contents = sb.filesystem.read_text("/tmp/test.txt")
```

Timeouts: default max lifetime **5 minutes**, configurable to 24h; separate `idle_timeout`.

Snapshots — three types: **Filesystem** (`sb.snapshot_filesystem(ttl=...)` → reusable `modal.Image`,
30-day default TTL), **Directory** (`sb.snapshot_directory(...)`, mountable into another sandbox),
**Memory** (experimental, full VM state via `_experimental_snapshot()`/`_experimental_from_snapshot()`,
7-day expiry).

**Network egress control** — unusually granular:
```python
sb = modal.Sandbox.create(..., block_network=True)                                  # full block
sb = modal.Sandbox.create(..., outbound_cidr_allowlist=["52.0.0.0/8"])              # CIDR allowlist
sb = modal.Sandbox.create(..., outbound_domain_allowlist=["api.openai.com","*.github.com"])  # domain (beta)
```
Inbound via **Tunnels** (`encrypted_ports=[8080]`) yielding a public `tunnel.url`.

**Pricing**: per-second, CPU $0.00003942/physical-core-second (1 core = 2 vCPU), $0.00000672/GiB-s
memory; region multiplier 1.25x-2.5x. GPU per-second: T4 $0.000164, A100 $0.000694, H100 $0.001097,
B200 $0.001736 (secondary-source aggregation).

**Self-hostable**: No (fully managed). Client SDK `modal-labs/modal-client` OSS (Apache-2.0, ~493★).

**Maturity**: Series C $355M (May 2026, Redpoint/General Catalyst), $4.65B valuation; ARR grew from
~$60M (Sep) to ~$300M. ([TechCrunch](https://techcrunch.com/2026/02/11/ai-inference-startup-modal-labs-in-talks-to-raise-at-2-5b-valuation-sources-say/), [SiliconANGLE](https://siliconangle.com/2026/05/21/serverless-ai-infrastructure-startup-modal-labs-seals-355m-funding-round/))

**Capabilities**: arbitrary command exec, full FS API, GPU sandboxes, granular egress control,
inbound tunnels, stdout/stderr streaming, warm pools, documented stateful code-interpreter pattern.

---

#### Daytona (daytona.io)

**Isolation**: Two families — (a) **Container sandboxes**: Linux namespaces per instance on
multi-tenant runners (namespace/cgroup isolation, not a hardware VM boundary); (b) **VM sandboxes**
(Linux + Windows, beta): true VMs supporting pause/resume and fork.

**Python SDK** (`pip install daytona`, sync-first):
```python
from daytona import Daytona, DaytonaConfig
daytona = Daytona(DaytonaConfig(api_key="YOUR_API_KEY"))
sandbox = daytona.create()
response = sandbox.process.code_run('print("Hello World")')
print(response.result)
```
Custom resources:
```python
from daytona import CreateSandboxFromImageParams, Resources
sandbox = daytona.create(CreateSandboxFromImageParams(image="ubuntu:22.04", resources=Resources(cpu=2, memory=4, disk=8)))
```
Defaults 1 vCPU/1GiB/3GiB disk; org max 4 vCPU/8GiB/10GiB (standard tier).

Lifecycle:
```python
sandbox.start()
sandbox.pause()   # VM sandboxes only — freezes VM, preserves FS+memory, stops CPU billing
                   # container sandboxes: pause NOT supported; use stop() (FS only)
forked = sandbox._experimental_fork(name="my-forked-sandbox")   # VM sandboxes, experimental
```
Ephemeral + auto-lifecycle:
```python
sandbox = daytona.create(CreateSandboxFromImageParams(ephemeral=True, auto_stop_interval=5))
```

**Persistence**: "Snapshots" = reusable base-image templates (Docker-image-like), distinct from a
live pause/resume snapshot. Volumes = persistent S3-backed storage, independent of sandbox lifecycle.

**Startup latency**: **"under 90ms from code to execution"** — stated directly on the docs
homepage (confirmed, not secondary-sourced).

**Pricing**: $0.0504/vCPU-hour, $0.0162/GiB-hour memory, $0.000108/GiB-hour storage (secondary-
source aggregation — notably identical vCPU-hour rate to E2B's reported figure, worth independently
re-verifying both). Free tier: $200 compute credit + 5GB storage, no card required.

**Self-hostable**: Yes — `daytonaio/daytona`, ~72,213★, **AGPL-3.0**. **Flagged, unverified via
secondary source only**: as of June 2026, Daytona's core development reportedly moved to a private
codebase, with the public repo receiving no further updates/fixes/releases (still usable/forkable
under AGPL-3.0). Verify directly against repo commit activity before relying on self-host viability.

**Maturity**: Series A $24M (Feb 2026, FirstMark Capital; Datadog + Figma Ventures strategic),
$125M valuation. Prior: $5M seed (Jun 2024), $2M pre-seed (Nov 2023). ~$31M total raised.
([PRNewswire](https://www.prnewswire.com/news-releases/daytona-raises-24m-series-a-to-give-every-agent-a-computer-302680740.html))

**Capabilities**: arbitrary shell/code exec, full FS ops, Git ops, computer-use, LSP support,
PTY/web terminal, SSH/VNC, preview URLs with custom-domain proxy + auth, log streaming, GPU
sandboxes (up to 16 vCPU/192GB/512GB disk), "linked sandboxes" (parent-child DNS-addressable
network), VPN connections, webhooks, MCP integration.

---

#### Runloop (runloop.ai)

**Isolation**: "Virtual machine technology" per Runloop's own docs — hypervisor not named.
(A competitor's blog claims "custom bare-metal hypervisor" with sub-25ms resume — **unverified,
non-neutral source**, do not treat as Runloop's own claim.)

**Python SDK** (`runloop_api_client`, sync **and** async; Runloop's docs recommend async):
```python
import asyncio
from runloop_api_client import AsyncRunloopSDK
runloop = AsyncRunloopSDK()  # reads RUNLOOP_API_KEY

async def run_example():
    devbox = await runloop.devbox.create()
    result = await devbox.cmd.exec(command="echo 'Runloop!!'")
    print(await result.stdout())
    await devbox.shutdown()
asyncio.run(run_example())
```
Long-running/background:
```python
command = await devbox.cmd.exec_async("HOST=0.0.0.0; npx run http-server")
await command.kill()   # streaming via output=lambda x: print(x)
```
Files:
```python
await devbox.file.write(file_path="/home/user/main.py", contents='print("Hello, World!")')
contents = await devbox.file.read(file_path="/home/user/test_results.txt")
await devbox.file.upload(file_path="...", file=open('large_data.txt', 'rb'))
```
Lifecycle — default max lifetime **1 hour**; suspend/resume preserves **disk only**, not memory:
```python
devbox = await runloop.devbox.create(launch_parameters={"keep_alive_time_seconds": 1800})
devbox = await runloop.devbox.create(launch_parameters={
    "lifecycle": {"after_idle": {"idle_time_seconds": 1800, "on_idle": "suspend"}}})
await devbox.suspend(); await devbox.await_suspended()
await devbox.resume(); await devbox.await_running()
```
Network egress via **Network Policies**:
```python
policy = await runloop.network_policies.create(name="restricted-policy", allow_all=False,
    allowed_hostnames=["github.com", "api.openai.com"])
devbox = await runloop.devbox.create(launch_parameters={"network_policy_id": policy.id})
```

**Pricing**: $0.108/CPU-hour, $0.0252/GB-hour memory; $50 free credit, no card required; suspended
devboxes incur zero compute charge (secondary-source aggregation).

**Self-hostable**: No indication found. `runloopai/api-client-python`: ~26★, MIT.

**Maturity**: $7M seed (Jul 2025, The General Partnership + Blank Ventures); ~12-person team,
alumni from Google/Stripe/Scale AI/Vercel.

**Capabilities**: blocking + non-blocking shell exec, full file R/W, PTY sessions, named/stateful
shells, SSH, tunnels, storage objects with presigned URLs, Docker-in-Docker, GPU option,
Dockerfile-based "Blueprints," "Axon" event stream for turn-based agent interaction (Agent Client
Protocol + Claude JSON bridges), built-in SWE-Bench-style eval framework, AI Gateway/MCP Hub.

---

#### Morph / MorphVM (morph.so) — "Infinibranch"

**Isolation**: KVM-based microVMs (secondary-sourced; not named in Morph's own fetched docs).
Headline differentiator: **Infinibranch** — snapshot/branch/restore entire environments in
**<250ms**, forking a running VM into N parallel copies with branch-level access control.

**Python SDK** (`morphcloud`, sync):
```python
from morphcloud.api import MorphCloudClient
client = MorphCloudClient()
snapshot = client.snapshots.create(image_id="morphvm-minimal", vcpus=1, memory=1024, disk_size=10000)
instance = client.instances.start(snapshot_id=snapshot.id)
instance.wait_until_ready()
result = instance.exec(command="echo 'Hello, Morph Cloud!'")
instance.stop()
```
Pause/resume — **preserves full state incl. in-flight processes**:
```python
instance = client.instances.get(instance_id="morphvm_abc123")
instance.pause()
instance.resume()   # restores exact state, "all processes and memory state intact"
```
Snapshot/branch (core Infinibranch primitive):
```python
new_snapshot = instance.snapshot()
snapshot, clones = instance.branch(count=3)
```
HTTP service exposure:
```python
service_url = instance.expose_http_service("my-service", 8080)  # auth_mode="api_key" optional
```
No dedicated package-install method — implied via `exec("pip install ...")` or baked into the
base snapshot image.

**Pricing**: credit unit **MCU** (1 vCPU-hour + 4GB RAM-hours + 16GB disk-hours, OR 5TB
snapshot-hours). Developer Plan: 300 free MCUs, up to 64 vCPU/256GB RAM/1024GB storage instances.
No granular $/unit rate found on the fetched plans page.

**Self-hostable**: No core OSS found; thin client SDKs only (`morph-labs/morph-python-sdk`: ~3★,
Apache-2.0).

**Maturity**: Founded 2023 (Jesse Han, ex-OpenAI). **Funding figures conflict between sources** —
"$20M seed" (Finsmes, Mar 2024) vs. "$5.75M seed led by Khosla Ventures" (Sep 2024) — unresolved,
may be the same round reported differently or a follow-on; flag for direct confirmation.

**Capabilities**: shell exec, FS R/W (incl. FUSE), HTTP service exposure with API-key auth, SSH
(shareable, no-API-key sharing), reboot, wake-on-request, snapshot TTL, metadata tagging, separate
"Morph EFS" shared-filesystem product, reverse-tunnel. No dedicated computer-use/desktop product
found (unlike Scrapybara/E2B Desktop) — likely absent, not confirmed absent.

---

#### Scrapybara (scrapybara.com) — desktop/browser computer-use specialist

**Isolation**: Not documented by Scrapybara itself; inferred VM-based given full remote
Ubuntu/Windows/Browser desktop instances with sub-1s spin-up claims — **inference, not a fact**.

**Python SDK** (`scrapybara`, both sync `Scrapybara` and async `AsyncScrapybara`):
```python
from scrapybara import Scrapybara
client = Scrapybara(api_key="your_api_key")
instance = client.start_ubuntu(timeout_hours=1)   # or start_browser(...), start_windows(...)
stream_url = instance.get_stream_url().stream_url   # live view/interact URL
result = instance.bash(command="ls -la")
instance.computer(action="move_mouse", coordinates=[200, 100])
instance.computer(action="click_mouse", button="left")
instance.computer(action="type_text", text="Hello, world!")
instance.stop()
```
Code execution — **stateful, Jupyter-style** (distinct from one-shot `bash`):
```python
result = instance.code.execute(code="print('Hello!')", kernel_name="python3")
notebook = instance.notebook.create(name="my_notebook", kernel_name="python3")
cell = instance.notebook.add_cell(notebook_id=notebook.id, type="code", content="print('Hello!')")
result = instance.notebook.execute_cell(notebook_id=notebook.id, cell_id=cell.id)
```
Upload / pause / resume:
```python
client.instance.upload(instance_id="instance_id", file=..., path="path")
client.instance.pause(instance_id="instance_id")
client.instance.resume(instance_id="instance_id")
```
Browser control (CDP/Playwright + persistent auth states):
```python
from playwright.sync_api import sync_playwright
cdp_url = instance.browser.start().cdp_url
browser = sync_playwright().start().chromium.connect_over_cdp(cdp_url)
auth_state_id = instance.browser.save_auth(name="default").auth_state_id
instance.browser.authenticate(auth_state_id=auth_state_id)
```
Agentic loop — Act SDK (model-agnostic computer-use harness):
```python
from scrapybara.tools import BashTool, ComputerTool, EditTool
from scrapybara.openai import OpenAI, UBUNTU_SYSTEM_PROMPT
response = client.act(model=OpenAI(), tools=[BashTool(instance), ComputerTool(instance), EditTool(instance)],
    system=UBUNTU_SYSTEM_PROMPT, prompt="Go to the top link on Hacker News")
```

**Persistence**: instance-level pause/resume exists; no explicit "snapshot to reusable image"
primitive found (unlike E2B/Morph/Modal) — likely thinner on this axis, not fully confirmed absent.

**Startup latency**: "Instantly spin up ... under 1 second" (confirmed).

**Pricing**: plans from $29/month (100 compute hours, 25 concurrent), Pro $99/month, Enterprise
custom (secondary-source aggregation, no free tier found).

**Self-hostable**: No. `scrapybara/scrapybara-python`: ~73★.

**Maturity**: Y Combinator F24; ~$500K pre-seed — smallest/earliest-stage of the seven surveyed.

**Capabilities**: full Ubuntu/Windows/Browser remote desktops with mouse/keyboard/screenshot
control, bash exec, stateful Jupyter-kernel code exec, file upload, live stream URL for
human-in-the-loop viewing, Playwright/CDP browser control with saved auth states, Act SDK
supporting OpenAI CUA and Anthropic Claude Computer Use out of the box.

---

#### Blaxel (blaxel.ai)

**Isolation**: **microVM-based**, explicitly documented — "lightweight, sandboxed virtual
machines with sub-25ms cold starts," code runs "with no risk of escaping."

**Python SDK** (`blaxel`, **async-only**, via `blaxel.core.SandboxInstance`; credentials only via
`BL_WORKSPACE`/`BL_API_KEY` env vars or CLI login, not constructor args):
```python
from blaxel.core import SandboxInstance
sandbox = await SandboxInstance.create_if_not_exists({
    "name": "my-sandbox", "image": "blaxel/base-image:latest",
    "memory": 4096, "storageMb": 102400,
    "ports": [{"target": 3000, "protocol": "HTTP"}], "region": "us-pdx-1"})
process = await sandbox.process.exec({"command": "echo 'Hello, World!'"})
```
Filesystem:
```python
await sandbox.fs.mkdir("/blaxel/app/uploads")
await sandbox.fs.write("/blaxel/app/config.json", "{}")
content = await sandbox.fs.read("/blaxel/app/config.json")
result = await sandbox.fs.find(path="/app", type="file", patterns=["*.md", "*.html"])
```
No dedicated package-install primitive — via `process.exec({"command": "pip install ..."})` or a
custom Dockerfile-based Template.

**Lifecycle — standout feature: fully automatic active/standby scale-to-zero**, not manual
pause/kill calls:
- **Active**: billed for memory + storage while a connection is open (CPU bundled/free).
- **Standby**: auto-triggered ~15s after last connection closes (or 15-min idle); auto-snapshots
  full state (FS + running processes); resumes from standby in **under 25ms** on reconnect; no
  memory charge while in standby. Network connections (DB pools, HTTP keep-alives) are **not**
  preserved and will time out.
- **Deletion**: separate, governed by configurable expiration policies.

**Persistence**: automatic full-state snapshot on every scale-to-zero transition (not a manual
API call). Also supports attachable **Volumes** and **Agent Drive** (distributed FS mountable
concurrently across multiple sandboxes/agents with label-based ACLs).

**Startup latency**: **"under 25ms"** resume from standby — most aggressive claim of all seven
providers surveyed.

**Pricing**: billed for memory + storage while active (CPU bundled); no granular published
per-GB-hour rate found in fetched docs pages.

**Self-hostable**: Partially — `blaxel-ai/sandbox` (~23★) with a published OpenAPI spec looks
self-hostable in isolation; the full managed control plane (scheduling, scale-to-zero
orchestration, billing) appears proprietary. Needs closer study to confirm the actual self-host
boundary.

**Maturity**: $7.3M seed (2025, First Round Capital + YC + Liquid 2 + Multimodal), closed one
month after a 6-founder team graduated YC Spring 2025. Claims 7.5M+ requests/day.

**Capabilities**: arbitrary shell exec, full FS API, preview URLs (real-time app rendering,
optional auth/custom domains), explicit port exposure, egress proxy with domain allow/denylist +
secrets injection (credentials never touch sandbox code), dedicated egress gateways (predictable
outbound IPs), log streaming, **built-in MCP server per sandbox**, cron-style schedules,
client-side session tokens (scoped, time-limited, for frontend-direct calls), Dockerfile-based
Templates, colocation with Blaxel's serverless "Agents Hosting" product.

---

### A2. Platform/edge providers

#### Cloudflare Sandbox SDK / Cloudflare Containers

**Isolation**: Linux containers wrapped by a Durable Object (one per sandbox instance) — not a
microVM model like Vercel/Northflank.

**SDK**: `@cloudflare/sandbox` npm package — **TypeScript/JavaScript only**, no Python SDK/client.
Python appears only as a *runtime you can execute code in* (a `sandbox:0.7.0-python` image
variant), not as an SDK language.

```typescript
import { getSandbox } from '@cloudflare/sandbox';
const sandbox = getSandbox(env.Sandbox, 'my-sandbox');
const result = await sandbox.exec('python3 -c "print(2 + 2)"');
await sandbox.writeFile('/workspace/hello.txt', 'Hello, Sandbox!');
const tunnel = await sandbox.tunnels.get(8080);
console.log(tunnel.url); // https://random-words-here.trycloudflare.com
```

**Capabilities**: command exec with streaming output, file R/W, `inotify` file watching, a
Jupyter-like code interpreter for Python/JS with persistent state, WebSocket browser terminal,
preview URLs/tunnels ("URLs do not survive a container restart"), S3-compatible bucket mounting,
backup/snapshot + overlay restore, "sessions" (isolated execution contexts inside one sandbox).

**Lifecycle**: instantiates on first reference by ID; sleeps after inactivity (default 10 min,
configurable via `sleepAfter`) — **on sleep, all files/processes/shell state are lost** unless
backed up or mounted externally; `keepAlive: true` sends a heartbeat every 30s.

**Startup latency**: GitHub README warns first run builds the Docker container (2-3 minutes);
steady-state cold-start not found.

**Pricing**: based on the underlying Containers platform. Requires Workers Paid plan ($5/mo base).
Memory $0.0000025/additional GiB-s (25 GiB-hours/mo included); CPU $0.000020/additional vCPU-s
(375 vCPU-min/mo included); Disk $0.00000007/additional GB-s (200 GB-hours/mo included). Instance
sizes `lite` (1/16 vCPU, 256MiB) to `standard-4` (4 vCPU, 12GiB). Egress $0.025-0.05/GB by region.
Billed in 10ms increments.

**Self-hostable**: No.

**Maturity**: v0.12.3 (Jul 1, 2026), explicitly **Beta** ("APIs may change before v1.0"), ~1.1k★,
107 releases.

---

#### Vercel Sandbox

**Isolation**: Firecracker microVM, one per sandbox, own filesystem/network, Amazon Linux 2023,
full root access. Confirmed: "Each sandbox runs in a secure Firecracker microVM."

**Python SDK — notably official**, unlike Cloudflare (`uv add vercel`, part of the `vercel` PyPI
package), both sync (`Sandbox`) and async (`AsyncSandbox`):

```python
# Sync
from vercel.sandbox import Sandbox
with Sandbox.create(timeout=300_000, runtime="python3.13") as sandbox:
    result = sandbox.run_command("python3", args=["-c", "print(2+2)"])
    print(result.stdout())

# Async interactive shell
import asyncio
from vercel.sandbox import AsyncSandbox
async def main():
    sandbox = await AsyncSandbox.create(interactive=True, timeout=300_000)
    try:
        await sandbox.shell(["/bin/bash"])
    finally:
        await sandbox.stop()
asyncio.run(main())

# Files
sandbox.write_files([{"path": "hello.py", "content": b"print('hi')"}])
data = sandbox.read_file("hello.py")
sandbox.download_file(remote_path="out.txt", local_path="./out.txt")

# Detached command + streaming logs
cmd = sandbox.run_command_detached("npm", args=["install"])
for line in cmd.logs():
    print(line)
result = cmd.wait()

# Snapshot + resume
snap = sandbox.snapshot(expiration=0)
# later: Sandbox.create(source=SnapshotSource(snap.snapshot_id))

# Ports / preview URL
sandbox = Sandbox.create(ports=[3000])
print(sandbox.domain(3000))

sandbox.extend_timeout(600_000)
sandbox.stop(blocking=True)
```

**Capabilities**: arbitrary shell exec (`run_command` blocking, `run_command_detached` for
streaming/long-running, `sudo` supported), full FS R/W (`read_file`, `write_files`,
`download_file`, `iter_file` chunked streaming), PTY interactive shell (async-only), preview URLs
via `.domain(port)` (up to 15 open ports), network egress policy (`NetworkPolicy`:
allow-all/deny-all/custom subnet+rule, mutable post-creation), snapshot/restore, beta "Drives"
for persistent storage across runs, Git/tarball/snapshot as initial source.

**Lifecycle**: `PENDING → RUNNING → STOPPING → STOPPED`, plus `ABORTED`/`FAILED`/`SNAPSHOTTING`.
`Sandbox.get(sandbox_id)` reconnects to an existing sandbox from another process. Persistent
sandboxes auto-save state on stop and resume by default.

**Startup latency**: "Sandboxes start in milliseconds" (marketing, not independently benchmarked).

**Max duration**: Hobby 45 min; Pro/Enterprise 24 hours (default timeout 5 min, adjustable).

**Pricing**:

| Metric | Hobby (free) | Pro/Enterprise |
|---|---|---|
| Active CPU | 5 hrs/mo | $0.128/hour |
| Provisioned Memory | 420 GB-hrs/mo | $0.0212/GB-hour |
| Sandbox Creations | 5,000/mo | $0.60/1M |
| Data Transfer | 20 GB/mo | $0.15/GB |
| Snapshot Storage | 15 GB lifetime | $0.08/GB-month |
| Concurrent sandboxes | 10 | 2,000 |
| Max runtime | 45 min | 24 hours |

Resource caps: Hobby max 4 vCPU/8GB, Pro max 8 vCPU/16GB, Enterprise max 32 vCPU/64GB; fixed 32GB
ephemeral NVMe disk on all plans. Only one region currently (`iad1`). Example: 5-min "AI code
validation" run (2 vCPU/4GB) ≈ $0.03; a 2-hr long task (8 vCPU/16GB) ≈ $2.73.

**Self-hostable**: No.

**Maturity**: GA product, dedicated pricing page, CLI, JS+Python SDKs, public GitHub repo. Auth
via Vercel OIDC token (automatic in Vercel deployments) or access tokens for external use.

---

#### Northflank (sandboxes for AI agents)

**Caveat**: docs URLs guessed for this stream both 404'd; the following is from the product
marketing page and API-intro docs only — treat exec-API shape, pause/resume mechanics, and
snapshot semantics as unconfirmed pending a direct docs fetch.

**Isolation**: microVMs — "Every workload runs in its own microVM with Kata Containers or gVisor."

**SDK**: **No Python SDK** (confirmed via docs fetch) — REST API, CLI, and a JavaScript client are
offered.

**Capabilities**: parallel worker spawning/background jobs, code execution for codegen, GPU
support (H100s, fractional GPU), persistent volumes (4GB-64TB, multi-read-write), S3-compatible/
MinIO object storage, stateful DB addons (Redis/Postgres/MySQL/MongoDB), built-in CI/CD,
observability/cost tracking.

**Lifecycle/persistence**: marketing claims flexible ephemeral-or-persistent modes with "no forced
time limits" (seconds to weeks) and autoscaling — exact API calls not verified.

**Startup latency**: marketing claims "sub-second cold starts... boot a microVM in under a
second," homepage banner claims "microVM 200ms" — not independently verified.

**Pricing**: CPU $0.01667/vCPU-hour; GPU $2.74/hour all-in (H100, marketing page). No free-tier
specifics found.

**Self-hostable / BYOC**: **Yes** — deploys into the customer's own VPC on AWS, GCP, Azure, or
Oracle Cloud, multi-region. Real differentiator vs. Cloudflare/Vercel/Fly (single-platform-locked).

**Maturity**: named customers/logos: Sentry, Pebblebed, Cedana, ChaiDiscovery, CoreWeave,
Directus, GovTech. Claims "80k+ developers in production," "130B+ requests processed," "millions
of microVMs monthly since 2021."

---

#### Fly.io Machines

**Isolation**: Firecracker microVMs is the well-known public architecture, but this was **not
independently re-confirmed** in the specific pages fetched this session — flag as widely
documented elsewhere but not re-verified in-session.

**SDK**: No official Python SDK found. Access via REST API (Machines API) and `flyctl` CLI.

**REST API surface**:
```
POST   /v1/apps/{app_name}/machines                          # create
POST   /v1/apps/{app_name}/machines/{machine_id}/start
POST   /v1/apps/{app_name}/machines/{machine_id}/stop          # params: signal, timeout
POST   /v1/apps/{app_name}/machines/{machine_id}/suspend       # memory snapshot for fast restart
DELETE /v1/apps/{app_name}/machines/{machine_id}               # ?force=true
GET    /v1/apps/{app_name}/machines/{machine_id}/wait?state=started|stopped|suspended|destroyed
GET    /v1/apps/{app_name}/machines/{machine_id}
POST   /v1/apps/{app_name}/machines/{machine_id}/cordon | /uncordon
```
Notably: **no explicit "exec" endpoint appeared** in the fetched reference — Fly historically
exposes exec via `flyctl machine exec` CLI or a separate path not confirmed this session.

**Lifecycle states**: `created → started → stopped`, plus `suspended` (memory snapshot) →
`destroyed`. `skip_launch` creates without booting (warm image cache); `lease_ttl` for exclusive
locking during startup.

**Persistence**: optional attached Volumes for durable storage; otherwise ephemeral, reset on
every startup.

**Startup latency**: starting an already-stopped machine "usually well under a second"; initial
creation (image fetch + FS setup) "low double-digit seconds."

**Pricing**: **not obtained** in this research pass (pricing-page fetch failed) — no figures
should be assumed.

**Self-hostable**: No.

**Maturity**: long-standing GA product, used both for general app hosting and historically as an
AI-sandbox substrate by several code-execution startups.

---

### A3. Hyperscaler-native

#### Azure Container Apps dynamic sessions (code interpreter sessions)

Per the LCD/capability-matrix research pass (see [Section D](#d-cross-cutting-capability-matrix)):

- **Isolation**: Hyper-V boundary per session.
- **Model**: **stateful by session identifier** — a session-identifier string reuses/creates a
  session; state persists until idle-timeout.
- **Shell**: **code-only** — POST to `/executions`, no general shell endpoint (contrast with E2B/
  Modal/Daytona's full shell access).
- **Files**: REST — `POST files` (multipart, 128MB limit), `GET files/{name}/content`,
  `GET files/{name}` (metadata), `GET files` (list) — all scoped to `/mnt/data`.
- **Network**: not documented in fetched pages (managed/opaque network posture).
- **Ports/preview URLs**: none — session is not network-addressable beyond the management API.
- **Pause/resume/snapshot**: none — sessions have an idle-timeout and are deleted; reuse is by
  session-identifier, not restore-from-snapshot.
- **Packages**: preinstalled only (NumPy, pandas, scikit-learn listed); no arbitrary package
  install at session time documented.
- **Timeouts**: per-execution cap of **220 seconds**; session idle-timeout configured at the
  session-pool level.
- **Concurrency**: session **pool** has a configurable max-concurrent-sessions setting.
- **Python integration**: no official Python SDK; community tools exist —
  `langchain_azure_dynamic_sessions.tools.sessions.SessionsPythonREPLTool`/`SessionsBashTool`
  (LangChain) and `AzureCodeInterpreterToolSpec` (LlamaIndex) both wrap the REST session API,
  auth via a `TokenProvider`-style pluggable credential.
- **Pricing**: consumption-based container-apps billing (session duration).

**Design-relevant takeaway**: this service intentionally gives up general shell access and
pause/resume/snapshot in exchange for a simple, session-identifier-addressed, POST-and-get-JSON
contract with a strict per-call time cap — a structurally different shape from the VM/container
sandboxes above, and one AK's minimal core interface must still accommodate.

---

#### AWS Bedrock AgentCore Code Interpreter

Per the LCD/capability-matrix research pass:

- **Isolation**: managed container ("sandbox environment").
- **Model**: stateful within a `code_session`; `clearContext` flag lets you explicitly reset vs.
  carry state forward.
- **Shell**: Python/JS/TS code execution + a **separate** terminal-command capability via
  execution-role/S3 integration — not a general shell in the E2B/Modal sense.
- **Files**: inline upload up to 100MB; via S3 + terminal commands up to 5GB.
- **Streaming**: "code execution results are returned and processed as streams."
- **Network**: **network modes** exist (sandbox/public/VPC per the original research brief);
  exact enum values not independently re-verified this session. **Security note**: independent
  security researchers have publicly demonstrated DNS-exfiltration/credential-extraction issues
  against AgentCore's *default* network mode (per rywalker.com research cited in Section E) —
  relevant to AK's network-egress-control design regardless of which backend is chosen.
- **Response envelope**: structured — `content[]`, `structuredContent.{stdout, stderr, exitCode,
  executionTime}`.
- **Timeouts**: default **15 minutes**, extendable up to **8 hours** — the longest max duration of
  any provider surveyed in this document.
- **Packages**: pre-built runtimes "with common libraries pre-installed" per language; less clear
  on arbitrary runtime pip installs.
- **Pricing**: AWS-standard Bedrock pricing (not itemized in fetched material).
- **Python integration**: via boto3/AWS SDK, not a dedicated `bedrock-agentcore` Python package
  confirmed in this pass.

---

#### Google Vertex AI code execution — GAP, NOT RESEARCHED

The dedicated research task for Vertex AI's code-execution offerings (the Gemini/Vertex code
interpreter tool, Vertex AI Agent Engine code execution, and any GKE-based "Agent Sandbox" —
noting `kubernetes-sigs/agent-sandbox` is a CNCF/K8s SIG project, **not** Google-proprietary, and
must not be conflated with a Google-managed product) was stopped before it produced results.

**Do not cite anything about Google's offering from this document** — it needs a dedicated
follow-up research pass before being used in design decisions. See
[Section G](#g-known-gaps--follow-ups).

---

## B. Self-hosted / open-source

### Docker/Podman (containers as code-exec backend) — partial coverage

**Isolation**: Linux namespaces (pid/net/mnt/uts/ipc/user) + cgroups for resource limits; shares
host kernel — not a strong security boundary alone ("a kernel escape is part of the threat
model"). Platform: Linux native; macOS/Windows via VM (Docker Desktop, Podman machine).

**Python SDK**: `docker-py` (package `docker`), sync API, `docker.from_env()` then
`client.containers.run(image, command, ...)`. Podman has `podman-py` with a Docker-compatible API
surface (talks to the Podman REST socket) — not independently re-verified with a fresh code
snippet this pass; standard/stable library knowledge.

**Two integration patterns observed**: "agent runs inside the sandbox, communicates over network"
vs. "agent runs on host, drives sandbox as a tool"; also a "protocol-based abstraction with
swappable backends" pattern (in-memory for tests, real FS for dev, Docker for prod).

**License**: Docker Engine/Moby — Apache-2.0. Podman — Apache-2.0.

**Operational burden**: needs a Linux host (or Docker Desktop/Podman machine VM on macOS/Windows)
with the daemon/socket running; no special hardware requirement (no KVM needed for the container
layer itself, only for the VM layer on non-Linux hosts).

Docker's own newer offering: **Docker Sandboxes**, purpose-built for coding agents
([docs.docker.com/ai/sandboxes](https://docs.docker.com/ai/sandboxes/)).

---

### gVisor (runsc)

**Isolation**: user-space application kernel ("Sentry") that intercepts application syscalls and
re-implements ~200 Linux syscalls in memory-safe Go, rather than passing them to the host kernel —
"provides many security benefits of VMs while maintaining the lower resource footprint, fast
startup, and flexibility of regular userspace applications." Integrates as `runsc`, an
OCI-compliant runtime.

**Platform**: Linux 4.14.77+, x86_64 and ARM64; limited macOS support ("testing only," not a real
deployment target).

**SDK**: none — swap-in OCI runtime invoked via Docker (`--runtime=runsc`) or Kubernetes
RuntimeClass.

**License**: Apache-2.0. **Maturity**: ~18.9k★. Built by Google; used in Google Cloud services
(Cloud Run, GKE Sandbox, App Engine per general knowledge, not re-confirmed this pass).

**Capabilities**: full process/FS/network syscall interception, drop-in under existing container
tooling; adds syscall-boundary overhead for syscall-heavy workloads.

**Operational burden**: Linux host with `runsc` registered as a container runtime; no KVM required
— lower infra burden than Firecracker/Kata since it slots under existing Docker/K8s.

---

### Firecracker microVMs

**Isolation**: KVM-based hardware virtualization; production deployments use a **jailer** process
applying cgroup/namespace isolation and dropping privileges before launching the VM, plus
thread-specific seccomp filters.

**Platform**: Linux + KVM only. x86_64 (Intel Cascade Lake through Sapphire/Granite Rapids; AMD
Milan/Genoa) and ARM64 (Graviton 2/3/4); specific host kernel versions required.

**SDK**: none — configured via a REST API over a Unix socket (OpenAPI spec) controlling vCPUs,
memory, network interfaces, block devices, VM lifecycle. Integrated via `firecracker-containerd`
or Kata Containers rather than used raw in most agent stacks.

**Persistence/snapshots**: first-class — AWS Lambda SnapStart uses Firecracker snapshots of
initialized execution environments to skip cold-start init; one dev writeup claims sandboxes
booting in **28ms** using snapshots.

**Startup latency**: ~125ms microVM boot claim, described as "essentially fixed" cost in the
Lambda cold-start breakdown.

**License**: Apache-2.0. **Maturity**: ~35.5k★ — largest of the VM-isolation projects surveyed.
Built at AWS; powers **AWS Lambda and Fargate**; widely known (not re-verified this pass) to
underlie E2B/Fly.io-style sandbox infra.

**Operational burden**: bare-metal or nested-virt-capable Linux hosts with KVM access — heaviest
infra requirement of the self-hosted group (can't run inside a plain container or non-KVM VM).

---

### Kata Containers

**Isolation**: full lightweight VM per container/pod, hardware-virtualized via KVM, guest kernel
isolating the workload at the hardware level. Pluggable hypervisors: QEMU, Cloud Hypervisor,
Firecracker, Dragonball.

**Platform**: 64-bit Linux (x86_64, aarch64, ppc64le, s390x) with virtualization extensions;
nested virtualization required if running inside a VM.

**SDK**: none — OCI runtime via containerd/CRI-O using the shimv2 interface (one shim per pod),
same integration pattern as gVisor.

**License**: Apache-2.0. **Maturity**: ~8.3k★, OpenInfra Foundation governance. Latest release
v3.32.0 (Jun 2026, approximate).

**Capabilities**: strongest isolation of the "drop-in OCI runtime" group (real VM boundary vs.
gVisor's syscall interception), at VM-level overhead cost.

**Operational burden**: Linux + KVM + containerd/CRI-O with the kata shim — more infra than
gVisor, less than raw Firecracker (Kata handles VM lifecycle/networking plumbing).

---

### microsandbox (zerocore-ai)

**Isolation**: microVMs via **libkrun** (not Firecracker/QEMU) — "Every agent deserves its own
machine."

**Platform**: macOS (Apple Silicon only), Linux (KVM-enabled), Windows (WHP-enabled) — the only
surveyed microVM tech with an out-of-the-box macOS story (via libkrun, no nested Linux needed).

**Python SDK**: `microsandbox` on PyPI (v0.6.6), fully async. Bundles the `msb` runtime +
`libkrunfw` directly in the wheel — no separate server process for basic use.
```python
import asyncio
from microsandbox import Sandbox

async def main():
    sandbox = await Sandbox.create("my-sandbox", image="python", cpus=1, memory=512)
    output = await sandbox.exec("python", ["-c", "print('Hello from a microVM!')"])
    print(output.stdout_text)
    await sandbox.stop()
asyncio.run(main())
```
Alternate shell-style form:
```python
async with await Sandbox.create("python-readme", image="alpine", replace=True) as sandbox:
    output = await sandbox.shell("echo 'Hello from microsandbox!'")
    print(output.stdout_text.strip())
```

**Persistence/snapshot**: volumes, secrets, metrics, logs, snapshots, SSH/SFTP access called out in
the SDK surface — feature depth not independently verified beyond the README.

**Startup latency**: claims "average boot times under 100ms" on Apple Silicon.

**License**: **Apache-2.0** for the local/self-hosted runtime; hosted cloud platform stated to
carry a separate future commercial license (TBD). "Running locally or on your own infrastructure
is free, forever."

**Maturity**: ~6.9k★, beta status, explicit breaking-changes warning; ~653 commits/49 releases —
active but young.

**Operational burden**: lowest of the microVM options — SDK spawns VMs as child processes directly
(bundled libkrun), no separate daemon/server needed for the basic path; an `msb server` mode also
exists for shared/self-hosted deployment.

---

### Anthropic sandbox-runtime (srt)

**Isolation**: OS-level, no container/VM. **Linux**: bubblewrap for namespace isolation +
network-namespace removal + seccomp-BPF (blocks raw AF_UNIX socket creation, forcing all traffic
through the proxy). **macOS**: native `sandbox-exec` with dynamically generated Seatbelt profiles
specifying allowed read/write paths and restricting network to designated localhost ports.

**Platform**: Linux and macOS — the only two of the self-hosted technologies here with genuine
native macOS support without a VM.

**Invocation**: npm package `@anthropic-ai/sandbox-runtime`, CLI `srt`, e.g.
`srt "curl anthropic.com"`.

**Network egress control**: secure-by-default/deny-by-default. All traffic routed through
host-side HTTP and SOCKS5 proxy servers enforcing `network.allowedDomains`/`deniedDomains`
allowlists; Linux talks over Unix domain sockets, macOS over specific localhost ports.

**Filesystem control**: `allowRead`/`denyRead`/`allowWrite`/`denyWrite`.

**Config**: JSON at `~/.srt-settings.json` by default.

**Known limitation** (self-documented): broad domain allowlists can still create exfiltration
vectors; Linux also has a weaker "nested sandbox" mode trading security for Docker compatibility.

**SDK**: no Python SDK — TypeScript/Node library + CLI only.

**License**: Apache-2.0. **Maturity**: ~4.7k★ — an Anthropic-experimental project hardening Claude
Code's own execution. See also the fuller writeup in
[framework-abstractions.md §7](framework-abstractions.md) covering the reusable `SandboxManager`/
`SandboxViolationStore` library API and Claude Code's own use of it.

**Operational burden**: very low — no daemon, no VM, no KVM; installs bubblewrap (Linux) or uses
macOS's built-in sandbox-exec. Lightest-weight option in this survey for basic FS+network
confinement, but **not** kernel-boundary isolation like gVisor/Firecracker/Kata (still shares the
host kernel/process table, just restricts FS/network).

---

### bubblewrap

**Isolation**: unprivileged user namespaces (no root required) + mount namespace with explicit
bind mounts to build a minimal filesystem view + optional PID/IPC/net/UTS namespace unsharing +
seccomp filters + `PR_SET_NO_NEW_PRIVS` to block setuid escalation.

**Platform**: Linux only.

```bash
bwrap --ro-bind /usr /usr --symlink usr/lib64 /lib64 \
  --proc /proc --dev /dev --unshare-pid --new-session bash
```

**License**: GitHub's own detector reported "unknown" during this fetch (LICENSE + COPYING files
present) — commonly documented elsewhere as LGPL-2.1+; treat as unconfirmed and verify directly if
it matters for AK's license posture.

**Maturity**: 8,000+★. Used by **Flatpak**, rpm-ostree's unprivileged mode, and as the Linux
backend for **Anthropic's srt** (above).

**Capabilities**: no built-in seccomp policy generation (caller supplies filters), no resource-
limit/cgroup layer itself (pairs with systemd/cgroups), no network egress filtering by itself
(only namespace on/off) — a low-level primitive, not a full sandboxing product.

**Noted risks** (self-documented): sandbox strength depends entirely on the flags passed; TIOCSTI
injection and D-Bus-socket-mount-based privilege escalation are called out as concerns.

**Operational burden**: minimal — single static-ish binary, packaged by every major Linux distro,
no daemon.

---

### nsjail — partial coverage

**Isolation**: Linux namespaces (UTS/mount/PID/IPC/NET/USER/cgroup/time per one source), cgroups,
rlimits, and seccomp-BPF syscall filters using the **Kafel** BPF policy language (Google's own DSL
for seccomp filters).

**Platform**: Linux only. **License**: Apache-2.0.

**Maturity/users**: a Google project; described by comparison sources as "config-file driven
(protobuf), designed for server workloads and CTF infrastructure" — heavier-weight and less
universally packaged than bubblewrap. Named as the sandbox **Windmill** (self-hosted workflow
engine) uses for Python/Go execution.

**Capabilities**: can run as a one-shot process jail or a standalone listening service (accepting
connections and jailing each), unlike bubblewrap's "wrap this one command" scope.

**Not yet verified**: exact GitHub star count, precise seccomp architecture details, FS/network-
egress granularity, language bindings — recommend a direct fetch of `github.com/google/nsjail` if
precise numbers become decision-relevant.

---

### Judge0

**Isolation**: **Isolate** (the IOI competitive-programming sandbox) — Linux namespaces + cgroups
+ chroot-style confinement per submission — orchestrated inside Docker Compose alongside a
Ruby-on-Rails API, PostgreSQL, Redis, and background workers for async execution.

**Platform**: Linux (Docker-based deployment).

**API**: REST, not a Python SDK:
```bash
curl -H "Content-Type: application/json" \
  -d '{"language_id": 109, "source_code": "print(...)", "stdin": "..."}' \
  "https://ce.judge0.com/submissions?wait=true"
```
Supports sync (`?wait=true`) and async + webhook callback modes.

**License**: **GPL-3.0** — copyleft, and no separate commercial/dual-license option found in this
pass; worth a second, more careful check if AK is considering embedding vs. calling it as a
separate hosted service, since GPL implications differ by integration shape.

**Maturity**: ~4.3k★, 896 forks. Latest tagged release cited as v1.13.1 (Apr 2024, likely stale —
worth reverifying). Used in competitive programming, e-learning, recruitment/assessment
platforms; cited as a code-execution tool pluggable into LLM agent workflows (e.g., a Kestra
integration).

**Capabilities**: 90+ language support (marketing figure), custom compiler options, CLI args,
time/memory limits, additional-files/multi-file submissions, base64 I/O, webhooks.

**Operational burden**: heaviest of the "execution engine" pair (Judge0/Piston) — full multi-
service stack (Rails + Postgres + Redis + workers + Isolate) via Docker Compose.

---

### Piston (engineer-man)

**Isolation**: "Isolate inside Docker" — Linux namespaces + chroot + a distinct unprivileged Linux
user per submission + cgroups for resource limiting.

**Platform**: Linux (Docker container), requires **cgroup v2**.

**API**: REST + WebSocket, no official Python SDK (community `pistonpy` on PyPI). Endpoints:
`GET /api/v2/runtimes`, `POST /api/v2/execute`, `WS /api/v2/connect` (interactive/streaming).
```json
{"language": "js", "version": "15.10.0",
 "files": [{"name": "code.js", "content": "console.log('test')"}],
 "args": ["1", "2", "3"], "run_timeout": 3000, "run_memory_limit": -1}
```

**License**: MIT — notably more permissive than Judge0's GPL-3.0.

**Maturity**: ~2.8k★. Used by EMKC (Engineer Man's coding challenges), the Engineer Man Discord
bot (reported across 4,100+ servers), 200+ direct integrations per the repo.

**Capabilities**: 70+ language runtimes, network disabled by default inside execution containers,
fork-bomb resistance (max 256 processes), max 2048 open files, default 3s CPU/wall timeout,
1024-char output cap, automatic per-submission cleanup, real streaming via WebSocket (Judge0
doesn't offer this).

**Operational burden**: single Docker container + docker-compose, lighter than Judge0 (no
separate DB/queue dependency) but needs cgroup v2 explicitly enabled.

---

## C. In-process / language-level

### Pyodide (core)

CPython compiled to WebAssembly via Emscripten, for browsers and Node.js. Created by Michael
Droettboom at Mozilla (2018); now community-governed.

**Isolation**: entire CPython interpreter inside a WASM VM. No ambient host filesystem/network
access — only through the JS↔Python FFI and Emscripten's virtual filesystem, unless explicitly
wired up.

**API** (Node.js and browser): `loadPyodide()` → `pyodide` object; `pyodide.runPython("...")`
executes code, returns the last expression's value; `pyodide.loadPackage(...)`/
`micropip.install(...)` for packages.

**Filesystem virtualization**: Emscripten virtual FS, default `MEMFS` (in-memory, non-persistent).
Alternatives: `NODEFS` (mount a real Node.js directory), `IDBFS` (browser IndexedDB persistence),
`PROXYFS`, `WORKERFS`.
```js
pyodide.FS.mount(pyodide.FS.filesystems.NODEFS, { root: "." }, "/mnt");
pyodide.runPython("import os; print(os.listdir('/mnt'))");
```

**Packages**: pure-Python wheels from PyPI install directly via micropip. A curated set of
packages with C/C++/Rust extensions has been specially ported (NumPy, pandas, SciPy, Matplotlib,
scikit-learn, cryptography, PyYAML, regex, etc.) — arbitrary compiled wheels do **not** work.

**Performance/startup**: cold load ≈ 4-5s (6.4MB download) on first page load; cached reload ≈ 2s;
some embeddings report 12-15s (fresh iframe instance). No GPU/CUDA path.

**License**: MPL-2.0. **Maturity**: ~14.7k★, active, BrowserStack-sponsored CI.

**Hard limits**: no native/compiled arbitrary wheels; no GPU; no real sockets in-browser
(fetch/CORS-bound); single-threaded by default.

---

### langchain-sandbox / `PyodideSandbox` (Pyodide + Deno)

**Status**: **archived January 14, 2026, no longer maintained.** Maintainers now recommend
accessing code execution through sandbox APIs or LLM provider APIs instead. Still directly
relevant as the reference implementation of the Pyodide+Deno pattern — smolagents' `WasmExecutor`
(v1.20.0) builds on the same stack.

**Architecture**: `pyodide-sandbox-js` (Deno/TypeScript core booting Pyodide) + `sandbox-py`
(Python wrapper, `PyodideSandbox`, shells out to a Deno subprocess).

**Isolation**: Deno enforces the outer permission boundary (no file/net/env access unless
granted); Pyodide/WASM provides inner interpreter isolation. Two layers stacked.

```python
from langchain_sandbox import PyodideSandbox
sandbox = PyodideSandbox(allow_net=True)   # allow_net needed for micropip installs
result = await sandbox.execute("import numpy as np\nx = np.array([1, 2, 3])\nprint(x)")
```

**Persistence/state**: stateless by default. `stateful=True` returns `session_bytes` +
`session_metadata` (pickled interpreter state) passed into the next `.execute()` call to
continue a "session." Explicit security warning: **never unpickle `session_bytes` from an
untrusted source**. Plugs into LangGraph via `PyodideSandboxTool`.

**Security caveats**: guarantees depend entirely on the Deno permission flags passed through;
scope `allow_net` to specific domains to avoid SSRF.

**Startup latency**: "several seconds" per run (Pyodide init dominated).

**Hard limits**: no filesystem access/persistence from inside sandboxed code; networking must go
through `httpx.AsyncClient` (no `requests` — needs real sockets unavailable in WASM).

**License**: MIT. **Maturity**: ~241★, last PyPI release `0.0.6` (May 21, 2025), Python ≥3.10,
requires Deno installed separately.

---

### wasmtime-py + CPython-on-WASI (VMware, componentize-py)

**Important distinction**: `wasmtime-py` embeds Wasmtime *inside* Python (calling WASM modules
from a Python host) — it is not itself "Python running in WASM." Sandboxing *Python code*
separately needs CPython compiled to `wasm32-wasi`, which VMware's project provides.

**wasmtime-py**: `pip install wasmtime`. Python 3.9+, x86_64/arm64, Win/Mac/Linux. Apache-2.0,
Bytecode Alliance project, ~533★.
```python
from wasmtime import Store, Module, Instance, Func, FuncType
store = Store()
module = Module(store.engine, "(module ...)")
instance = Instance(store, module, [Func(store, FuncType([], []), say_hello)])
```

**CPython on WASI** (VMware `webassembly-language-runtimes`, "python.wasm"): prebuilt `python.wasm`
binary + `python311.zip` stdlib archive, run via Wasmtime CLI with explicit directory preopens:
```
wasmtime run --mapdir /::$PWD bin/python-3.11.1.wasm -- -c "import sys; ..."
```
`PYTHONPATH` must include the mapped `python311.zip`. **pip largely doesn't work** — WASI
(preview1) lacks full socket support.

**Sandboxing pattern** (Simon Willison's approach, `wasmtime-py` + `python.wasm`): Engine
configured for fuel metering (instruction-count based CPU cap) — a bare `print()` burns ≈230M
fuel units, so loop-heavy code exhausts a 400M budget and traps. This is the mechanism standing in
for a CPU/instruction-count limit (WASI has no wall-clock timeout primitive). `WasiConfig` sets
`preopen_dir(".", "/")` — only this directory is visible (capability-based).

**componentize-py** (Bytecode Alliance, Apache-2.0, ~267★/46 forks, v0.25.0): converts a Python
app + WIT interface definitions into a standalone `.wasm` component, runnable via `wasmtime`.
Limitation: imports resolved only at build time — dynamic/runtime imports must appear at module
top level; native C extensions remain a major compatibility barrier.

**Isolation overall**: WASI is capability-based — no ambient FS/network authority; only explicitly
preopened directories visible; no arbitrary syscalls.

**Hard limits**: no general networking (no sockets in WASI preview1), no native/compiled packages
beyond what's baked into the wasm build, no `subprocess`/shell.

**Startup/latency**: no confirmed number found; plausibly lighter than browser-hosted Pyodide
(no JS engine layer) but unverified — open gap.

---

### Wasmer + RustPython (brief, lower confidence)

Smaller/community projects (`wasm-py-sandbox` on PyPI, `jimkring/python-sandbox-wasm`) pair
**Wasmer** with **RustPython** compiled to `wasm32-wasi` — RustPython provides no sandboxing
itself; the WASI runtime (via Wasmer) supplies the same capability-based isolation described
above. One source claims Wasmer "can run Python server-side on WASM including native modules like
gevent and SQLAlchemy" — **not independently verified against Wasmer's own docs**, flag as
unconfirmed. No adoption/maturity signal comparable to Pyodide or wasmtime-py found.

---

### Deno subprocess isolation (permissions model)

**Model**: "secure by default" — zero access to filesystem, network, env, or subprocess execution
unless the invoker explicitly grants it via flags: `--allow-read[=paths]`, `--allow-write[=paths]`,
`--allow-net[=hosts]`, `--allow-env[=vars]`, `--allow-run[=cmds]`, `--allow-ffi`. `--deny-*` flags
carve exceptions out of a broad allow (e.g. `--allow-read --deny-read=/etc`).

**Critical caveats** (the two ways this model breaks):
- `--allow-run`: subprocesses execute **outside** Deno's permission enforcement entirely.
  `--allow-run=deno` is explicitly dangerous — sandboxed code could spawn a new Deno process with
  `--allow-all` and fully escape.
- `--allow-ffi`: loaded native libraries run as machine code, outside JS-level permission checks —
  effectively full native syscall access regardless of other flags.

**Role in agent sandboxing**: exactly the mechanism `langchain-sandbox`'s `PyodideSandbox` relies
on — spawns `pyodide-sandbox-js` as a Deno subprocess, and whatever flags the Python wrapper
passes through become the actual security boundary. The guarantee is only as strong as the flag
set chosen by the integrator.

**Gap noted**: no built-in Deno primitive for CPU-time or memory ceilings found; resource
exhaustion protection needs an outer layer (OS cgroups/ulimits, container limits).

---

### RestrictedPython (Zope Foundation)

**Mechanism**: **AST-level transformation**, not a runtime sandbox. `compile_restricted()` rewrites
the AST at compile time so attribute access, item access/assignment, iteration, and printing are
routed through guard hooks the host application supplies (`_getattr_`, `_getitem_`, `_write_`,
`_getiter_`, etc.). `import` is blocked by default.

```python
from RestrictedPython import compile_restricted, safe_globals
source_code = "def example():\n    return 'Hello World!'"
loc = {}
byte_code = compile_restricted(source_code, '<inline>', 'exec')
exec(byte_code, safe_globals, loc)
loc['example']()
```
`safe_globals` = `{'__builtins__': safe_builtins}`, a curated builtins dict. Attempting
`import os; os.listdir('/')` raises `ImportError: __import__ not found` under the default policy.

**License**: present in repo (BSD-derivative per Zope conventions). **Maturity**: ~735★, 53
tagged releases, Zope Foundation maintained. Supports **CPython 3.10-3.14 only** — explicitly
excludes PyPy and other implementations.

**Persistence/state**: none built in — compile-time AST guard, not a session/runtime.

**Explicit limitations and CVEs**: the project's own docs state bluntly: **"RestrictedPython is
not a sandbox system or a secured environment, but it helps to define a trusted environment and
execute untrusted code inside of it."** Does **not** restrict timing attacks, memory consumption,
or CPU usage.

Two sandbox-escape CVEs on record:
- **CVE-2023-37271**: stack frames reachable from inside generators/generator expressions;
  untrusted code could grab the current frame and walk up the call stack to reach unrestricted
  interpreter context. Affected 3.4.2 through 5.3a1.dev0; fixed in **6.1/5.3**.
- **CVE-2025-22153**: type-confusion bug in `try/except*` (PEP 654 exception-group) handling let
  attackers bypass the sandbox. Affected 6.0 through <8.0 on Python 3.11-3.13.2; CVSS 3.1 base
  score **7.9 (High)**; fixed in **8.0** by disallowing `try/except*` and removing
  `ExceptionGroup` from `safe_builtins`.

**Real-world usage**: Zope/Plone "Python Scripts" and similar CMS/plugin-script fields — no
evidence found that LangChain, CrewAI, AutoGen, LlamaIndex, or smolagents use RestrictedPython as
their code-exec guard; smolagents built something different instead (below).

---

### smolagents' `LocalPythonExecutor` (custom, not RestrictedPython)

smolagents (Hugging Face; Apache-2.0; ~28.3k★; v1.26.0) explicitly did **not** adopt
RestrictedPython — built a from-scratch AST-walking interpreter instead:

Evaluates the AST operation-by-operation with custom rules: imports disallowed unless explicitly
authorized (`additional_authorized_imports=["numpy", ...]`, wildcard submodule support like
`numpy.*`); submodule access individually gated even for authorized top-level packages (blocks
`random._os` even though `random` is allowed); a hard cap on total elementary operations executed
(guards infinite loops); anything not explicitly implemented raises `InterpreterError`.

```python
from smolagents.local_python_executor import LocalPythonExecutor
custom_executor = LocalPythonExecutor(["numpy"])
custom_executor("import os; os.system('echo Bad command')")
# >>> InterpreterError: Import of os is not allowed. Authorized imports are: [...]
custom_executor("while True: pass")
# >>> InterpreterError: Maximum number of 1000000 iterations in While loop exceeded
```

**Official, explicit disclaimer**: *"LocalPythonExecutor provides best-effort mitigations only and
is not a security boundary."* Not for untrusted code — docs push toward remote sandboxed executors
(`executor_type="e2b"|"docker"|"modal"|"blaxel"`, and v1.20.0+'s Pyodide+Deno-based `WasmExecutor`).
See [framework-abstractions.md §1](framework-abstractions.md) for the full executor-interface
writeup.

---

### Other notable in-process options

**PyPy sandbox** — stalled/prototype. PyPy's own docs call the current implementation "the old,
unmaintained version"; a rewrite exists only in unfinished branches. Almost no extension modules
function under it. **Not viable for production agent sandboxing today.**

**CPython PEP 578 audit hooks** (`sys.addaudithook`/`sys.audit`, Python 3.8+) — visibility into
runtime events (file opens, imports, exec/eval, socket connects), so a hook can log or raise to
abort an operation. **Explicitly not a sandboxing mechanism** per the PEP itself and an open
CPython issue (#87604) — hooks exist for observability, not a security boundary; code paths that
don't trigger an audited event bypass them entirely. Useful as defense-in-depth logging around
another sandbox, not as the sandbox itself.

**Monkey-patched builtins / restricted-globals-dict** (DIY anti-pattern) — stripping
`__builtins__` or blacklisting `eval`/`exec`/`__import__` from the globals dict. Widely documented
as trivially escapable — even with `__builtins__` removed, introspection chains such as
`().__class__.__bases__[0].__subclasses__()` let attacker code enumerate every live class
(including file/subprocess-capable ones) without ever needing `import`. Considered obsolete/
insecure; superseded by RestrictedPython (still weak) or full WASM/VM/container isolation.

**Overall in-process takeaway**: every option trades off along the same axis — WASM-based
approaches (Pyodide, wasmtime/WASI, Wasmer) give the strongest process-level isolation (no
ambient syscalls) at the cost of startup latency, packaging restrictions, and little/no real
networking; AST-level approaches (RestrictedPython, smolagents' interpreter) are fast and
stateful-friendly but explicitly disclaim being a security boundary and have a real CVE history
(RestrictedPython) or an explicit "not a security boundary" warning (smolagents); Deno's
permission flags are a solid coarse-grained gate but only as strong as the flags chosen, and two
of them (`--allow-run`, `--allow-ffi`) can fully unwind the sandbox if granted to untrusted code.

---

## D. Cross-cutting capability matrix

| Dimension | E2B | Modal (Sandbox) | Daytona | Azure Container Apps Dynamic Sessions | AWS Bedrock AgentCore Code Interpreter | Docker (self-hosted / llm-sandbox) | Wasm (Pyodide+Deno) |
|---|---|---|---|---|---|---|---|
| **Isolation tech** | Firecracker microVM, dedicated kernel | gVisor (syscall-interception container) | OCI/Docker container, shared host kernel (VM sandboxes also available) | Hyper-V boundary per session | Managed container ("sandbox environments") | Namespaces/cgroups (as strong as host config) | In-process WASM runtime, no OS-level isolation |
| **Stateful REPL vs stateless exec** | Stateful (`run_code` = Jupyter-like kernel); persists across calls in one sandbox | Stateless per `exec()` call by default; sandbox object persists across execs | Stateful `process.code_run` (per-sandbox interpreter); also raw `exec()` | **Stateful by session identifier** — reuses/creates a session; persists until idle-timeout | Stateful within a `code_session`; `clearContext` flag lets you explicitly reset vs. carry state forward | Depends on wrapper — one session = one container, state persists across `run()` calls | `stateful=True` round-trips pickled `session_bytes`/`session_metadata` between calls — "client-held" state |
| **Arbitrary shell vs code-only** | Full shell **and** code exec | Full shell (arbitrary entrypoint) | Full shell **and** code | **Code-only** — POST to `/executions`, no general shell endpoint | Python/JS/TS code + **separate** terminal-command capability via execution-role/S3, not a general shell | Full shell | Code-only (Python subset via Pyodide) |
| **Streaming stdout** | Yes | Yes — iterate `p.stdout` line-by-line | Not explicitly documented (implies buffered) | Streamed per response schema; metrics via response headers | Yes — "results are returned and processed as streams" | Backend-dependent | No (single blocking call) |
| **File upload/download** | `sandbox.files` read/write/list | Modal `Volume`/mounted paths, not per-call upload API | `sandbox.fs.upload_file/download_file/list_files` | REST: `POST files` (multipart, 128MB limit), `GET files/{name}/content`, list, metadata | Inline upload up to 100MB; via S3 + terminal commands up to 5GB | `copy_to_runtime`/`copy_from_runtime` | Not supported — explicit limitation |
| **Network egress policy/allowlists** | Yes — `denyOut`/`allowOut` CIDR; allow takes precedence over deny | Yes — CIDR + domain allowlist (TLS SNI inspection on 443); `block_network` to disable | Yes — CIDR allowlist (5-10 blocks, IPv4 only) or `networkBlockAll` | Not documented (opaque network posture) | **Network modes** exist; researchers have demonstrated DNS-exfiltration/credential-extraction issues in the *default* mode | Fully user-controlled | N/A unless `allow_net=True`, then unrestricted within sandbox's own outbound path |
| **Exposing ports/preview URLs** | Yes | Yes — Probes + tunnels | Yes — preview links + SSH | No | Not primary use case | User-managed | No |
| **Pause/resume/snapshot** | Yes (beta) — pause preserves FS **and memory**; ~4s/GB pause, ~1s resume, retained up to 30 days | FS snapshots; lifecycle Created→Scheduled→Started→Ready→Finished, no memory-snapshot pause | Rich lifecycle: start/stop/pause/resume (VM sandboxes only), archive (containers only), cold vs hot (memory) snapshot | No pause/resume — idle-timeout + delete; reuse by session-identifier | Not documented as a feature (session-scoped, long-duration instead) | Backend-dependent; no built-in snapshot | No (ephemeral per call) |
| **Package installation** | Runtime `pip install` or prebuilt Templates | Prebuilt `modal.Image` (declarative, cached layers) is primary | Snapshots (prebuilt images) as primary model, or ad hoc install | Preinstalled only; no arbitrary install at session time documented | Pre-built runtimes "with common libraries pre-installed"; less clear on arbitrary installs | Dockerfile-baked or `libraries=[...]` at run time | `micropip` at runtime (requires `allow_net=True`) |
| **Rich results (images/dataframes)** | Rich — image outputs captured from `run_code` logs | Plain stdout/stderr by default | Plain by default | Rich implied (data-science stack preinstalled) | Structured — `content[]`, `structuredContent` | Rich via artifact-capture wrappers | Plain stdout/stderr + returned result value |
| **Timeouts/auto-termination** | Configurable timeout + `set_timeout()` | Default 5 min, configurable to 24h; separate idle_timeout | `auto_stop_interval` + `auto_delete_interval` | Per-execution cap of **220 seconds** | Default **15 minutes**, extendable to **8 hours** | User-managed | Multi-second startup itself a ceiling |
| **Concurrency limits** | ~20 concurrent on free tier | Serverless queueing, no small fixed cap | Configurable via session-pool setting | Session pool has configurable max | Not documented | User/infra-managed | Bounded by host process/VM limits |
| **Pricing model shape** | Free credits then $150/mo Pro + per-second | ~$250/mo + usage; per-second GPU billing | Usage-based, ~$0.067/hr/sandbox, GPU sandboxes available | Consumption-based container-apps billing | AWS-standard Bedrock pricing | Infra cost only | Free (client/edge compute) |
| **License/self-hostable** | Apache-2.0, not self-hostable (managed only, BYOC option) | Proprietary, not self-hostable | **AGPL-3.0**, self-hostable | N/A (Azure-managed only) | N/A (AWS-managed only) | Fully self-hosted by construction | Fully local/embeddable |

**Key structural takeaway**: the "code-interpreter-style" services (Azure Dynamic Sessions, Bedrock
AgentCore) intentionally give up general shell access and pause/resume/snapshot for a much
simpler, session-identifier-addressed, POST-and-get-JSON-back contract with strict per-call time
caps. The "full VM/container" services (E2B, Modal, Daytona) converge on shell exec + code exec +
files + network-allowlist + some snapshot mechanism, but disagree on exactly which lifecycle verbs
exist (`pause` vs `archive` vs nothing) and whether snapshot includes memory. **A minimal LCD
`execute(command) -> {stdout, stderr, exit_code}` is satisfiable by every backend surveyed,
including the code-interpreter-style ones** (model `execute` as "run this code," treat "shell" as
just another `language`). Anything above that (files, network policy, pause/resume, ports) needs
to be optional capability surface, not a required method — several backends genuinely cannot
implement pause/resume (Azure, Bedrock, Wasm) or ports (Azure, Bedrock, Wasm) at all.

---

## E. Industry comparison posts (2025-2026)

Blog-post-level comparative sources found during research; useful for cross-checking claims and
for the economic framing they add (none independently re-verified beyond what's cited inline):

- **[E2B vs Daytona: Sandbox Comparison for Platform Engineers](https://www.zenml.io/blog/e2b-vs-daytona)** (ZenML) —
  E2B ~150ms cold start/8 vCPU max/8192 MiB max/20 free concurrent/Apache-2.0; Daytona sub-90ms
  creation/4 vCPU documented max/GPU support/AGPL-3.0. Frames the choice as: need
  **memory-snapshot** semantics → E2B; need **policy-driven long-lived** sandboxes (days/weeks) +
  GPU → Daytona. Flags the Apache-2.0 vs AGPL-3.0 license difference as a real factor for teams
  embedding the SDK.

- **[AI Agent Sandboxes Compared](https://rywalker.com/research/ai-agent-sandboxes)** (Ry Walker
  Research) — the broadest survey found, **19 platforms**: E2B, Daytona, Modal, Sprites, Vercel
  Sandbox, Cloudflare Sandbox SDK, AWS AgentCore, Google Agent Sandbox (i.e.
  `kubernetes-sigs/agent-sandbox`), NVIDIA OpenShell, Blaxel, Northflank, OpenSandbox, Runloop,
  CodeSandbox SDK, Microsandbox, AIO Sandbox, ComputeSDK, Quilt, Zeroboot. Notable data points:
  E2B "1B+ sandboxes started, used by 94% of Fortune 100"; Modal "$4.65B valuation"; Daytona
  "72.5K★, $24M Series A." Central thesis, directly relevant to AK's RBAC requirement:
  **"sandboxed is a spectrum, not a checkbox"** — cites security research demonstrating
  DNS-exfiltration and credential-extraction against AWS AgentCore's *default* network mode, and
  concludes the ephemeral-vs-persistent debate has "resolved" because all major platforms now
  offer snapshot/checkpoint regardless of original design philosophy.

- **[E2B Alternatives: Best Sandbox Environments for 2026](https://blaxel.ai/blog/e2b-alternatives-sandbox-environments)**
  (Blaxel) — compares Blaxel, Modal, Daytona, CodeSandbox, Fly.io on isolation architecture,
  resume-from-standby latency, max standby duration, cold-start time, SDK languages, agent
  co-hosting, compliance. Numbers: Blaxel <25ms resume/indefinite standby/~200-600ms cold start;
  Modal ~1s cold start/7-day standby; Daytona sub-90ms cold start/30-day auto-archive; CodeSandbox
  0.5-2s resume/2-7 day standby; Fly.io hundreds-of-ms resume. (Note: a competitor's self-comparison
  — read Blaxel's own numbers generously, others' skeptically.)

- **[Daytona vs Modal: comparing AI code execution sandboxes in 2026](https://northflank.com/blog/daytona-vs-modal)**
  (Northflank) — frames the real difference as environment/lifecycle design philosophy
  (inactivity-driven automation for Daytona vs. timeout-bounded sessions with explicit network
  locks for Modal) rather than raw capability gaps.

- **[Sandboxed Code Execution for AI Agents in 2026: E2B vs Modal vs Daytona](https://agentmarketcap.ai/blog/2026/04/10/sandboxed-code-execution-ai-agents-e2b-modal-daytona)**
  (AgentMarketCap) — cold start E2B ~150ms/Modal sub-second/Daytona 27-90ms; GPU only on Modal;
  max session E2B 24h/Daytona "unlimited"; Computer Use only on Daytona; open-source: Daytona
  yes/E2B partial/Modal no; self-hosted: only Daytona. Gives an economic inflection point:
  **under 1M daily executions, use a managed service; self-hosting becomes economical above ~10M
  daily executions.**

- Also surfaced, not deep-fetched: [particula.tech Modal vs E2B vs Daytona vs Vercel
  Sandbox](https://particula.tech/blog/modal-vs-e2b-vs-daytona-vs-vercel-sandbox-ai-code-execution),
  [mcp.directory Cloudflare vs Modal vs E2B vs Daytona
  2026](https://mcp.directory/blog/cloudflare-sandbox-vs-modal-vs-e2b-vs-daytona-2026), [Spheron:
  E2B/Daytona/Firecracker on GPU
  cloud](https://www.spheron.network/blog/ai-agent-code-execution-sandbox-e2b-daytona-firecracker/)
  — all confirm the same five-ish axes (isolation tech, cold start, persistence, network policy,
  pricing) have become the industry-standard comparison template by mid-2026.

---

## F. Implications for Agent Kernel's `Sandbox` abstraction

1. **A single required method is sufficient and precedented.** deepagents' `execute()`,
   llm-sandbox's `run()`/`execute_command()`, and Google ADK's `execute_code()` all converge on
   one required verb — everything else (files, network policy, snapshots, ports) should be
   optional capability surface, because Azure Dynamic Sessions and Bedrock AgentCore *structurally
   cannot* implement shell/ports/snapshot, yet both are important first-class backends per AK's
   own scope (cloud-provider-native row). See [framework-abstractions.md §Synthesis](framework-abstractions.md)
   for the full cross-framework confirmation of this pattern.

2. **State handling has three genuinely different shapes** in the wild: server-held
   session-by-identifier (Azure, Bedrock, E2B/Daytona/Modal), client-held serialized state
   (langchain-sandbox's `session_bytes`), and no state at all (Wasm per-call). AK's interface
   needs to pick one canonical model and let backends without native support simulate it.

3. **None of the surveyed providers or frameworks model AK's two RBAC identity modes**
   (agent-own vs. user-assumed identity) as part of the sandbox interface itself — confirmed
   independently by both this provider survey and the framework-abstractions survey as a genuine
   AK differentiator, not something to copy from prior art. The closest analogues are Azure's
   Entra-token auth (bearer token scoped to a session pool + role assignment) and Bedrock
   AgentCore's per-session network modes — both backend-specific bolt-ons, not abstracted.

4. **"Sandboxed is a spectrum, not a checkbox"** (Ry Walker Research's framing, Section E) — AK's
   design should surface isolation strength as a queryable/declared property of each backend
   (kernel-shared namespace vs. syscall-interception vs. microVM vs. WASM), not just a binary
   "is it sandboxed." This maps onto the `SandboxCapabilities`-flags recommendation in
   [framework-abstractions.md](framework-abstractions.md).

5. **Network egress control is universally present among the serious backends** (E2B, Modal,
   Daytona, Runloop, Anthropic srt) but with incompatible shapes (CIDR-only, domain-allowlist,
   deny/allow precedence rules differ). This is exactly the kind of capability that deserves a
   normalized optional interface rather than being left as backend-specific kwargs, given its
   direct relevance to the RBAC/permission-boundary requirement.

6. **Economic framing matters for "first built-in backends" scoping** (Section E's "under 1M/day
   → managed, over 10M/day → self-host" inflection point, and OpenHands' retreat from maintaining
   third-party runtimes in-tree per framework-abstractions.md §8a) — favor a small number of
   deeply-supported first-party backends (one strong cloud SaaS, Docker/Podman self-hosted, and
   the AWS/Azure cloud-native options aligned with AK's existing deployment adapters) over trying
   to ship many shallowly-supported ones.

---

## G. Known gaps / follow-ups

Before treating this document as final for design purposes:

1. **Google Vertex AI code execution — completely unresearched.** The dedicated task for this
   was killed before producing results. Needs a fresh pass covering: the Gemini/Vertex code
   interpreter tool, Vertex AI Agent Engine code execution, and any GKE-based Google-managed
   "agent sandbox" offering (distinct from the community `kubernetes-sigs/agent-sandbox` CRD
   project, which **is** covered — see `framework-abstractions.md` §1.10 for that one).
2. **Northflank** — exec-API shape, exact pause/resume mechanics, and snapshot semantics are
   unconfirmed; the docs URLs tried both 404'd. Needs a fresh docs-URL discovery pass.
3. **Fly.io Machines pricing** — not obtained in any research pass; page fetch failed both times
   it was attempted. No figures should be assumed until this is fetched directly.
4. **E2B and Daytona per-vCPU-hour pricing** — both came back as an identical $0.0504/vCPU-hour
   from secondary-source aggregation rather than a direct fetch of each pricing page; worth
   independently confirming these aren't cross-contaminated.
5. **Daytona's "core development moved private" claim (June 2026)** — sourced from a web-search
   summary, not a Daytona-official statement; verify directly against repo commit activity before
   this affects a self-host decision.
6. **Morph's isolation tech, pricing rates, and funding amount** — conflicting/thin public
   sourcing throughout; treat the whole Morph section as lower-confidence than the others.
7. **docker-py / podman-py exact code snippets** were not freshly re-verified this pass (standard
   library knowledge, not independently confirmed against current docs).
8. **nsjail** — exact star count, seccomp architecture detail, and FS/network-egress granularity
   not confirmed; recommend a direct fetch of `github.com/google/nsjail` if it becomes
   decision-relevant.
