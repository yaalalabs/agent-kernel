# #692 design diagrams

> Supporting material for [design.md](../design.md). These diagrams illustrate the design; they add no requirements.
> Where the design does not name a class or field, the name used here is illustrative and marked with `*`.

Legend for the flowcharts: a thick teal outline is new in #692, a dashed amber outline is changed by #692, a red
outline is a denied path, and anything else is existing and unchanged.

## 1. Worker pipeline in `BrokerWorkerCore.run`

`ExecutionManager` runs the guard once before submitting (defence in depth). The worker runs it again, authoritatively,
after `_enforce_policy` and before the per-session lock and sandbox acquisition
(`ak-py/src/agentkernel/sandbox/broker/worker.py`). A denied request never reaches a provider.

```mermaid
flowchart TD
  A(["Agent tool call"]) --> AG{"Agent-side guard<br/>in ExecutionManager"}
  AG -->|"denied"| DEN
  AG -->|"permitted: submit"| S(["ExecutionRequest arrives"])
  S --> R["Resolve profile to provider"]
  R --> RP{"Provider found?"}
  RP -->|"no"| CE["SandboxConfigError"]
  RP -->|"yes"| OP{"operation is destroy?"}
  OP -->|"yes"| DS["Dispose sandbox unless attached<br/>no checks run"]
  OP -->|"no"| P1["_check_principal"]
  P1 --> P2["_enforce_policy"]
  P2 --> GQ{"Gated operation?"}
  GQ -->|"execute_command, upload_file, download_file"| L
  GQ -->|"execute_code, install_packages"| G["SandboxPermissionGuard"]
  G -->|"denied"| DEN["Guard logs one WARNING on ak.sandbox.broker<br/>and raises SandboxPermissionDeniedError<br/>process() and the thread flavor skip<br/>their generic warning for this subclass only"]
  G -->|"permitted"| L["Per-session lock"]
  L --> AQ["Attach or create sandbox, self-heal"]
  AQ --> EX["Provider call under effective timeout"]
  EX --> RES(["SandboxResult"])
  classDef new stroke:#1f8a7a,stroke-width:3px
  classDef deny stroke:#b3322d,stroke-width:2px
  class AG,GQ,G new
  class DEN,CE deny
```

- The guard reads only the request (`policy`, `operation`, `payload`). It never reads `AKConfig` or provider
  capabilities. The existing
  `_check_principal` still reads `AKConfig`.
- Because the authoritative check sits in the worker core, it covers the embedded, thread and queue flavors and
  bring-your-own `ExecutionManager` callers.

## 2. Guard deny rules

Every deny exit makes the guard itself log exactly one `WARNING` on `ak.sandbox.broker` and raises `SandboxPermissionDeniedError`. The log line names
the operation, profile, agent, AK session id, sandbox session id and reason. It never includes code bodies or package
lists.

Package-spec validation is not a guard rule. `PackageInstaller` does it, with a shared baseline and then the
ecosystem's `PackageSpecRule` (built-in or bring-your-own), and raises `ValueError` without an audit line.

```mermaid
flowchart TD
  IN["Guard: request.policy"] --> OPS{"operation"}

  OPS -->|"execute_code"| L1{"policy.languages set?"}
  L1 -->|"no: provider-declared languages apply"| OK
  L1 -->|"yes"| L2{"language in the allowlist?"}
  L2 -->|"no"| DENY
  L2 -->|"yes"| OK

  OPS -->|"install_packages"| P1{"package_install block declared?"}
  P1 -->|"no"| DENY
  P1 -->|"yes"| P2{"ecosystem in package_install.ecosystems?"}
  P2 -->|"no"| DENY
  P2 -->|"yes"| OK

  DENY["Denied<br/>WARNING + SandboxPermissionDeniedError"]
  OK(["Permitted: continue to lock and acquire"])
  classDef deny stroke:#b3322d,stroke-width:2px
  class DENY deny
```

## 3. Permission vs capability

Policy (what the profile *may* do) is checked first, by the guard. Capability (what the image *can* do) is the existing
honesty contract, raised by the handle. Only the policy denial is audit-logged.

```mermaid
flowchart LR
  Q["Gated operation"] --> M{"Policy permits it?<br/>may side: request.policy only"}
  M -->|"no"| PE["SandboxPermissionDeniedError<br/>+ WARNING audit line"]
  M -->|"yes"| C{"Instance declares it?<br/>can side: provider config"}
  C -->|"no"| CE["SandboxCapabilityError<br/>no audit line"]
  C -->|"yes"| RUN["Run in sandbox"]
  RUN -->|"installer or script fails"| NZ["SandboxResult<br/>non-zero exit_code"]
  RUN -->|"success"| OKR["SandboxResult"]

  RC["run_command, or subprocess inside run_code"] -.->|"not gated by these permissions"| IMG[("Anything installed in the image")]
  classDef deny stroke:#b3322d,stroke-width:2px
  classDef changed stroke:#b26a12,stroke-width:2px,stroke-dasharray:6 4
  class PE deny
  class CE,NZ changed
```

## 4. Configuration and model

The policy envelope is extended in place. `_SandboxPolicyConfig` is the config-side mirror of `SandboxPolicy` and gains
the same fields. `package_install` is presence-enabled: a declared block permits installing, and `None` denies it.

```mermaid
classDiagram
  direction LR
  class ExecutionRequest {
    +operation
    +profile
    +principal
    +SandboxPolicy policy
    +sandbox_session
  }
  class SandboxPolicy {
    <<changed>>
    +network_egress
    +fs_allow_read / fs_allow_write
    +cpu / memory_mb
    +timeout
    +strict
    +Optional~list~ languages
    +Optional~PackageInstallPolicy~ package_install
  }
  class PackageInstallPolicy {
    <<new>>
    +list~str~ ecosystems
  }
  class ProviderRuntimeConfig {
    <<new>>
    +dict language_runtimes
  }
  class ProviderPackageConfig {
    <<new>>
    +dict package_installers
    +dict package_rules
  }
  class DockerConfig
  class KubernetesConfig
  class E2BConfig
  class DaytonaConfig
  class SandboxCapabilities {
    <<changed>>
    +list~str~ languages
    +list~str~ package_ecosystems
    +bool package_install derived
  }
  class SandboxPermissionGuard {
    <<new>>
    +check(request)*
  }
  class Sandbox {
    +execute_code(code, language)
    +install_packages(packages, ecosystem, timeout)
  }
  class PackageInstaller {
    <<new>>
    +build argv from package_installers
    +baseline spec validation
  }
  class PackageSpecRule {
    <<new>>
    +validate(packages)*
  }
  class PythonSpecRule
  class NodeSpecRule
  ExecutionRequest *-- SandboxPolicy
  SandboxPolicy *-- PackageInstallPolicy
  ProviderRuntimeConfig <|-- DockerConfig
  ProviderRuntimeConfig <|-- KubernetesConfig
  ProviderPackageConfig <|-- DockerConfig
  ProviderPackageConfig <|-- KubernetesConfig
  ProviderPackageConfig <|-- E2BConfig
  ProviderPackageConfig <|-- DaytonaConfig
  ProviderRuntimeConfig ..> SandboxCapabilities : keys become languages
  ProviderPackageConfig ..> SandboxCapabilities : keys become package_ecosystems
  SandboxPermissionGuard ..> SandboxPolicy : reads
  Sandbox ..> PackageInstaller : uses
  PackageSpecRule <|-- PythonSpecRule
  PackageSpecRule <|-- NodeSpecRule
  PackageInstaller ..> PackageSpecRule : runs rule for ecosystem
  ProviderPackageConfig ..> PackageSpecRule : package_rules resolves BYO
```

`PythonSpecRule`\* and `NodeSpecRule`\* are illustrative names for the built-in `python` and `node` rules.

| Field | Side | Default | Meaning |
|---|---|---|---|
| `languages` | policy (may) | `None` | Allowlist for `run_code`. `None` means whatever the provider declares, which is today's behaviour. `[]` denies every `run_code` call. |
| `package_install` | policy (may) | `None` | Presence permits installing. Absent means denied. |
| `package_install.ecosystems` | policy (may) | `["python"]` | `[]` is rejected at load. Open question: default to everything the provider declares instead? |
| `language_runtimes` | provider (can), `docker`/`kubernetes` | `{python: [python, -c]}` | Language to interpreter argv prefix. Keys become the instance's `languages`. A `python` key is required; every prefix must be non-empty with no empty token. |
| `package_installers` | provider (can) | `{python: [pip, install]}` | Ecosystem to installer argv prefix. Keys become `package_ecosystems`. Each key must resolve to a `PackageSpecRule` (`python` and `node` ship, others come from `package_rules`); every prefix must be non-empty with no empty token. |
| `package_rules` | provider (can) | `{}` | Ecosystem to the dotted path of a bring-your-own `PackageSpecRule`, e.g. `apk: my_org.rules.ApkRule`. |

Example profile using both capabilities (illustrative):

```yaml
sandbox:
  enabled: true
  profiles:
    default:
      type: docker
      docker:
        image: my-org/sandbox-node:1.4
        language_runtimes:              # can: what the image contains
          python: [python, -c]
          node: [node, -e]
        package_installers:
          python: [pip, install]
          node: [npm, install]        # operator-declared: only the image knows npm exists
      policy:                          # may: what agents are allowed to do
        # docker cannot enforce an allowlist (it fails closed under strict). For hard egress
        # limits use network_egress: deny with a mirror or pre-baked image instead.
        network_egress: allow
        languages: [python, node]
        package_install:               # present = permitted
          ecosystems: [python]          # node can install, but this profile may not
```

## 5. Provider matrix after #692

What each built-in provider can declare (the *can* side). The profile policy still has to permit each one.

| Provider | Languages | Package install | Config mixins |
|---|---|---|---|
| `docker` | Keys of `language_runtimes`, run as argv (replaces hard-coded `python -c`) | Yes: `PackageInstaller` argv, run directly | Runtime + Package |
| `kubernetes` | Keys of `language_runtimes`, run as argv (replaces hard-coded `python -c`) | Yes: `PackageInstaller` argv, run directly | Runtime + Package |
| `e2b` | `python` (unchanged; the template decides its kernel) | Yes: `PackageInstaller` argv joined with `shlex.join` (the SDK takes a string) | Package |
| `daytona` | `python` only (the SDK fixes the language per sandbox) | Yes: `PackageInstaller` argv joined with `shlex.join` (the SDK takes a string) | Package |
| `local_subprocess` | `python`, `bash` (unchanged) | No | None |
| `ec2_ssm` | `python` (unchanged) | No | None |

## 6. Capability 1: code in additional languages

```mermaid
flowchart LR
  RC["run_code with language = node"] --> G1{"policy.languages set<br/>and node missing from it?"}
  G1 -->|"yes"| PE["SandboxPermissionDeniedError + WARNING"]
  G1 -->|"no"| C1{"node in instance languages?<br/>keys of language_runtimes"}
  C1 -->|"no"| CE["SandboxCapabilityError"]
  C1 -->|"yes"| ARGV["argv = runtime prefix + code<br/>node, -e, CODE"]
  ARGV --> EX["docker exec or kubernetes exec"]
  EX --> RES(["SandboxResult"])
  classDef new stroke:#1f8a7a,stroke-width:3px
  classDef changed stroke:#b26a12,stroke-width:2px,stroke-dasharray:6 4
  classDef deny stroke:#b3322d,stroke-width:2px
  class G1 new
  class C1,ARGV changed
  class PE deny
```

## 7. Capability 2: `install_packages`, in-process flavor

In the embedded and thread flavors, `run()` raises the real exception type up to the tool.

```mermaid
sequenceDiagram
  autonumber
  actor Agent
  participant Tool as install_packages tool
  participant EM as ExecutionManager
  participant W as BrokerWorkerCore
  participant G as SandboxPermissionGuard
  participant H as Provider handle
  participant PI as PackageInstaller
  participant SB as Sandbox
  Agent->>Tool: install_packages(packages, ecosystem, sandbox_session_id, profile)
  Tool->>EM: install_packages(...)
  Note over EM: Warns once per profile if package_install is declared with network_egress deny,<br/>or with an fs policy on docker or kubernetes (read-only root filesystem)
  EM->>G: agent-side check(request)
  opt not permitted (agent side)
    G->>G: one WARNING on ak.sandbox.broker, no package list
    G-->>EM: raise SandboxPermissionDeniedError
    Note over EM,G: The tool returns error JSON before submit
  end
  EM->>W: ExecutionRequest op=install_packages with resolved policy
  W->>W: _check_principal, then _enforce_policy
  W->>G: check(request)
  alt not permitted
    G->>G: one WARNING on ak.sandbox.broker, no package list
    G-->>W: raise SandboxPermissionDeniedError
    W-->>EM: SandboxPermissionDeniedError (generic failure warning skipped)
    EM-->>Tool: SandboxPermissionDeniedError
    Tool-->>Agent: error JSON
  else permitted
    W->>W: per-session lock, attach or create sandbox
    W->>H: install_packages(packages, ecosystem=..., timeout=...), backstop = timeout + grace
    alt ecosystem not declared by this instance
      H-->>W: raise SandboxCapabilityError
      W-->>EM: SandboxCapabilityError
      EM-->>Tool: SandboxCapabilityError
      Tool-->>Agent: error JSON
    else declared
      H->>PI: validate specs, build argv for ecosystem
      alt invalid spec for the ecosystem (URL, VCS, path, archive, leading dash, ...)
        PI-->>H: raise ValueError, no audit line
        H-->>W: ValueError
        W-->>EM: ValueError
        EM-->>Tool: ValueError
        Tool-->>Agent: error JSON
      else valid
        PI-->>H: argv, e.g. pip install pkg-a pkg-b
        H->>SB: run argv (docker, kubernetes) or shlex.join string (e2b, daytona)
        SB-->>H: exit_code, stdout, stderr (handle kills it on its own timeout, before the backstop)
        H-->>W: SandboxResult, non-zero exit_code on installer failure
        W-->>EM: SandboxResult
        EM-->>Tool: SandboxResult or promoted SandboxTask
        Tool-->>Agent: JSON result or pending task
      end
    end
  end
```

## 8. Queue flavor: the policy travels with the request

The agent side resolves the profile policy and the worker enforces exactly that, so a worker with a different
`AKConfig` cannot widen it. The codec code and `BrokerOperation` do not change, but the schema gains the new policy
fields and the `ecosystem` payload key.

```mermaid
sequenceDiagram
  autonumber
  participant EM as ExecutionManager (agent pod)
  participant Q as Queue transport
  participant QW as Queue worker
  participant W as BrokerWorkerCore
  participant G as SandboxPermissionGuard
  Note over EM: Resolves profile policy from its own AKConfig, runs the agent-side guard
  EM->>Q: ExecutionRequest, policy carried on the request
  Q->>QW: deliver request
  QW->>W: process(request)
  W->>G: check using request.policy only
  Note over G: Never reads the worker's AKConfig
  alt denied
    G->>G: one WARNING on ak.sandbox.broker
    G-->>W: raise SandboxPermissionDeniedError
    W-->>QW: generic failure warning skipped, ExecutionCompletion status=failed, error_type=SandboxPermissionDeniedError
  else permitted
    W->>W: lock, acquire, provider call
    W-->>QW: ExecutionCompletion status=succeeded with result
  end
  QW->>Q: publish completion
  Q-->>EM: completion, tool returns result or error JSON
  Note over EM,G: Old agent to new worker: new fields decode as absent, so gated operations are denied
  Note over EM,G: New agent to old worker: old worker drops the new fields and ignores ecosystem (runs pip). The agent-side guard prevents unchecked installs. Upgrade workers first.
```
