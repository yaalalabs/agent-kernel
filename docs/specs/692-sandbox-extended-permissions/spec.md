# #692: Sandbox extended permissions — Implementation Spec

> Status: **Draft**. Stage 2, written against [design.md](design.md) as finalized in `b3ca3e22`. Stage 3
> (`plan.md`) follows once this spec is reviewed.

This spec details how the approved design is built. Profile policy gains two permissions: the languages `run_code`
may use, and whether packages may be installed and from which ecosystems. One new class,
`SandboxPermissionGuard`, decides every gated operation. It runs authoritatively in `BrokerWorkerCore`, and as
defence in depth in `ExecutionManager`. Package installation becomes reachable through a new `install_packages`
tool. A shared `PackageInstaller` turns a request into a validated installer argv, with per-ecosystem validation
through a pluggable `PackageSpecRule`. In phase 2, `docker` and `kubernetes` run code through operator-declared
`language_runtimes`. [design.md](design.md) is the requirements source; [Requirement trace](#requirement-trace)
maps each of its requirements to a section here and to a delivery phase.

Line citations are against `develop` at `341d3fe9`.

**Clarifications made while detailing.** None changes a requirement. Each is listed here so the reviewer can confirm
it matches the design's intent:

1. **"Config load resolves every rule" becomes two checks.** `core/config.py` cannot import `sandbox/`, because
   `sandbox` imports `core.config`. So:
   - Pydantic validators, at config load, check structure: argv prefixes, `ecosystems: []`, and `attached` +
     `package_install`.
   - `PackageSpecRuleFactory.validate_config`, at each side's startup hook, resolves rules: built-in names and
     dotted paths. The agent side runs it in `get_sandbox_tools()`, which runs at agent construction
     (`core/base.py:708`). The worker side runs it in `QueueBrokerWorker._validated_broker`
     (`broker/queue_worker.py:73`).
   - A missing or unresolvable rule therefore fails at process startup with `SandboxConfigError`, not on a request.
2. **The guard decides before session resolution on the agent side.** The guard runs on `(operation, payload,
   policy)` before `_resolve_session` (`manager.py:250`). That method can tear down an idle-expired sandbox, and a
   denied request must have no side effects.
3. **The kill no longer needs `pkill`.** The default image `python:3.12-slim` ships neither `pkill` nor `ps`. This
   was verified with `docker run --rm python:3.12-slim sh -c 'command -v pkill'`, which prints nothing. So today's
   `_best_effort_kill` (`docker.py:89`, `kubernetes.py:169`) kills nothing on the default image. The design
   requires that a timed-out install be killed, so the kill moves to a `/proc` scan that needs no procps (see
   [ProcessKiller](#processkiller)). The scan matches a per-exec environment marker, not the process name: once the
   kill actually works, a name match would also kill same-named processes from earlier execs, such as a background
   `python` server the agent started.
4. **A bring-your-own rule for a built-in ecosystem runs after the built-in rule, never instead of it.** The design
   offers bring-your-own rules as the way to get package-name allowlists. A `python` allowlist must therefore be
   able to narrow the `python` grammar, and must not be able to loosen it.
5. **The config mixins are spelled with config.py's private prefix.** The design's `ProviderRuntimeConfig` and
   `ProviderPackageConfig` become `_SandboxProviderRuntimeConfig` and `_SandboxProviderPackageConfig`. Every model
   in `core/config.py` except `AKConfig` is private.

## Design

### Package layout

```
ak-py/src/agentkernel/sandbox/
├── errors.py              # + SandboxPermissionDeniedError
├── model.py               # + PackageInstallPolicy; SandboxPolicy.languages / .package_install /
│                          #   .effective_timeout(); SandboxCapabilities.package_ecosystems + validator + derive()
├── base.py                # Sandbox.install_packages(packages, ecosystem="python", timeout=None)
├── permission.py          # NEW: SandboxPermissionGuard, PermissionAuditContext
├── packages.py            # NEW: PackageSpecRule ABC, PythonPackageSpecRule, NodePackageSpecRule,
│                          #      PackageSpecRuleFactory, PackageInstaller
├── manager.py             # + install_packages(); guard + spec validation before submit; config warnings
├── tools.py               # + install_packages tool (conditional); permission-aware guidance
├── testing.py             # + contract check: undeclared ecosystem raises
├── __init__.py            # + exports PackageSpecRule, PackageInstallPolicy (see Public exports)
├── broker/
│   ├── worker.py          # guard; mismatch warning; effective timeout + backstop; install dispatch + legacy shim
│   ├── thread.py          # skip generic warning for SandboxPermissionDeniedError
│   ├── queue.py           # ceiling check against the operation's effective timeout
│   └── queue_worker.py    # startup rule resolution
└── providers/
    ├── process.py         # NEW: ProcessKiller (per-exec marker + procps-free kill-by-marker command)
    ├── docker.py          # instance caps; installer argv; runtime argv (phase 2); kill on timeout or cancel
    ├── kubernetes.py      # same as docker
    ├── e2b.py             # instance caps; installer command (shlex.join); install timeout
    ├── daytona.py         # same as e2b
    └── ec2_ssm.py         # instance-caps language check only
ak-py/src/agentkernel/core/config.py   # policy fields, _SandboxPackageInstallConfig, provider mixins
```

`local_subprocess.py` is not changed. It declares `package_install=False` (`local_subprocess.py:117`). Its language
dispatch is an `if/elif` on the language name (`local_subprocess.py:41-46`) that matches its declared
`["python", "bash"]` (`local_subprocess.py:115`), and it reads no class capability attribute.

### Public exports

`agentkernel.sandbox.__all__` gains two names:

- `PackageSpecRule`, the stable import path for bring-your-own rule authors;
- `PackageInstallPolicy`, beside the already-exported `SandboxPolicy`.

`SandboxPermissionDeniedError` is reachable through the already-exported `errors` module.

These stay internal, as the factory, tools and providers are today (`sandbox/__init__.py:7-10`):

- `SandboxPermissionGuard`;
- `PermissionAuditContext`;
- `PackageSpecRuleFactory`;
- `PackageInstaller`;
- the two built-in rules;
- `ProcessKiller`.

### Governing rules

1. **The guard reads only the request.** `SandboxPermissionGuard` takes `operation`, `payload` and `policy`, plus an
   audit context used only for the log line. It never reads `AKConfig` or provider capabilities.
   - Reason: a queue-flavor worker must enforce exactly the policy the agent side resolved (design, Trust model).
     Capability checks stay in the handles, which keeps "not permitted" and "cannot" separate.
2. **The guard is the only reader of the permission fields.** `policy.languages` and `policy.package_install` are
   read for permission decisions in exactly one place: `SandboxPermissionGuard._denial_reason`. Three other readers
   use them for different purposes, and none of them decides permission:
   - the worker's mismatch warning;
   - tool registration and guidance;
   - the effective-timeout lookup.
3. **The guard logs; callers never log a denial again.** The guard writes exactly one `WARNING` on
   `ak.sandbox.broker` per denial.
   - `BrokerWorkerCore.process()` and `ThreadBroker._handle` skip their generic warning for
     `SandboxPermissionDeniedError` only.
   - The tools' warning on `ak.sandbox.tools` stays. "One per denial" is counted per logger.
4. **The handle owns the timeout, and the worker's timer is a backstop.** The worker passes the operation's
   effective timeout to the handle. The worker wraps the call in `asyncio.wait_for(effective +
   BACKSTOP_GRACE_SECONDS)`.
5. **Providers never read `AKConfig`.** `PackageInstaller` and the runtime map are built from the provider's own
   config block, injected by the factory. This is the existing rule at `base.py:90-95`.
6. **Validation is input checking, not permission.** A rejected package spec raises `ValueError`, which is not
   audit-logged. Its message names the entry's index and the rule it broke, never the entry text, so no package
   text reaches any log.

### Errors (`sandbox/errors.py`) — phase 1

```python
class SandboxPermissionDeniedError(SandboxPolicyError):
    """The profile's policy does not permit this operation (raised and audit-logged by SandboxPermissionGuard)."""
```

- It is a plain subclass with the inherited `Exception(message)` constructor.
  - That constructor is what the queue client's typed re-raise calls: `exc_cls(completion.error or ...)`
    (`broker/queue.py:162-164`).
  - Because the class is defined in `errors.py`, the `getattr(sandbox_errors, ...)` lookup resolves it by name.
- Its message never contains code or package text.

### Wire and capability models (`sandbox/model.py`) — phase 1

```python
class PackageInstallPolicy(BaseModel):
    """Permission to install packages, carried on the wire inside SandboxPolicy."""

    ecosystems: list[str] = Field(default_factory=lambda: ["python"], min_length=1)  # permitted ecosystem keys
    timeout: float | None = Field(default=None, gt=0)  # install wall clock; None = policy.timeout


class SandboxPolicy(BaseModel):
    ...  # existing fields unchanged
    languages: list[str] | None = None  # run_code allowlist; None = provider-declared; [] = deny every run_code
    package_install: PackageInstallPolicy | None = None  # None = installs denied

    def effective_timeout(self, operation: str) -> float:
        """The operation's own wall-clock limit: package_install.timeout for installs when set, else timeout."""
```

`SandboxCapabilities` gains a field and a validator:

```python
    package_ecosystems: list[str] = Field(default_factory=list)  # ecosystems install_packages accepts

    @model_validator(mode="after")
    def _derive_package_install(self) -> "SandboxCapabilities":
        """Keep package_install consistent with package_ecosystems (the source of truth):
        - non-empty ecosystems -> package_install=True; an explicit package_install=False
          ('package_install' in model_fields_set) raises ValueError;
        - package_install=True with no ecosystems (a pre-#692 BYO declaration) -> ["python"]."""

    def derive(self, **update: Any) -> "SandboxCapabilities":
        """A re-validated copy with ``update`` applied: the instance-override helper."""
        return type(self).model_validate({**self.model_dump(), **update})
```

- **Why `derive` exists.** Pydantic's `model_copy(update=...)` skips validators. If the instance overrides used it,
  as `kubernetes.py:206` does today, they would bypass `_derive_package_install` and could represent
  `package_install=True` with no ecosystems.
- **Rule for every instance override.** Each override goes through `derive`, including the existing kubernetes
  `policy_network` flip.
  - An override that changes ecosystems sets both fields together: `derive(package_ecosystems=eco,
    package_install=bool(eco))`. This means a provider configured with `package_installers: {}` honestly declares
    no installs.

### SandboxPermissionGuard (`sandbox/permission.py`) — phase 1

```python
class PermissionAuditContext(BaseModel):
    """Who and where, for the denial log line only; never part of the decision."""

    profile: str
    agent: str
    ak_session_id: str
    sandbox_session_id: str


class SandboxPermissionGuard:
    """Decides whether one operation is permitted by its profile's policy. Stateless."""

    _log = logging.getLogger("ak.sandbox.broker")

    def check(self, request: ExecutionRequest) -> None:
        """Worker entry point: check_operation over the request's own fields."""

    def check_operation(self, operation: str, payload: Mapping[str, Any], policy: SandboxPolicy,
                        context: PermissionAuditContext) -> None:
        """Raise SandboxPermissionDeniedError (after one WARNING) when the policy denies the operation."""

    @staticmethod
    def _denial_reason(operation: str, payload: Mapping[str, Any], policy: SandboxPolicy) -> str | None:
        """The deny rules; None = permitted."""
```

The deny rules are exhaustive. Any operation not listed here is permitted:

| Operation | Denied when | Reason text |
|---|---|---|
| `execute_code` | `policy.languages is not None` and `payload.get("language", "python")` is not in it | `language '<l>' is not permitted by the profile (permitted: [...])` |
| `install_packages` | `policy.package_install is None` | `the profile does not permit package installation` |
| `install_packages` | `payload.get("ecosystem", "python")` is not in `policy.package_install.ecosystems` | `ecosystem '<e>' is not permitted by the profile (permitted: [...])` |

- The guard does not gate `execute_command`, `upload_file`, `download_file` or `destroy`.
- **Log line.** It is written once per denial, on `ak.sandbox.broker`, at `WARNING`:
  `Sandbox permission denied: operation=%s profile=%s agent=%s ak_session_id=%s sandbox_session_id=%r reason=%s`.
  The reason text holds only the language or ecosystem names and the permitted list, never code or package specs.
  The names come from the request, so they are repr-escaped (`{name!r}`), and so is `sandbox_session_id` (`%r`),
  which may be a model-supplied id: a newline in either cannot forge a log line.
- **Exception message.** It is `profile '<p>' does not permit <operation>: <reason>; this is a configuration
  decision, so do not retry it through run_command`.
- **Concurrency.** The guard holds no state. One instance per `BrokerWorkerCore` and one per `ExecutionManager` is
  safe across threads and event loops.

### BrokerWorkerCore changes (`sandbox/broker/worker.py`) — phase 1

The new `run()` order is shown below. Steps marked with `+` are new.

```
1. provider = SandboxProviderFactory.get(profile)                  (worker.py:62, unchanged)
2. destroy short-circuit                                           (worker.py:71, unchanged)
3. + _warn_capability_mismatch(provider, request)
4. _check_principal, _enforce_policy                               (worker.py:79-80, unchanged)
5. + self._guard.check(request)
6. lock -> _acquire -> _execute                                    (worker.py:82, unchanged)
```

```python
class BrokerWorkerCore:
    BACKSTOP_GRACE_SECONDS: ClassVar[float] = 10.0  # patch target for tests

    # __init__ adds:
    #   self._guard = SandboxPermissionGuard()
    #   self._install_shim: dict[type, bool] = {}  # Sandbox subclass -> True when its install_packages is legacy
    #   self._policy_warned: set[tuple[str, ...]]  # was set[tuple[str, str]]; widened for the tagged mismatch key

    def _warn_capability_mismatch(self, provider: SandboxProvider, request: ExecutionRequest) -> None:
        """One WARNING per (provider, profile) when the policy permits what the instance does not declare."""

    async def _call_install(self, sandbox: Sandbox, payload: dict, timeout: float) -> SandboxResult:
        """Dispatch install_packages, routing a pre-#692 one-argument override through the deprecation shim."""
```

- **Mismatch warning.**
  - It warns when any of these holds:
    - `policy.package_install` is set and the instance's `package_ecosystems` lacks at least one entry of
      `package_install.ecosystems`. This covers `package_install=False` providers such as `local_subprocess` and
      `ec2_ssm`.
    - `policy.languages` holds a language that is not in the instance's `languages`.
  - It reads `provider.capabilities`, which is the instance, so instance overrides count.
  - Its memo key is `(type(provider).__name__, request.profile, "permission")`. This tagged key stays apart from the
    `_enforce_policy` key `(provider, profile)` (`worker.py:43`, `worker.py:164-165`), so neither warning suppresses
    the other.
  - Message: `Sandbox profile %s permits %s, but provider %s does not declare it; such requests will fail with
    SandboxCapabilityError`.
- **Generic warning skip.** `process()` (`worker.py:114`) adds an `except SandboxPermissionDeniedError` branch ahead
  of `except Exception`. The branch builds the same `failed` completion with `error_type` set, and logs nothing.
  - Every other `SandboxPolicyError` still reaches the generic warning. That includes the errors from
    `_check_principal` and `_enforce_policy`.
- **Effective timeout and backstop.** `_execute` (`worker.py:206-234`) changes as follows:
  - `timeout = request.policy.effective_timeout(op)` replaces `request.policy.timeout` (`worker.py:211`).
  - The handle receives `timeout=timeout` for `execute_code`, `execute_command` and `install_packages`.
  - `asyncio.wait_for(call(), timeout=timeout + self.BACKSTOP_GRACE_SECONDS)` replaces the bare `timeout`
    (`worker.py:230`).
  - On backstop expiry the message is `sandbox operation '<op>' exceeded timeout <timeout>s (backstop)`.
  - `upload_file` and `download_file` pass no timeout to their handles, as today, so the backstop is their only
    timer.
- **Install dispatch and the legacy shim.**
  - `_call_install` decides once per `Sandbox` subclass whether its override is legacy. It inspects
    `inspect.signature(type(sandbox).install_packages)`. The override counts as **modern** when it names both
    `ecosystem` and `timeout`, or when it takes `**kwargs`.
  - **Modern overrides** are called as `install_packages(packages, ecosystem=..., timeout=...)`.
  - **Legacy overrides:**
    - An `ecosystem` other than `python` raises `SandboxCapabilityError(<class>, "package_ecosystem:<e>")`.
    - Otherwise the call is `install_packages(packages)`, and the first such call per class logs one `WARNING` on
      `ak.sandbox.broker`: `Sandbox %s overrides install_packages(packages) without ecosystem/timeout; this form is
      deprecated and will stop working in the next minor release`.
    - The backstop is the install's only timer.
  - The memo `_install_shim` is per `BrokerWorkerCore` instance, so a worker warns at most once per class.

### Thread and queue flavors — phase 1

- **`ThreadBroker._handle`** (`broker/thread.py:135-141`) gains an `except SandboxPermissionDeniedError` branch
  ahead of `except Exception`.
  - It records the `failed` completion and delivers the exception to a waiting caller.
  - It does not log, because the guard already has.
- **`QueueExecutionBroker.submit`** (`broker/queue.py:103-108`) changes its ceiling check.
  - The old check was `request.policy.timeout > ceiling`.
  - The new check is `request.policy.effective_timeout(request.operation) > ceiling`, so an install is checked
    against its own `package_install.timeout`.
  - The grace period is not added. `worker_timeout_ceiling` is documented as the maximum *effective* timeout the
    worker supports (`config.py:829-832`), and its serverless value of 840 s already leaves margin under the
    platform limit. Adding the grace would make `policy.timeout: 840`, which is valid today, fail at submit.
  - The error message names the operation and its effective timeout.
- **`QueueBrokerWorker._validated_broker`** (`broker/queue_worker.py:73-86`) calls
  `PackageSpecRuleFactory.validate_config(config)` after `check_store_pairing`. A worker with an unresolvable rule
  therefore dies at startup.
- **The codec does not change**, and neither does `BrokerOperation` (`broker/base.py:17`) or `ExecutionRequest`. The
  new data travels as fields of `SandboxPolicy` and as the `ecosystem` key of the free-form `install_packages`
  payload.

### Sandbox ABC (`sandbox/base.py`) — phase 1

```python
    async def install_packages(self, packages: list[str], ecosystem: str = "python",
                               timeout: float | None = None) -> SandboxResult:
        """Install packages of one ecosystem and return the installer's SandboxResult.
        An undeclared ecosystem raises SandboxCapabilityError; an installer failure is a non-zero result.
        Optional: override only when the provider declares package_ecosystems."""
        raise SandboxCapabilityError(self.__class__.__name__, "package_install")
```

The capability-error subject for an undeclared ecosystem is `package_ecosystem:<e>`. This mirrors the existing
`language:<l>` form (`docker.py:55`).

### Package validation and installation (`sandbox/packages.py`) — phase 1

```python
class PackageSpecRule(ABC):
    """Validates package specs of one ecosystem's grammar. Bring-your-own rules subclass this."""

    @abstractmethod
    def validate(self, packages: list[str]) -> None:
        """Raise ValueError naming the index and the broken rule; never echo the entry."""


class PythonPackageSpecRule(PackageSpecRule): ...   # 'python': PyPI registry specs
class NodePackageSpecRule(PackageSpecRule): ...     # 'node': npm-registry specs


class PackageSpecRuleFactory:
    """Resolves an ecosystem key to its rule chain (#541 shape: built-in branches + resolve_dotted)."""

    BUILTIN: ClassVar[tuple[str, ...]] = ("python", "node")

    @classmethod
    def resolve(cls, ecosystem: str, package_rules: Mapping[str, str]) -> list[PackageSpecRule]:
        """The built-in rule, if any, then the bring-your-own rule from package_rules, if any;
        SandboxConfigError when neither exists or a dotted path does not resolve to a PackageSpecRule."""

    @classmethod
    def validate_config(cls, sandbox_config: Any) -> None:
        """Startup check: resolve every package_installers key of every profile's provider block."""


class PackageInstaller:
    """Turns a package request into a validated installer invocation. Shared by docker, kubernetes, e2b, daytona."""

    def __init__(self, installers: Mapping[str, list[str]], rules: Mapping[str, list[PackageSpecRule]]) -> None: ...

    @classmethod
    def from_config(cls, config: Any) -> "PackageInstaller":
        """Build from a _SandboxProviderPackageConfig block, resolving rules through the factory."""

    @property
    def ecosystems(self) -> list[str]: ...  # the declared keys, in config order

    def validate(self, packages: list[str], ecosystem: str) -> None:
        """Baseline, then every rule in the ecosystem's chain. ValueError on rejection."""

    def argv(self, packages: list[str], ecosystem: str) -> list[str]:
        """validate(), then the configured prefix + one argument per package."""

    def command(self, packages: list[str], ecosystem: str) -> str:
        """shlex.join(argv(...)), for SDKs that accept only a command string."""
```

- **Baseline.** `PackageInstaller._check_baseline` runs before any rule. It rejects:
  - an empty list;
  - an empty entry;
  - an entry starting with `-`;
  - any whitespace (`str.isspace` on any character);
  - NUL;
  - `://`;
  - a leading `.`, `/` or `~`.
- **`python` rule.**
  - It accepts a registry name with optional extras and version specifiers, with no whitespace and no markers. The
    pattern is:
    `^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?(?:(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+(?:,(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+)*)?$`
  - Before the pattern, it rejects these explicitly, each with its own message:
    - a `git+` prefix;
    - any `/`;
    - an archive suffix: pip's full `ARCHIVE_EXTENSIONS` set (`.zip`, `.whl`, `.tar.bz2`, `.tbz`, `.tar.gz`, `.tgz`,
      `.tar`, `.tar.xz`, `.txz`, `.tlz`, `.tar.lz`, `.tar.lzma`). pip installs a bare entry with any of these
      suffixes as a local file, so a shorter list would let a file in the workdir through.
  - The pattern excludes `@`, so direct references (`name @ url`) and markers (`;`) are also rejected.
- **`node` rule.**
  - It accepts `name`, `@scope/name`, and either one followed by `@<version-or-range>`. The pattern is:
    `^(?:@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*(?:@[A-Za-z0-9.^~<>=*|+_-]+)?$`
  - Before the pattern, it rejects these explicitly:
    - the protocol prefixes `github:`, `git+`, `file:`, `link:` and `npm:`;
    - a `.tgz`, `.tar.gz` or `.tar` suffix (npm-package-arg treats each as a local file);
    - any `/` other than the single scope separator, which covers `user/repo` shorthand.
- **Rule chains.** For a built-in key, a `package_rules` entry is appended after the built-in rule, so it can only
  narrow (clarification 4). For any other key, the `package_rules` entry is the whole chain.
- **Resolution.**
  - Built-ins are resolved by an `if/elif` with real classes.
  - A dotted path goes through `resolve_dotted(path, base=PackageSpecRule, error=SandboxConfigError)`, then is
    instantiated with no arguments. This is the shape `SandboxProviderFactory` uses (`factory.py:161`).
- **Where `validate_config` runs.**
  - Agent side: `get_sandbox_tools()`, at agent construction.
  - Worker side: `QueueBrokerWorker._validated_broker`.
  - The embedded and thread flavors share the agent's process, so the agent-side check covers them.
- **Concurrency.** A `PackageInstaller` is immutable after construction and is safe to share across threads.

### ProcessKiller (`sandbox/providers/process.py`) — phase 1

```python
class ProcessKiller:
    """Tags an exec with a unique marker and builds the procps-free command that kills it."""

    MARKER_ENV: ClassVar[str] = "AK_EXEC_ID"
    KILL_TIMEOUT_SECONDS: ClassVar[float] = 5.0  # must stay below BrokerWorkerCore.BACKSTOP_GRACE_SECONDS

    @staticmethod
    def new_marker() -> str: ...                                # uuid4().hex: fixed-length, fresh per exec

    @classmethod
    def environment(cls, marker: str) -> dict[str, str]: ...     # {AK_EXEC_ID: marker}, for Docker exec_run(environment=)

    @classmethod
    def wrap(cls, argv: list[str], marker: str) -> list[str]:
        """['/bin/sh', '-c', 'export AK_EXEC_ID="$1"; shift; exec "$@"', 'ak-exec', marker, *argv], for the
        Kubernetes stream exec, which has no per-exec environment."""

    @classmethod
    def argv(cls, marker: str) -> list[str]:
        """['/bin/sh', '-c', <scan /proc/[0-9]*/environ, SIGKILL every pid whose environment holds
        AK_EXEC_ID=<marker>, skipping PID 1 and the scanning shell's own $$>]."""
```

- This is the single home of the kill shared by `docker` and `kubernetes`. It replaces `["pkill", "-9", name]`
  (`docker.py:89`) and `sh -c "pkill -9 name"` (`kubernetes.py:169`).
- **Why a marker, not the name.** Once the kill works, a name match kills every same-named process in the sandbox:
  a timed-out `run_code` would also kill a background `python` server that an earlier exec started. Each killable
  exec therefore carries a fresh marker in its environment, and the kill matches only that marker.
  - `docker` passes it through `exec_run(environment=...)`, so the exec argv is unchanged.
  - `kubernetes` launches the exec through `wrap()`: the launcher exports the marker and `exec`s the real argv, so
    the process that runs is still argv[0].
  - Children inherit the environment, so the installer's children (pip's build backends, npm's lifecycle scripts)
    are killed with it.
  - The kill's own exec carries no marker, so it never matches itself. The `$$` and PID 1 skips stay as second
    guards. PID 1 is the container's main process: managed sandboxes run `sleep infinity` there, but an image whose
    entrypoint is an interpreter would otherwise be at risk (the concern noted at `tests/test_sandbox_providers.py:1617`).
  - The shell drops environ's NUL separators when reading it. That is safe because the marker is fixed-length hex,
    so no marker is a prefix of another.
- **The kill never runs in an environment the framework does not own.** When the provider's config sets
  `attach_to` (`docker` mode 3, `config.py:746`; `kubernetes` mode 3, `config.py:783`), the handle is built with the
  kill disabled, and its execs are neither tagged nor wrapped.
  - On a timeout or cancellation it raises as usual, and the timed-out process keeps running.
  - The flag comes from the config's `attach_to`, not from create-versus-attach, because managed sessions reattach
    through `attach()` too.
- The kill is **best-effort**, for three reasons:
  - A process that clears or replaces its environment (for example `env -i`) no longer carries the marker and
    escapes.
  - Background jobs started *by the timed-out exec itself* inherit its marker and are killed with it.
  - The kill call is bounded by `KILL_TIMEOUT_SECONDS`.
- The scan needs `/bin/sh` and `cat`, which every supported image ships.
- The docs state these limits.

### Provider changes — phase 1 (packages, instance capabilities) and phase 2 (runtimes)

There are eight handle-construction sites:

- `docker.py:159`, `docker.py:194`;
- `kubernetes.py:275`, `kubernetes.py:391`;
- `e2b.py:123`, `e2b.py:131`;
- `daytona.py:136`, `daytona.py:183`.

At every one of them, the handle now also receives the provider instance's `capabilities` and its
`PackageInstaller`. The `docker` and `kubernetes` handles also receive `kill_enabled = not config.attach_to` (see
[ProcessKiller](#processkiller)). In phase 2, the `docker` and `kubernetes` handles also receive the runtime map. Handle language
checks read the instance capabilities, not the class attribute. These five lines change:

- `docker.py:54`;
- `kubernetes.py:75`;
- `e2b.py:44`;
- `daytona.py:55`;
- `ec2_ssm.py:87`. The `ec2_ssm` handle is built at `ec2_ssm.py:205` from the provider's instance.

| Provider | Instance capability override (via `derive`) | `install_packages` | `execute_code` |
|---|---|---|---|
| `docker` | `package_ecosystems` = `package_installers` keys. Phase 2: `languages` = `language_runtimes` keys | `self._exec(installer.argv(...), timeout)` | Phase 1: `["python", "-c", code]` (`docker.py:56`). Phase 2: `[*runtimes[language], code]` |
| `kubernetes` | The same, composed with the existing `policy_network` flip (`kubernetes.py:202-206`) in one `derive` call | The same as `docker` | The same as `docker` (`kubernetes.py:77`) |
| `e2b` | `package_ecosystems` = `package_installers` keys | `self.execute_command(installer.command(...), timeout)` | Unchanged, `["python"]` |
| `daytona` | The same as `e2b` | The same as `e2b` | Unchanged, `["python"]` |
| `local_subprocess`, `ec2_ssm` | None (`package_install=False`) | Base ABC raises | Unchanged |

- **Undeclared ecosystem.** Each implementing handle first checks `ecosystem not in
  self._capabilities.package_ecosystems` and raises `SandboxCapabilityError(<handle>, "package_ecosystem:<e>")`.
- **Kill on timeout or cancellation (`docker`, `kubernetes`).**
  - In `_exec` (`docker.py:66-83`, `kubernetes.py:118-163`), both `asyncio.TimeoutError` and
    `asyncio.CancelledError` run the kill:
    `asyncio.wait_for(<exec ProcessKiller.argv(marker)>, ProcessKiller.KILL_TIMEOUT_SECONDS)`, where `marker` is
    the one the timed-out exec carried. It swallows any failure with one warning as today.
  - Then `TimeoutError` becomes `SandboxTimeoutError`, and `CancelledError` is re-raised.
  - Supported Pythons are 3.12 and 3.13. On both, `asyncio.wait_for` cancels the awaited coroutine in the same task
    and waits for its handler to finish before raising. So a backstop cancellation completes the kill while
    `_lock_for(...)` (`worker.py:82`) is still held.
  - The two `_exec` methods stay separate. They already mirror each other and differ only in transport (Docker
    `exec_run` against the Kubernetes stream API), and unifying them is outside #692.
- **Install timeout on `e2b` and `daytona`.** Installs now pass the effective timeout to `execute_command`, which
  hands it to the SDK's native command timeout:
  - `e2b`: `commands.run(timeout=...)` (`e2b.py:59`);
  - `daytona`: `process.exec(timeout=...)` (`daytona.py:62`).
  - Today their installs pass none (`e2b.py:66`, `daytona.py:67`).
  - The native timer now always fires before the backstop, so each handle maps its SDK's timeout error to
    `SandboxTimeoutError` (`e2b.exceptions.TimeoutException` from `run_code` / `commands.run`;
    `daytona.common.errors.DaytonaTimeoutError` from `code_run` / `exec`). Unmapped, a timeout would complete
    as `failed` with the SDK's error type instead of `timed_out`.
- **Self-timing handles benefit from the backstop.** Today the worker's outer timer and a self-timing handle's timer
  share one value. The outer timer starts first, so it fires first and cancels the handle before its own kill runs.
  The grace period fixes that for every self-timing handle:
  - `local_subprocess`, which kills the process group on its own `TimeoutError` (`local_subprocess.py:65-68`);
  - `ec2_ssm`, which cancels the SSM command (`ec2_ssm.py:112-114`).
- **Phase 2: the runtime argv.** `docker` and `kubernetes` look up `language_runtimes[language]`. An undeclared
  language raises `SandboxCapabilityError` from the instance-capability check before the lookup. The interpreter is
  always argv[0], and the submitted code is always the last argument.
- **Why `e2b` and `daytona` get no runtimes.**
  - `e2b` runs code in a kernel chosen by `template` (`e2b.py:115`).
  - `daytona`'s SDK fixes the code language per sandbox, not per call.
  - Both keep `languages=["python"]`. This is a design non-change.

### Consumer changes

- **`ExecutionManager`** (`sandbox/manager.py`):
  - **New `install_packages`:**
    ```python
    async def install_packages(self, packages: list[str], *, ecosystem: str = "python", profile: Optional[str] = None,
                               sandbox_session_id: Optional[str] = None, wait: Optional[float] = None
                               ) -> Union[SandboxResult, SandboxTask]:
    ```
    It submits `install_packages` with the payload `{"packages": packages, "ecosystem": ecosystem}` through
    `_submit_op`.
  - **`_submit_op` order** (`manager.py:228-279`):
    1. resolve the profile name and config (unchanged);
    2. `policy = self._policy_from(profile_cfg)`;
    3. **+** `self._guard.check_operation(operation, payload, policy, context)`. `context` holds:
       - the profile;
       - the agent (`_current_agent_name()`);
       - the AK session id (`_current_session_id()`);
       - the sandbox session id: the explicit id, `default:<profile>` for `per_session`/`per_runtime`, or `""` for
         `per_call`.
    4. **+** `self._validate_payload(operation, payload, profile_cfg)`. For `install_packages` this runs the spec
       validation (below), and it is a no-op for every other operation;
    5. `_resolve_session`, `_resolve_principal`, build the request with the same `policy` object, then submit
       (unchanged).
    - A denial or a rejected spec therefore leaves no side effect: no idle teardown, no registry write and no
      submit.
  - **Agent-side spec validation.** `_installer_for(profile_cfg)` returns the `PackageInstaller` for the profile's
    provider block, cached per profile.
    - When the block is a `_SandboxProviderPackageConfig` (`docker`, `kubernetes`, `e2b`, `daytona`), the installer
      validates with the agent's copy of that block.
    - For any other provider, only the baseline runs agent-side, and the handle's validation in the worker decides.
  - **`_policy_from`** (`manager.py:331-343`) also copies the two new fields:
    - `languages=list(p.languages) if p.languages is not None else None`;
    - `package_install=PackageInstallPolicy(ecosystems=list(...), timeout=...)` when the block is present, else
      `None`.
  - **Config warnings.** `__init__` (`manager.py:38-43`) calls `_warn_permission_config(config)`. The manager is a
    singleton, so each warning fires once per profile per process (`_reset()` rebuilds it). The method warns on
    `ak.sandbox`:
    - `package_install` with `scope: per_runtime`, because an install changes a sandbox that every AK session on the
      runtime shares;
    - `package_install` with `network_egress: deny`, because an install then needs a mirror inside the image;
    - `package_install` on a `docker` or `kubernetes` profile with `fs_allow_read` or `fs_allow_write`. The root
      filesystem is then read-only (`docker.py:176-178`, `kubernetes.py:308-311`). The warning names the fix: a
      `--target` prefix pointing into the workdir, with that path on the image's `PYTHONPATH`.
- **Tools** (`sandbox/tools.py`):
  - **New tool:**
    ```python
    async def install_packages(packages: list[str], ecosystem: str = "python",
                               sandbox_session_id: Optional[str] = None, profile: Optional[str] = None) -> str:
    ```
    It follows the `run_code` contract (`tools.py:64-88`):
    - the disabled check;
    - `wait = sandbox.broker.wait_timeout`;
    - `_outcome_json` for a result or a pending task;
    - `_error_json` plus a `WARNING` on `ak.sandbox.tools` on failure.
    - The function is named `install_packages` so that `func.__name__ == SystemTool.name`, because tool builders
      bind by `func.__name__`.
  - **Conditional registration.** `get_sandbox_tools()` (`tools.py:309-358`) appends
    `SystemTool(name="install_packages", description="", func=install_packages)` only when some profile has
    `policy.package_install is not None`. The other eight tools are unchanged. The decision is derived from config
    only, with no provider import.
  - **Guidance.**
    - `_profiles_text` (`tools.py:287-306`) appends each profile's permissions:
      - `languages: python, bash` when `policy.languages` is set;
      - `run_code disabled (command-only profile)` when it is `[]`;
      - `package installs: python, node` or `package installs not permitted`.
    - The tool list gains an `install_packages(...)` line only when the tool is registered.
    - One new sentence: `If a result says an action is not permitted by the profile, report it to the user; do not
      work around it with run_command or run_code.`
  - **Startup check.** `get_sandbox_tools()` calls `PackageSpecRuleFactory.validate_config(config)` first, so an
    unresolvable rule fails agent construction.
  - **Name collision.** A user tool named `install_packages` now collides with the system tool when it is
    registered. `Agent._warn_on_tool_name_collisions` (`core/base.py:709`) already reports this.
- **Verified unchanged:** `SandboxPreHook`, every other tool, `BrokerWireCodec`, `EmbeddedBroker`, and the
  `destroy` path. `_destroy_backend` sends `SandboxPolicy()`, which carries no permission fields and is never gated.

### Config changes (`core/config.py`)

- **Reused whole:**
  - `_SandboxPolicyConfig` (`config.py:724-736`) is extended in place. There is no parallel `permissions` block and
    no `enabled` flag.
  - The `docker`, `kubernetes`, `e2b` and `daytona` blocks subclass the new mixins rather than copying their fields.
- **New on `_SandboxPolicyConfig`** (phase 1). Readers: the guard (through the wire copy), tool registration and
  guidance, the manager's warnings, and the worker's mismatch warning.
  ```python
  languages: Optional[list[str]] = Field(default=None, description="Languages run_code may use under this profile; "
      "omitted = whatever the provider declares; [] = no run_code (command-only profile)")
  package_install: Optional[_SandboxPackageInstallConfig] = Field(default=None, description="Permit install_packages "
      "under this profile; omitted = installs denied")
  ```
  - `languages` cannot be derived from existing config: today the provider declares languages, and nothing in config
    narrows them.
  - `package_install` cannot be derived either: nothing in config expresses permission to install.
- **New model** (phase 1):
  ```python
  class _SandboxPackageInstallConfig(BaseModel):
      ecosystems: list[str] = Field(default_factory=lambda: ["python"], min_length=1, description="Package ecosystems "
          "installs may use (e.g. python, node); each must be declared by the provider's package_installers")
      timeout: Optional[float] = Field(default=None, gt=0, description="Wall-clock limit in seconds for one install; "
          "omitted = policy.timeout")
  ```
  - `ecosystems: []` fails at config load with a pydantic `ValidationError`.
  - `timeout` is needed because the install's wall clock differs from the `run_code` limit (`config.py:735`), which
    is sized for code.
- **New validator on `_SandboxProfileConfig`** (`config.py:845`): a `model_validator(mode="after")` rejects
  `environment == "attached"` combined with `policy.package_install is not None`.
- **New mixin, phase 1: `_SandboxProviderPackageConfig`.** It is subclassed by `_SandboxDockerConfig`,
  `_SandboxKubernetesConfig`, `_SandboxE2BConfig` and `_SandboxDaytonaConfig`. `PackageInstaller.from_config` reads
  it.
  ```python
  package_installers: dict[str, list[str]] = Field(default_factory=lambda: {"python": ["pip", "install"]},
      description="Ecosystem -> installer argv prefix the image provides; the keys are the provider's declared ecosystems")
  package_rules: dict[str, str] = Field(default_factory=dict,
      description="Ecosystem -> dotted path of a PackageSpecRule subclass validating that ecosystem's package specs")
  ```
  - A `field_validator` requires every argv prefix to hold at least one token, and no token to be empty.
  - Both fields cannot be derived from anything else, because only the operator's image decides which installers
    exist.
  - **Declaring `package_installers` replaces the default map; it is not merged with it.** An operator who adds
    `node` restates `python`. An image with no `pip` may legitimately omit `python`. The worker's mismatch warning
    then names any profile that still permits it.
- **New mixin, phase 2: `_SandboxProviderRuntimeConfig`.** It is subclassed by `_SandboxDockerConfig` and
  `_SandboxKubernetesConfig`. Those two providers read it to build their runtime map and instance `languages`.
  ```python
  language_runtimes: dict[str, list[str]] = Field(default_factory=lambda: {"python": ["python", "-c"]},
      description="Language -> interpreter argv prefix the image provides; the code is appended as the last argument")
  ```
  - One validator requires a `python` key, because the provider contract makes Python mandatory
    (`sandbox/testing.py:162`).
  - A second validator requires every argv prefix to hold at least one token and no empty token.
- **Single-backend sugar has no `policy` field** (`config.py:908-955`), so enabling installs or narrowing languages
  requires a `profiles` block. This is unchanged.
- **Existing YAML and `AK_*` variables:**
  - Every new field defaults to today's behaviour, except the deliberate denial of raw `install_packages` requests
    (Behavioural change 1).
  - The new env forms follow the existing nesting:
    - `AK_SANDBOX__PROFILES__<NAME>__POLICY__PACKAGE_INSTALL__ECOSYSTEMS='["python","node"]'`;
    - `AK_SANDBOX__PROFILES__<NAME>__DOCKER__PACKAGE_INSTALLERS='{"python":["pip","install"]}'`.
  - Because the block is presence-enabled, any `...__POLICY__PACKAGE_INSTALL__*` variable materializes the block
    and permits `python` installs. The docs say so, as they do for `thread`.

### Wire compatibility

| Pairing | Result |
|---|---|
| Old agent to new worker | `SandboxPolicy.package_install` is absent, so it decodes as `None` and installs are denied. `languages` is absent, so it is `None` and today's behaviour holds. |
| New agent to old worker | The old worker drops the unknown policy fields (`extra="ignore"`). It passes only `payload["packages"]` (`worker.py:220`), so a permitted non-`python` install runs as `pip install`. It ignores `package_install.timeout`. The agent-side guard and validation keep every install permitted and well-formed. |
| New worker to old agent | `SandboxPermissionDeniedError` is unknown to the old agent's `errors` module and degrades to `ExecutionBrokerError` (`broker/queue.py:162-165`). The request is still denied. |

**Rollout rule:** upgrade queue workers before agent pods. The docs state it.

### Behavioural changes

All of these are intentional.

1. **Raw `install_packages` requests are denied.** Today a raw request runs with no permission check
   (`worker.py:220`). Now it is denied unless the profile declares `package_install`. This closes #692's gap.
2. **The `Sandbox.install_packages` signature changes** to `(packages, ecosystem="python", timeout=None)`, and the
   worker passes both by keyword. One-argument bring-your-own overrides keep working for one minor release through
   the shim, which logs one deprecation warning per class. The shim is removed in the following minor release, and
   the release notes say so.
3. **Every worker operation's outer timer becomes effective timeout + 10 s.** This covers all operations, not only
   installs, so a hung handle is reported up to 10 s later than today.
4. **Timed-out handles are now killed instead of left running** after the worker gives up:
   - a timed-out `execute_code`, `execute_command` or install on `docker` and `kubernetes` is killed (best-effort);
   - `local_subprocess` now kills its process group;
   - `ec2_ssm` now cancels its command.
5. **The kill works on images without procps, targets only the timed-out exec, and runs only in managed
   sandboxes.** The `docker` and `kubernetes` kill now uses a `/proc` scan for the exec's environment marker instead
   of `pkill` by name, so it works on the default image, where today it does nothing, and it spares same-named
   processes from earlier execs. It skips PID 1, and it never runs when the provider's `attach_to` is set. Today
   `pkill` would kill matching processes in an attached container whose image ships procps.
6. **`e2b` and `daytona` installs now run under the effective timeout through their SDK's native command timeout.**
   Today they run with none.
7. **`e2b` and `daytona` build install commands with `PackageInstaller` (`shlex.join`).** The command for a valid
   spec is byte-identical to today's `shlex.quote` join. For example, `pip install requests httpx` matches the
   existing test assertion at `tests/test_sandbox_providers.py:950-951`. URL, VCS, path and archive specs are now
   rejected on all four installing providers.
8. **Guard denials log the guard's warning instead of the generic one** on `process()` and the thread flavor. Every
   other failure, including other `SandboxPolicyError`s, keeps the generic warning.
9. **The queue client's ceiling check now uses the operation's effective timeout.** An install whose
   `package_install.timeout` exceeds `worker_timeout_ceiling` is rejected at submit. Every other operation is checked
   exactly as today.
10. **New tool.** Agents on a deployment where some profile permits installs see a ninth tool, `install_packages`.
11. **Instance capability overrides re-validate** through `SandboxCapabilities.derive`. The kubernetes
    `policy_network` flip produces the same capabilities as before.

**Non-changes:**

- `BrokerOperation`, `ExecutionRequest`, `ExecutionCompletion`, `BrokerWireCodec` and the response-store record
  format.
- The `docker`/`kubernetes` install argv `["pip", "install", ...]` (`tests/test_sandbox_providers.py:327-328` and
  `1638-1642`). On `kubernetes` a killable exec is launched through `ProcessKiller.wrap`, so the stream API receives
  the launcher followed by that unchanged argv.
- Every existing public export.
- The `_enforce_policy` and `_check_principal` behaviour and their warnings.
- The default `languages` of every provider.
- `local_subprocess` and `ec2_ssm` keep `package_install=False`.
- Data written before the change (nv_cache registries and stored completions) reads back identically, because no
  persisted model gains a required field.

### Documentation

`docs/docs/advanced/sandbox.md` gains the following. The design requires each item.

- **A "Package installation" section**, covering:
  - the `package_install` block and its presence-enabled semantics, including the env-var materialization note;
  - `package_installers` and `package_rules`, and the replace-not-merge rule;
  - the `install_packages` tool;
  - the `python` and `node` grammars, and the bring-your-own `PackageSpecRule` example.
- **A per-posture table** of which ecosystems can install and which argv prefix to configure:

  | Posture | `python` | `node` |
  |---|---|---|
  | `network_egress: deny` | Offline only: `[pip, install, --no-index, --find-links, /wheels]` over wheels baked into the image | Offline only: `[npm, install, --offline]` over a cache baked into the image |
  | Read-only root filesystem (`docker`/`kubernetes` with a filesystem policy) | `[pip, install, --target, /workspace/site]`, with `/workspace/site` on `PYTHONPATH` | `[npm, install, --cache, /workspace/.npm]` (a local install into the writable workdir) |
  | Non-root or PSA-restricted image | `[pip, install, --target, <writable dir>]` or `[pip, install, --user]` with a writable `HOME` | Local installs work; avoid `-g` |

- **Language runtimes (phase 2):** `language_runtimes`, `policy.languages`, and command-only profiles
  (`languages: []`).
- **Permissions versus capabilities, and what permissions do not gate.** This covers `run_command`, `subprocess`
  inside `run_code`, and self-provisioned tooling such as `pip install playwright` with network egress.
- **The hardening recipe:** `deny` plus a mirror or a pre-baked image. `allowlist` on `e2b`/`daytona` is added to
  the recipe only after the live egress test passes.
- **Per-provider `network_egress` enforcement**, following the design's list.
- **The upgrade rule:** workers before agents.
- **Install timeouts:**
  - Install time counts against `package_install.timeout` plus the 10 s backstop.
  - A queue transport's redelivery window (`ack_wait` or visibility timeout) must exceed that total. Otherwise the
    install is redelivered and re-runs (`broker/queue_worker.py:152-156`).
- **The kill's best-effort limits** from [ProcessKiller](#processkiller) (it targets only the timed-out exec and
  its children), and the rule that a timed-out process in an attached container (`attach_to`) is not killed.
- **The migration step for bring-your-own `Sandbox` subclasses:** the new signature, and the shim's one-release
  window. The same text goes into the release notes.

## Error handling

| Failure | Raised as | Where it surfaces | Logged |
|---|---|---|---|
| Operation not permitted | `SandboxPermissionDeniedError` | Tool `{"error": ...}`; queue flavor re-raises it by name | Once by the guard on `ak.sandbox.broker`, plus the tools' warning on `ak.sandbox.tools` |
| Permitted, but the provider does not declare it (language, ecosystem, or install at all) | `SandboxCapabilityError` from the handle | Tool error | The generic warning; plus the worker's one-time mismatch warning per (provider, profile) |
| Rejected package spec | `ValueError` (index and rule only) | Tool error, before submit agent-side; again in the handle | The tools' warning only |
| Unresolvable or missing rule, or a rule class that is not a `PackageSpecRule` | `SandboxConfigError` | Agent construction (`get_sandbox_tools`) or `QueueBrokerWorker` startup | Startup traceback |
| Empty argv prefix, `ecosystems: []`, `attached` + `package_install`, or no `python` runtime (phase 2) | pydantic `ValidationError` | `AKConfig` load | Startup traceback |
| Install exceeds its effective timeout | `SandboxTimeoutError` from the handle, after a best-effort kill | Tool error; `timed_out` completion | `process()`'s existing timed-out warning |
| Handle hangs past the backstop | `SandboxTimeoutError` (backstop) | The same | The same |
| Installer exits non-zero | No exception: `SandboxResult(exit_code != 0)` | Tool result JSON | None |
| Legacy one-argument override asked for a non-`python` ecosystem | `SandboxCapabilityError` | Tool error | The generic warning |

## Testing

New test files:

- **`tests/test_sandbox_permissions.py`** covers the guard, the worker wiring and the manager:
  - one test per deny rule, asserting the raised type and exactly one `caplog` record on `ak.sandbox.broker`;
  - that no code or package text appears in that record;
  - allowed-path tests for `run_code` (languages `None`, listed, and `[]` denying) and for `install_packages`;
  - an agent-side denial before submit: the broker's `submit` is never called, and an idle-expired session is not
    torn down;
  - one warning per denial on `process()` and on `ThreadBroker._handle`, while `_enforce_policy` and
    `_check_principal` denials still log the generic warning;
  - the mismatch warning fires once per (provider, profile), and does not suppress, nor get suppressed by, the
    non-strict `_enforce_policy` warning;
  - the legacy shim: a one-argument override runs a `python` install and logs one deprecation warning across two
    calls, and a `node` request on it raises `SandboxCapabilityError`;
  - the manager's three config warnings each fire once per profile;
  - effective timeout: an install uses `package_install.timeout` when set and `policy.timeout` otherwise. The
    backstop equals that plus `BrokerWorkerCore.BACKSTOP_GRACE_SECONDS`, which is patched low (patch target
    `agentkernel.sandbox.broker.worker.BrokerWorkerCore.BACKSTOP_GRACE_SECONDS`).
  - Tests use a test-local package-capable provider subclassing `FakeSandboxProvider`, through the existing
    `_install_sandbox_cfg` / `_sandbox_cfg` helper pattern (`tests/test_sandbox.py:124`, `tests/test_sandbox.py:135`).
- **`tests/test_sandbox_packages.py`** covers spec validation and rule resolution:
  - every baseline rejection;
  - every accept and reject case of the `python` and `node` rules, including `dist/x.whl`, `sub/pkg`,
    `user/repo`, `github:a/b`, `pkg@file:x` and one entry per archive suffix;
  - error messages never contain the entry;
  - `argv()` and `command()` shapes;
  - a bring-your-own rule resolves from `package_rules`;
  - a non-`PackageSpecRule` class or a bad path raises `SandboxConfigError`;
  - a permissive bring-your-own rule for `python` still loses to the baseline and to the built-in rule;
  - `validate_config` raises for a key with no rule.
- **`tests/test_sandbox_egress_live.py`** is the live test that gates the allowlist recipe.
  - It is env-gated by `AK_TEST_SANDBOX_EGRESS=1` plus `E2B_API_KEY` / `DAYTONA_API_KEY`, and skipped otherwise, on
    the `test_transport_contract_live.py` pattern.
  - With `network_egress: allowlist`, a sandbox reaches a listed registry host and cannot reach an unlisted one.

Existing test files that change:

- **`tests/test_sandbox.py`:**
  - `SandboxCapabilities` derivation:
    - ecosystems imply `package_install`;
    - a legacy `package_install=True` maps to `["python"]`;
    - an explicit `False` with ecosystems raises;
    - `derive()` re-validates.
  - Config:
    - an empty argv prefix is rejected;
    - `ecosystems: []` is rejected;
    - `attached` + `package_install` is rejected;
    - `languages: []` loads;
    - an omitted `ecosystems` gives `["python"]`;
    - phase 2: `language_runtimes` without `python` is rejected.
  - Tool registration: `install_packages` is present only when a profile permits it, `func.__name__` equals the
    tool name, and the guidance text shows the per-profile permissions.
  - `test_model_capabilities_defaults` (`tests/test_sandbox.py:158-175`) gains `package_ecosystems == []`.
- **`tests/test_sandbox_providers.py`:**
  - The existing install assertions stay unchanged and must pass: `docker` at 327-328, `e2b` at 950-951, `daytona`
    at 1276-1277 and `kubernetes` at 1638-1642.
  - New:
    - an undeclared ecosystem raises;
    - `package_installers` with `node` declares the ecosystem on the instance;
    - a timed-out install and a timed-out `execute_code` on `docker` and `kubernetes` run
      `ProcessKiller.argv(marker)` with the marker the exec carried, and so does a cancellation;
    - with `attach_to` set, a timed-out exec raises `SandboxTimeoutError`, carries no marker and sends no kill;
    - the `ProcessKiller` script skips PID 1 and its own `$$`; on a real `/proc` it kills a target launched through
      `wrap()` and spares a same-named process without the marker;
    - phase 2: a `language_runtimes` entry drives `execute_code`'s argv and the instance `languages`.
  - The kill assertions at `tests/test_sandbox_providers.py:346` and `:1675` move from `pkill` to the
    `ProcessKiller.argv(marker)` shape. The fake container records each exec's `environment`. The fake cluster
    strips the `wrap()` launcher and records the marker, so existing argv assertions stay unchanged, and its exec
    handler, which recognises `pkill` today (`tests/test_sandbox_providers.py:1422`), learns the new script.
- **`tests/test_sandbox_queue_broker.py`:**
  - `SandboxPermissionDeniedError` round-trips by name;
  - the ceiling test (`:332-335`) is unchanged; an install-timeout ceiling case is added;
  - `QueueBrokerWorker` fails at startup on an unresolvable rule.
- **`sandbox/testing.py` (`SandboxProviderContract`):** `test_contract_capability_honesty` gains a check that, when
  `package_install` is declared, `install_packages(["pip-noop"], ecosystem="definitely-not-an-ecosystem")` raises
  `SandboxCapabilityError`.
  - The contract requires the new signature immediately. A bring-your-own provider whose handle keeps the
    one-argument override fails this check with `TypeError`. The worker's shim covers runtime only, not
    conformance.

Run the suite with `cd ak-py && uv run pytest tests/test_sandbox*.py`, then run the full `uv run pytest`.

## Requirement trace

| design.md requirement | Spec section | Phase |
|---|---|---|
| Installs off by default; languages stay provider-declared and `policy.languages` only narrows | Config changes; SandboxPermissionGuard | 1 |
| The policy is checked on every operation, before acquire | BrokerWorkerCore changes | 1 |
| `SandboxPermissionDeniedError`, defined in `errors.py` | Errors | 1 |
| One `WARNING` per denial on `ak.sandbox.broker`; the generic warnings at two sites skip it | SandboxPermissionGuard; BrokerWorkerCore; Thread and queue flavors | 1 |
| No audit-only mode | SandboxPermissionGuard (no such branch) | 1 |
| Permission and capability are separate; the mismatch warning reuses `_policy_warned` | Governing rules 1–2; BrokerWorkerCore | 1 |
| Permissions do not gate the environment; docs per posture and per provider | Documentation | 1 |
| Trust model: the worker enforces the agent-resolved policy | Governing rule 1 | 1 |
| The tool is registered only when permitted; guidance lists permissions | Consumer changes (Tools) | 1 |
| Guard class, its inputs and the ungated operations | SandboxPermissionGuard | 1 |
| Guard in the worker (authoritative) and in the manager (defence in depth) | BrokerWorkerCore; Consumer changes (`ExecutionManager`) | 1 |
| Policy fields; presence-enabled block; `ecosystems` default and the `[]` rejection; `timeout` | Config changes; Wire and capability models | 1 |
| `attached` rejected; `per_runtime` warns | Config changes; Consumer changes (`ExecutionManager`) | 1 |
| `_policy_from` copies the new fields | Consumer changes (`ExecutionManager`) | 1 |
| `ProviderPackageConfig`: installers, rules, rule coverage, non-empty argv | Config changes; Package validation | 1 |
| `ProviderRuntimeConfig`: runtimes, `python` key, non-empty argv | Config changes; Provider changes | 2 |
| `SandboxCapabilities.package_ecosystems` and the derivation validator | Wire and capability models | 1 |
| Wire compatibility and the rollout rule | Wire compatibility; Documentation | 1 |
| Runtime argv on `docker`/`kubernetes`; instance capability checks | Provider changes | 2 (argv); 1 (instance checks) |
| Guard language rule | SandboxPermissionGuard | 1 |
| `install_packages` signature; the handle owns the timeout; backstop; kill on cancellation | Sandbox ABC; BrokerWorkerCore; Provider changes; ProcessKiller | 1 |
| `PackageInstaller`, `PackageSpecRule`, baseline, `python`/`node` rules, bring-your-own resolution, agent-side validation | Package validation; Consumer changes (`ExecutionManager`) | 1 |
| Invocation: argv for `docker`/`kubernetes`, `shlex.join` for `e2b`/`daytona` | Provider changes | 1 |
| Install guard rules; manager `install_packages`; the new tool | SandboxPermissionGuard; Consumer changes | 1 |
| `deny` and filesystem-policy warnings | Consumer changes (`ExecutionManager`) | 1 |
| Behaviour changes, including the bring-your-own shim and release notes | Behavioural changes; BrokerWorkerCore; Documentation | 1 |
| Contract check, guard, installer, config, timeout, handle, worker and manager tests; the live test | Testing | 1 (2 for the runtime cases) |
