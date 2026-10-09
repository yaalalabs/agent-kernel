# #749 (phase 2): Resolve secrets from Kubernetes Secrets mounted into the pod — Implementation Spec

Adds `KubernetesSecretProvider`, a stdlib-only built-in `SecretProvider` (short name `kubernetes`)
that reads an environment-variable-style key such as `OPENAI_API_KEY` from the one file of that name
among the Kubernetes Secrets mounted at `<mount_path>/<secret-name>/` (default
`/var/run/secrets/agentkernel`). Phase 1's `SecretManager` is untouched: environment, then cache,
then provider. The provider never calls the API server. The config gains one per-backend block,
`secret.provider.kubernetes.mount_path`. The Helm chart gains one opt-in `secretStore` value that
mounts each listed Secret, read-only and whole, into the one tier that executes agents.

[`design.md`](design.md) is the requirements source. This spec holds the implementation detail
(helper names, exact error strings, volume naming, tests and CI steps) that the design leaves out;
see [Changes from design.md](#changes-from-designmd) for the refinements made here.

## Design

### Package layout

```
ak-py/src/agentkernel/secret/
├── __init__.py          # + KubernetesSecretProvider export
├── factory.py           # + "kubernetes" branch, _BUILTIN_SECRET_PROVIDERS
└── providers/
    └── kubernetes.py    # NEW: KubernetesSecretProvider
```

`base.py`, `cache.py`, `errors.py`, `manager.py`, `testing.py`, `providers/env.py` and
`providers/aws_ssm.py` do not change.

### `secret/providers/kubernetes.py` — `KubernetesSecretProvider`

```python
"""KubernetesSecretProvider — Kubernetes Secrets mounted into the pod as files.

Each Secret is its own volume at {mount_path}/{secret-name}/, one file per data key. The key
OPENAI_API_KEY is read from the one file of that name across the mounted Secrets.
"""

class KubernetesSecretProvider(SecretProvider):
    """Kubernetes Secrets mounted as volumes under mount_path; never calls the API server."""

    _log = logging.getLogger("ak.secret.provider.kubernetes")

    def __init__(self, mount_path: str) -> None:
        """:raises AKConfigError: If mount_path is empty or not absolute. Touches no file."""

    @classmethod
    def create(cls, config: _SecretConfig) -> "KubernetesSecretProvider":
        """Build from `secret.provider.kubernetes.mount_path`."""
        return cls(mount_path=config.provider.kubernetes.mount_path)

    def get_secret(self, key: str) -> Optional[str]:
        """Return the content of the one file named `key` under mount_path, or None if there is none.

        :raises ValueError: If key is not a single, non-hidden path component.
        :raises SecretError: If mount_path is missing or not a directory, the key exists in more
                             than one place, or a file cannot be listed, read or decoded.
        """

    def _find_candidates(self, key: str) -> list[str]: ...   # lists mount_path once
    def _read(self, path: str) -> Optional[str]: ...          # None when the file vanished
```

**Rules:**

1. **Construction does no I/O.** `__init__` checks `mount_path` only as a string: `""` or a
   relative path (`not os.path.isabs(mount_path)`) raises `AKConfigError` naming
   `secret.provider.kubernetes.mount_path`. The path is stored as given; it is not resolved or
   normalized. A missing mount therefore fails at the first `get_secret`, not at
   `SecretManager.current()`. This keeps the baremetal/eks CI flavors green (see
   [Examples and docs](#examples-and-docs)).
2. **The key is checked again in the provider.** `get_secret` raises `ValueError` when `key` is
   empty, starts with `.`, or contains `/` or `os.sep`. `SecretManager._validate_key`
   (`secret/manager.py:103-106`) already rejects all of these. The provider repeats the check
   because the class is exported and callable without the manager. With the check, "a key can
   never address a path outside `mount_path`" holds for every caller, not only manager callers.
3. **Candidate discovery** (`_find_candidates`), one `os.scandir(mount_path)` per call:
   - entries whose name starts with `.` are skipped (`..data`, `..<timestamp>`);
   - an entry named `key` for which `entry.is_file()` is true is a top-level candidate,
     `<mount_path>/<key>`;
   - for every other entry where `entry.is_dir()` is true, `<mount_path>/<entry>/<key>` is a
     candidate when `os.path.isfile` is true for it;
   - both `is_file`/`is_dir` and `os.path.isfile` follow symlinks. The kubelet layout,
     `<dir>/KEY -> ..data/KEY` and `..data -> ..<timestamp>`, therefore resolves to the current
     revision. **A candidate is a path that resolves to a regular file.** A directory with the
     key's name is never a candidate; a directory at the top level is searched as a Secret
     directory instead.
   - No level deeper than `<mount_path>/<dir>/` is searched.
4. **The decision is made on the candidate count, before any file is read.** Zero candidates is a
   miss (`None`). Two or more raise `SecretError` naming every candidate path, sorted. One
   candidate is read. As a result, an empty file and a non-empty file with the same key are still
   a duplicate error, not "the non-empty one wins".
5. **Reading** (`_read`): `open(path, "rb")`, then `bytes.decode("utf-8")`, returned verbatim with
   no strip and no base64. An empty file returns `None`, matching `EnvSecretProvider`
   (`secret/providers/env.py:13`). If the file vanished between discovery and `open`
   (`FileNotFoundError`, for example a key removed by a rotation in flight), the result is a miss
   (`None`). The next `get` sees the settled state.
6. **No memo of where a key lives.** Every call re-lists `mount_path`. A Secret added or removed by
   a rollout, or a key moved between Secrets, is picked up with no stale state.
7. **No mutable state and no lock.** The only attribute is the immutable `mount_path` string, so
   concurrent calls from `ThreadRunner` consumer threads or several event loops are safe by
   construction. This meets the ABC's "must tolerate concurrent calls" (`secret/base.py:25`).
8. **`secret.prefix` is not read.** The pod's mounts are the deployment scope.
9. **Silence.** Log records and exception messages carry the key, `mount_path` and candidate paths
   only, never file contents. A miss logs at DEBUG: `"No file named %s under %s"`.

**Per-operation cost**, accepted: an uncached `get` costs one `scandir` of `mount_path`, plus one
`stat` per mounted Secret directory, plus one `open`/`read` on a hit. All are local filesystem
calls. The hot paths are unaffected: the manager caches hits for `cache_ttl` (default 300 s), and
the phase-1 rule (resolve at startup) still applies. A miss is not cached by the manager
(`secret/manager.py:97-100`), so a repeated `get(key, default=...)` for an absent key lists the
directory each time. That cost is documented, not mitigated.

### `secret/factory.py` — `SecretProviderFactory`

```python
_BUILTIN_SECRET_PROVIDERS = ["env", "aws_ssm", "kubernetes"]
...
        if key == "env":
            ...
        if key == "kubernetes":
            from .providers.kubernetes import KubernetesSecretProvider

            return KubernetesSecretProvider.create(config)
        if key == "aws_ssm":
            ...
```

- The `kubernetes` branch goes next to `env` and has **no `require_extra`**: the module imports
  only `logging`, `os`, `typing` and AK internals.
- The unknown-name error message lists the new name through `_BUILTIN_SECRET_PROVIDERS`, with no
  separate edit.
- `get` still never calls `AKConfig.get()`.

### `secret/__init__.py`

`KubernetesSecretProvider` is added to the imports and `__all__`. It is stdlib-only, so an eager
import pulls in no SDK. It joins `EnvSecretProvider` in the export list; `AWSSMSecretProvider`
stays unexported because it imports `boto3`. With the export, a caller can build
`SecretManager(provider=KubernetesSecretProvider("/run/secrets"))` without config.

### Consumer changes

**None.** No AK entrypoint (`AgentRunner.run()`, `IOHandler.run()`, `WebSocketGateway.run()`) calls
`SecretManager`. The provider is reached only from application code that calls
`SecretManager.current().get(...)`, as in phase 1.

### Config changes

**Reuse audit.** The existing `_SecretConfig` (`core/config.py:911-924`) is reused whole:
`provider.type` selects the backend and `cache_ttl` is the rotation-pickup window. `prefix` exists
but is not read. `_SandboxKubernetesConfig` (`core/config.py:737`) configures where sandbox pods are
created (namespace, image, kubeconfig), and none of its fields is a filesystem path for secrets.
Reusing it would couple two unrelated concerns.

One new model, placed directly before `_SecretProviderConfig` (`core/config.py:902`):

```python
class _SecretKubernetesConfig(BaseModel):
    mount_path: str = Field(
        default="/var/run/secrets/agentkernel",
        description="Absolute directory the Kubernetes Secrets are mounted under, one subdirectory per Secret "
        "(<mount_path>/<secret-name>/<KEY>); a key file directly under mount_path is also read. The Helm chart's "
        "secretStore mounts under the default, so set this only for Secrets mounted outside the chart, e.g. by the "
        "Secrets Store CSI driver or as Docker / Compose secrets (/run/secrets). Read only by the kubernetes provider",
    )
```

`_SecretProviderConfig` gains one field, and the description of its `type` field changes:

```python
class _SecretProviderConfig(BaseModel):
    type: str = Field(
        default="env",
        description="Secret backend: a built-in short name (env, aws_ssm, kubernetes) or a dotted path to a "
        "SecretProvider subclass. 'env' reads the environment variable named by the key. 'aws_ssm' is AWS SSM "
        "Parameter Store and requires secret.prefix. 'kubernetes' reads one file per key from the Kubernetes Secrets "
        "mounted under secret.provider.kubernetes.mount_path. A set, non-empty environment variable named by the key "
        "always wins over the provider.",
    )
    kubernetes: _SecretKubernetesConfig = Field(
        default_factory=_SecretKubernetesConfig, description="Settings of the kubernetes secret provider"
    )
```

`_SecretConfig.prefix` keeps its value and changes its description ending from
`"Required by aws_ssm; ignored by env"` to `"Required by aws_ssm; ignored by env and kubernetes"`.

| Field | Reader | Why it cannot be derived |
|---|---|---|
| `secret.provider.kubernetes.mount_path` | `KubernetesSecretProvider.create` → `__init__` | No existing field names a filesystem location for secrets, and the mount location is decided by whoever writes the pod spec. The chart mounts under the default, so the field matters only for hand-written or third-party mounts. |

- **No field lists the Secrets.** The provider discovers them from the subdirectories of
  `mount_path`, so the list lives only in the chart's `secretStore.secrets`.
- **No `enabled` flag.** `secret.provider.type: kubernetes` is the opt-in.
- **Per-backend block, not a top-level field**: the `sandbox.kubernetes` shape. It is nested under
  `provider` because only this provider reads it, unlike `prefix`, which phase 1 kept top-level as
  a deployment-wide scope.

**Compatibility.**
- Every new field has a default, and the default provider stays `env`. Existing `config.yaml`
  files and `AK_*` variables parse unchanged and keep their meaning.
- The new env var is `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH`. Because of `env_ignore_empty=True`
  (`core/util/config_yaml_util.py:190`), an empty value falls back to the default, so the
  empty-path `AKConfigError` can be reached only from YAML or code.
- Two field descriptions change (`provider.type`, `prefix`), which rewrites those two
  generated-docs entries.

### Deployment changes (`ak-deployment/ak-k8s/chart`)

**`values.yaml`**: a new top-level block after `extraEnvFrom` (`values.yaml:38-39`), next to the
other credential plumbing:

```yaml
# Kubernetes Secrets the agent-executing tier reads through the application's
# `secret.provider.type: kubernetes`. Each listed Secret (created by you, in the release namespace)
# is mounted read-only and whole at /var/run/secrets/agentkernel/<name>, so keys added to it, and
# rotated values, appear without a restart. Mounted into agent-runner, or into io in the
# single-process profile (agentRunner.enabled false, transport.type in_memory); never into
# ws-gateway or sandbox-worker. Any other combination fails the render. No RBAC is created.
# Every key of every listed Secret is readable by code in that tier: list only what agents need.
# Data keys must be the AK key name (e.g. OPENAI_API_KEY); other keys are never read.
secretStore:
  enabled: false
  # Required (at least one) when enabled.
  secrets: []
  # - name: openai-credentials
  # - name: slack-credentials
```

**`templates/_helpers.tpl`**: four new definitions. They are the single owner of the base path,
the per-Secret path and the volume names, so `volumes` and `volumeMounts` cannot drift:

```
{{- define "agent-kernel.secretStoreMountPath" -}}/var/run/secrets/agentkernel{{- end }}

{{/* "runner" | "io" | "": the one tier that executes agents in this release. */}}
{{- define "agent-kernel.secretStoreTier" -}}
{{- if .Values.agentRunner.enabled }}runner
{{- else if and .Values.ioHandler.enabled (eq .Values.transport.type "in_memory") }}io
{{- end }}
{{- end }}

{{/* Fails the render on an unusable secretStore; renders nothing. Included from configmap-env.yaml. */}}
{{- define "agent-kernel.secretStoreValidate" -}}
{{- if .Values.secretStore.enabled }}
{{- if not (include "agent-kernel.secretStoreTier" .) }}
{{- fail "secretStore.enabled needs an agent-executing tier: agentRunner.enabled, or ioHandler.enabled with transport.type in_memory" }}
{{- end }}
{{- if empty .Values.secretStore.secrets }}
{{- fail "secretStore.secrets must list at least one Secret when secretStore.enabled" }}
{{- end }}
{{- $seen := dict }}
{{- range .Values.secretStore.secrets }}
{{- if not (kindIs "map" .) }}
{{- fail (printf "secretStore.secrets entries must be objects with a name, e.g. '- name: %v'" .) }}
{{- end }}
{{- $name := required "secretStore.secrets[].name is required" .name }}
{{- if hasKey $seen $name }}
{{- fail (printf "secretStore.secrets lists '%s' more than once" $name) }}
{{- end }}
{{- $_ := set $seen $name true }}
{{- end }}
{{- end }}
{{- end }}

{{- define "agent-kernel.secretStoreVolumes" -}}      {{/* one `secret` volume per entry */}}
{{- range $i, $s := .Values.secretStore.secrets }}
- name: ak-secret-{{ $i }}
  secret:
    secretName: {{ $s.name }}
    optional: false
{{- end }}
{{- end }}

{{- define "agent-kernel.secretStoreVolumeMounts" -}} {{/* one read-only mount per entry */}}
{{- range $i, $s := .Values.secretStore.secrets }}
- name: ak-secret-{{ $i }}
  mountPath: {{ include "agent-kernel.secretStoreMountPath" $ }}/{{ $s.name }}
  readOnly: true
{{- end }}
{{- end }}
```

- No `items`, no `subPath` and no `defaultMode`: whole-Secret mounts are what make rotation and
  new keys visible, and the default `0644` keeps non-root images working.
- `ak-secret-<index>` keeps volume names inside the 63-character DNS-1123 label limit whatever the
  Secret's name (Secret names may contain `.` and run to 253 characters).
- `agent-kernel.secretStoreTier` is the single owner of the placement rule: the validate helper
  and both Deployments ask it, so the rule cannot drift between them.
- The map check runs before `.name` is read: on a bare string (`secrets: [openai-credentials]`),
  `.name` would otherwise fail with Go's "can't evaluate field name in type interface {}".

**Where validation runs.** `templates/configmap-env.yaml` includes
`agent-kernel.secretStoreValidate` once, at the top of the template, rendering nothing. That
ConfigMap renders in every release, so every misconfiguration fails `helm template`/`install`,
including a release where neither agent-executing Deployment renders. If validation lived in the
Deployments, that release would silently skip it.

**`templates/deployment-agent-runner.yaml`** (already gated on `agentRunner.enabled`, so
`secretStoreTier` is `runner` whenever it renders):
- pod `spec`, after `terminationGracePeriodSeconds` (`:33`):
  `{{- if .Values.secretStore.enabled }} volumes: {{- include "agent-kernel.secretStoreVolumes" . | nindent 8 }} {{- end }}`;
- container, after `resources` (`:63-66`): the same gate around `volumeMounts:` with
  `agent-kernel.secretStoreVolumeMounts` at `nindent 12`.

**`templates/deployment-io.yaml`**: the same two insertions, after `imagePullSecrets` (`:33-36`)
and after `resources` (`:84-87`), gated on
`{{- if and .Values.secretStore.enabled (eq (include "agent-kernel.secretStoreTier" .) "io") }}`.
That is the single-process profile (`values-dev.yaml:41-55`): `agentRunner.enabled: false` and
`transport.type: in_memory`, the only case where the io pod runs agents
(`templates/deployment-io.yaml:3-6`). With `agentRunner.enabled: false` on a broker transport the
agents run outside the release, so the io pod gets no mounts and the validate helper fails the
render instead.

- `deployment-ws-gateway.yaml` and `deployment-sandbox-worker.yaml` are not touched.
- No ServiceAccount, Role, RoleBinding or `serviceAccountName` is added.
- No `AK_SECRET__*` entry is added to the ConfigMap. The app's `config.yaml` selects the provider,
  and the chart mounts under the provider's default path.
- No checksum annotation is added for the Secrets: a Secret change must *not* roll the pods, which
  is the point.

**Rendering identity.** Every insertion is gated on `secretStore.enabled`, and the validate helper
renders nothing. With default values, `helm template` therefore produces byte-identical output for
every flavor file. [Testing → Verify](#verify-one-off-for-this-change) checks this once.

### Examples and docs

**`examples/k8s/openai-queue-mode`:**

- `config.nats.yaml` and `config.kafka.yaml` (both are baked into images by
  `deploy/package.sh:57`): append
  ```yaml
  # OPENAI_API_KEY from the environment when set, else from the Secrets the chart mounts under
  # /var/run/secrets/agentkernel (secretStore in ak-values.yaml).
  secret:
    provider:
      type: kubernetes
  ```
- `ak-values.yaml`: replace the `extraEnv` block (`:17-22`) with
  ```yaml
  secretStore:
    enabled: true
    secrets:
      - name: openai-credentials
  ```
  and update the header comment (`:1-3`) from "the OpenAI key" to "the OpenAI credentials Secret".
- `app_agent_runner.py`: import `set_default_openai_key` from `agents` and `SecretManager` from
  `agentkernel.secret`. Call `set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))`
  before the `Agent(...)` definitions, with the comment shape of
  `examples/aws-serverless/openai/lambda_agent_runner.py:6-8`.
- `app_io_handler.py` and `app_ws_gateway.py` do not change; neither reads `OPENAI_API_KEY`.
- `README.md`:
  - `:19` updates the `ak-values.yaml` description.
  - `:59` becomes
    `kubectl create secret generic openai-credentials --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"`.
  - A new *Secrets* section covers:
    - the mounted layout;
    - that a set `OPENAI_API_KEY` env var still wins;
    - adding a second Secret to `secretStore.secrets` (a values edit and a rollout);
    - adding a key to an existing Secret (no edit);
    - that a data key must be named `OPENAI_API_KEY` exactly; the old `openai` Secret's `api-key`
      is never read;
    - running the agent runner locally: export `OPENAI_API_KEY` (the env var wins), or point
      `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH` at a directory holding
      `openai-credentials/OPENAI_API_KEY`;
    - rotation.
  - **Rotation is stated honestly for this example.** The key is handed to the SDK once, at import,
    so rotating `openai-credentials` here needs `kubectl rollout restart deployment/ak-agent-kernel-agent-runner`.
    Code that calls `get` per use picks the new value up after the kubelet refresh plus `cache_ttl`.
- `deploy/deploy.sh:15-16`: the comment "the OpenAI secret reference" becomes "the OpenAI
  credentials Secret mount".
- `pyproject.toml`: unchanged, because no extra is needed.

**Release sequencing.** Both of the example's published pins predate this change:
- `agentkernel>=0.9.3` (`pyproject.toml:8`): until a release carries the provider, `kubernetes`
  is an unknown provider type.
- chart `0.9.3` (`deploy/deploy.sh:25`): helm silently ignores the unknown `secretStore` value, so
  no volume renders and the runner fails at startup with `SecretError` (mount path missing).

The README's non-`local` flow therefore works only after a release publishes both and the
pin-bump scripts (`scripts/update_chart_versions.py`, `scripts/update_examples_version.py`) run.
This is the same sequencing phase 1 had for its Terraform module pins. The `local` flow, and
therefore CI, uses this checkout for both.

**CI (`.github/workflows/chart-test.yaml`).**

- *Install chart* (`:147-169`) creates both Secrets on every flavor:
  ```bash
  kubectl create secret generic openai --from-literal=api-key="${{ secrets.OPENAI_API_KEY }}"
  kubectl create secret generic openai-credentials --from-literal=OPENAI_API_KEY="${{ secrets.OPENAI_API_KEY }}"
  ```
  - **`dev`**: `deploy.sh local` layers the example `ak-values.yaml`, so the runner mounts
    `openai-credentials` and has no `OPENAI_API_KEY` env var. The existing *Chat request through
    NATS* step therefore proves file resolution end to end.
  - **`baremetal` / `eks`**: unchanged `extraEnv` + `secretKeyRef` (`:165-167`) and no
    `secretStore`. They run the same image, whose config now selects `kubernetes`, with no mount.
    They stay green **only because** the env var wins before the provider is consulted and
    `KubernetesSecretProvider.__init__` does no I/O (rule 1). That dependency is intended: it is
    the CI coverage of the environment-first path.
- *Render every flavor and mode* (`:65-91`) gains the steps below. The job runs `bash -e`, so each
  expected failure uses an `if`-guarded idiom:
  ```bash
  echo "--- secretStore: two Secrets on the agent-runner"
  STORE=(--set secretStore.enabled=true \
    --set 'secretStore.secrets[0].name=openai-credentials' --set 'secretStore.secrets[1].name=slack-credentials')
  runner=$(helm template smoke "$CHART_DIR" "${STORE[@]}" --show-only templates/deployment-agent-runner.yaml)
  io=$(helm template smoke "$CHART_DIR" "${STORE[@]}" --show-only templates/deployment-io.yaml)
  grep -q 'mountPath: /var/run/secrets/agentkernel/openai-credentials' <<<"$runner"
  grep -q 'mountPath: /var/run/secrets/agentkernel/slack-credentials' <<<"$runner"
  grep -q 'secretName: slack-credentials' <<<"$runner"
  # `! grep` is exempt from `set -e`, so absence is asserted with an explicit exit.
  if grep -q '/var/run/secrets/agentkernel' <<<"$io"; then echo "io must not mount"; exit 1; fi
  echo "--- secretStore: single-process profile mounts on io"
  SINGLE=(--set agentRunner.enabled=false --set transport.type=in_memory)
  io=$(helm template smoke "$CHART_DIR" "${STORE[@]}" "${SINGLE[@]}" --show-only templates/deployment-io.yaml)
  grep -q 'mountPath: /var/run/secrets/agentkernel/openai-credentials' <<<"$io"
  grep -q 'mountPath: /var/run/secrets/agentkernel/slack-credentials' <<<"$io"
  echo "--- secretStore: websocket tier never mounts"
  ws=$(helm template smoke "$CHART_DIR" -f "$CHART_DIR/values-baremetal.yaml" "${STORE[@]}" \
    --set execution.mode=stream --set wsGateway.enabled=true --set wsGateway.auth.token=render \
    --show-only templates/deployment-ws-gateway.yaml)
  if grep -q '/var/run/secrets/agentkernel' <<<"$ws"; then echo "ws-gateway must not mount"; exit 1; fi
  echo "--- secretStore: expected failures"
  expect_fail() {  # <expected message> <helm args...>
    if helm template smoke "$CHART_DIR" "${@:2}" >/dev/null 2>err.txt; then echo "rendered: $*"; exit 1; fi
    grep -qF "$1" err.txt
  }
  expect_fail "must list at least one Secret" --set secretStore.enabled=true
  expect_fail "must be objects with a name" --set secretStore.enabled=true --set 'secretStore.secrets[0]=a'
  expect_fail "secretStore.secrets[].name is required" --set secretStore.enabled=true --set 'secretStore.secrets[0].other=x'
  expect_fail "more than once" --set secretStore.enabled=true \
    --set 'secretStore.secrets[0].name=a' --set 'secretStore.secrets[1].name=a'
  expect_fail "needs an agent-executing tier" --set secretStore.enabled=true \
    --set 'secretStore.secrets[0].name=a' --set agentRunner.enabled=false --set ioHandler.enabled=false
  expect_fail "needs an agent-executing tier" --set secretStore.enabled=true \
    --set 'secretStore.secrets[0].name=a' --set agentRunner.enabled=false   # broker transport, runner elsewhere
  ```
- **Default renders carry no mount** (permanent): the existing per-flavor loop (`:69-72`) also
  asserts that no flavor file's default render contains `/var/run/secrets/agentkernel`.
- **Default render is byte-identical**: a one-off check for this change, not a CI step; see
  [Testing → Verify](#verify-one-off-for-this-change).

**Docs surfaces.** Each gains `kubernetes` alongside `env`/`aws_ssm` and, where the surface
documents config, the new field.

| Surface | Change |
|---|---|
| `docs/docs/advanced/secrets.md` | `kubernetes` in the provider table (`:27`) and config sketch (`:45`); a new `### kubernetes` subsection after `### aws_ssm` (`:91`) covering: the layout, lookup across Secrets and the duplicate-key error; **key compatibility** (data keys must match `^[A-Z][A-Z0-9_]*$`, non-matching keys are silently unreachable, no remapping, and how to create compatible keys with `kubectl create secret generic … --from-literal=OPENAI_API_KEY=…` / `--from-env-file=.env`, or an External Secrets Operator `target.template.data` that renames remote keys); `mount_path` and other file-per-key mounts (CSI driver, Docker / Compose); the chart's `secretStore`, the tier placement rule and the exact volumes it renders; creating/adding/rotating Secrets with the kubelet delay and the no-`subPath` rule; **security** (every key of every listed Secret is readable by any code in the agent-executing container, including `local_subprocess` sandbox code; list only what agents need, keep unrelated keys out of those Secrets, use an isolated sandbox provider for untrusted code); **local development** (export the key, which wins, or set `mount_path` to a local directory laid out as `<dir>/<secret-name>/<KEY>` or flat `<dir>/<KEY>`; a missing directory is a `SecretError` even with `default=`, so keep `env` in a local config when neither applies); and that env still wins |
| `docs/docs/core-concepts/configuration.md` | `:187-189` sketch and `:520-521` env list: `kubernetes` and `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH` |
| `ak-deployment/ak-k8s/README.md` | `:112-113` points at a new *Secrets* section: `secretStore` values, the tier placement rule (and the render failure when no tier executes agents), no RBAC, key compatibility, the security note, rotation; links to `secrets.md` for the rest |
| `ak-py/README.md` | `:15` feature line and `:701-711` config reference |
| `.agents/skills/ak-dev-architecture/SKILL.md` | `:12` description, `:660` factory mapping, `:676-678` config sketch, `:1044` tree |
| `.agents/skills/ak-dev-new-secret-provider/SKILL.md` | `:5` "beyond env, aws_ssm and kubernetes", *Existing Providers* table (`:29`), and a note in step 6 (`:146`) that the Helm analog is a volume mount, not an IAM grant |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | `:149` factory test row names `kubernetes` |
| `docs/docs/agent-skills.md` | `:133` "beyond `env`, `aws_ssm` and `kubernetes`" |
| `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` | `:1310` provider question and `:1325` config comment |
| `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md` | *On-Prem / Kubernetes (Helm Chart)* (`:1247`): the `extraEnv` `secretKeyRef` install (`:1315-1317`) gains the `secretStore` alternative with `secret.provider.type: kubernetes` |

Both bundled-skill `evals/evals.json` files are **not** changed. Their cases test the AWS flows,
which this change leaves untouched. `docs/docs/examples/overview.md` has no entry for
`examples/k8s/openai-queue-mode` (only `examples/sandbox/broker-*`, `:78`), so it does not change.

### Behavioural changes

1. **`examples/k8s/openai-queue-mode` reads the OpenAI key from the mounted
   `openai-credentials` Secret** (data key `OPENAI_API_KEY`) instead of the `openai` Secret's
   `api-key` via `secretKeyRef`. **Migration:** a user who upgrades an existing install of this
   example keeps their old `openai` Secret, so the runner pod stays in `ContainerCreating` with a
   `FailedMount` event until they create `openai-credentials`. The README states this.
   Intentional: this example is the demonstration design.md asks for.
2. **The example's io and ws-gateway pods no longer receive `OPENAI_API_KEY`** (the top-level
   `extraEnv` is removed). Intentional least privilege; neither process reads it.
3. **CI's `kind-smoke` `dev` flavor resolves the key from a mounted file.** The `baremetal`/`eks`
   flavors stay on `secretKeyRef`.

**Non-changes**, verified:

- `SecretManager`, `SecretCache`, `SecretProvider`, the errors, the contract suite and the key
  grammar are unchanged.
- `env` and `aws_ssm` behave identically.
- No existing config field's name, type or default changes; two descriptions change.
- `helm template` with default values is byte-identical for every flavor.
- No RBAC object is created; the sandbox RBAC (`rbac-sandbox.yaml`) is untouched.
- `examples/sandbox/broker-*` keep `secretKeyRef`.
- No data is persisted. The provider reads only.

## Error handling

| Condition | Raised | Where | Surfaces as |
|---|---|---|---|
| `mount_path` empty (YAML/code) or relative | `AKConfigError` naming `secret.provider.kubernetes.mount_path` | `KubernetesSecretProvider.__init__` | At first `SecretManager.current()` |
| Key empty, starting with `.`, or containing `/`/`os.sep` (direct provider call) | `ValueError` | `get_secret` | Programming error; through the manager it is already rejected by `_validate_key` |
| `mount_path` does not exist (`FileNotFoundError`) or is not a directory (`NotADirectoryError`) | `SecretError` naming `mount_path`, saying to set `secretStore.enabled`/`secretStore.secrets`, mount Secrets there, or correct `secret.provider.kubernetes.mount_path`; chained | `_find_candidates` | Out of `get`, **even with `default=`** (`secret/manager.py:68`); never cached |
| Any other `OSError` listing `mount_path` (e.g. `PermissionError`) | `SecretError` naming the path and `type(exc).__name__`; chained | `_find_candidates` | Same |
| No candidate | — | returns `None` | `get` returns `default` or raises `SecretNotFoundError` |
| Exactly one candidate, empty file | — | returns `None` | A miss, as for `env` |
| Two or more candidates (any sizes) | `SecretError` listing the sorted candidate paths, never contents | `get_secret`, before reading | Out of `get`; never cached |
| Candidate vanished before `open` (`FileNotFoundError`) | — | `_read` returns `None` | A miss for this call; settled on the next |
| Any other `OSError` reading the candidate | `SecretError` naming the path and exception type; chained | `_read` | Out of `get` |
| File is not valid UTF-8 | `SecretError` naming the path; **raised `from None`** | `_read` | Out of `get`. The `UnicodeDecodeError` text quotes the offending byte, which is secret material, so it is not chained |
| A listed Kubernetes Secret does not exist | — | kubelet | Pod stays `ContainerCreating`, `FailedMount` event; the app never starts |
| `secretStore` misconfigured | `helm` render failure | `agent-kernel.secretStoreValidate` | `helm template` / `install` fails with the messages above |

## Testing

**`ak-py/tests/test_secret_providers.py`**: new tests for the provider.

- `TestKubernetesProviderContract(SecretProviderContract)`, with `reads_environment = False`:
  - the `provider` fixture returns `KubernetesSecretProvider(str(tmp_path))`;
  - `seed` writes the value as UTF-8 bytes (`write_bytes`, so newlines are not translated) to
    `<tmp_path>/<dir>/<key>`, with `<dir>` alternating between `openai-credentials` and
    `slack-credentials` across successive seeds. The contract therefore runs against the
    multi-Secret layout.
- Provider-specific tests, each building its layout in `tmp_path`:
  - **The kubelet layout**: `<dir>/..2026_10_08_00_00_00.1/KEY`, `<dir>/..data ->
    ..2026_10_08_00_00_00.1`, `<dir>/KEY -> ..data/KEY` resolves.
    - Re-pointing `..data` at a new timestamp directory with a different value makes the next
      call return the new value.
    - A key added only in the new revision is found.
  - A key at the top level (`<tmp_path>/KEY`) resolves.
  - **Duplicates** raise `SecretError`, and the message contains both paths and neither value:
    - the same key in two Secret directories;
    - the same key at the top level and in a Secret directory;
    - an empty file and a non-empty file with the same key.
  - **Dot entries are skipped**, tested where the skip actually matters: a single Secret mounted
    directly at `mount_path` (the override case), i.e. `<mount>/..ts/KEY`, `<mount>/..data -> ..ts`,
    `<mount>/KEY -> ..data/KEY`. It resolves to one value. Without the skip, `..data` and `..ts`
    would be searched as Secret directories and raise a duplicate error. A `.hidden/KEY` alone is
    not found.
  - **Depth**: `<tmp_path>/a/b/KEY` is not found.
  - A directory named `KEY` is not a candidate.
  - An empty file is a miss (`None`).
  - **`mount_path` errors**: a missing directory, and a regular file, raise `SecretError` whose
    message names the path and `secretStore`.
  - An unreadable directory (`chmod 000`, skipped when running as root) raises `SecretError`.
  - **Invalid UTF-8** raises `SecretError`, with `__cause__` and `__context__` suppressed
    (`from None`), and the message does not contain the bytes.
  - **A file that vanishes between discovery and read** is a miss: monkeypatch `builtins.open` in
    the module to raise `FileNotFoundError` once.
  - **Key guard**: `".."`, `".env"`, `"a/b"` and `""` raise `ValueError`.
  - **`__init__` validation and laziness**: `""` and `"relative/path"` raise `AKConfigError`. A
    nonexistent absolute path constructs fine, and no filesystem call is made at construction
    (assert with a monkeypatched `os.scandir` that raises).
  - **Re-discovery**: a key moved from one Secret directory to another between two calls is found
    in its new place.
- `test_contract_suite_is_not_exported` and `test_import_does_not_load_testing_module` stay as
  they are.

**`ak-py/tests/test_secret_factory.py`**: changed and new.

- `test_kubernetes_builds_kubernetes_provider`: `provider={"type": "kubernetes"}` builds a
  `KubernetesSecretProvider` with the default mount path, and `provider={"type": "kubernetes",
  "kubernetes": {"mount_path": "/run/secrets"}}` carries the override.
- `test_kubernetes_needs_no_sdk` (in `test_secret_providers.py`, beside
  `test_import_does_not_load_testing_module`, `:106`, and using its fresh-interpreter pattern): a
  subprocess imports `agentkernel.secret`, builds `SecretProviderFactory.get(...)` for `kubernetes`,
  and asserts that neither `kubernetes` nor `boto3` is in `sys.modules`. This pins both the
  stdlib-only claim and the eager export. A `sys.modules` monkeypatch would prove nothing, because
  the export has already imported the module.
- `test_unknown_short_name_rejected` (`:63-68`) also asserts `"kubernetes"` is in the message.
- `test_empty_prefix_is_fine_outside_aws_ssm` (`:103-105`) gains `"kubernetes"` in its
  parametrize list.
- `test_get_never_reads_akconfig` (`:108-114`) also builds `kubernetes`.
- `kubernetes` with `mount_path: ""` raises `AKConfigError` from the factory.

**`ak-py/tests/test_secret_manager.py`**: one addition to the environment-always-wins assertions,
as the new-provider skill requires. A `KubernetesSecretProvider` over a `tmp_path` seeded with
`KEY=from-file`, with `KEY=from-env` set, returns `from-env`, and the manager never lists the
directory (monkeypatched `os.scandir` counter is 0). A missing `mount_path` with `default="x"`
re-raises `SecretError`.

**`ak-py/tests/test_config.py`**:

- `test_secret_defaults` (`:312`) asserts
  `secret.provider.kubernetes.mount_path == "/var/run/secrets/agentkernel"`.
- `test_secret_env_vars` (`:324`) sets `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH=/run/secrets`
  and asserts it.
- A new case: `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH=""` leaves the default.

No existing patch target moves.

**Chart**: the `chart-test.yaml` renders (both mount placements, the ws-gateway exclusion and
every expected failure) and the `kind-smoke` `dev` run above. For the manual `ct install` gate,
see [Open decision](#open-decision).

### Verify (one-off, for this change)

Run once before merge; not added to CI. A permanent step would fail every later PR that
legitimately changes default renders, and `actions/checkout` fetches depth 1.

- **Default render is byte-identical**, the analog of phase 1's empty `terraform plan`: for each of
  `values.yaml`, `values-dev.yaml`, `values-baremetal.yaml` and `values-eks.yaml`, render with
  `helm template smoke <chart> -f <flavor>` on `develop` and on the branch, and `diff`; every diff
  is empty.
- The `kind-smoke` `dev` job passes on the PR (file resolution end to end), and the `baremetal` /
  `eks` jobs pass (environment-first path with the provider configured but no mount).

**Run:**

```bash
cd ak-py && uv run pytest tests/test_secret_providers.py tests/test_secret_factory.py \
  tests/test_secret_manager.py tests/test_config.py
cd ak-py && uv run pytest          # full suite
make lint-check-all
ct lint --config ak-deployment/ak-k8s/ci/ct.yaml
```

## Open decision

**The manual `ct install` gate** (`ak-deployment/ak-k8s/README.md:342-351`) installs
`chart/ci/kind-smoke-values.yaml` with the example images and no OpenAI key. That works today only
because the runner never reads the key at startup. After this change, `app_agent_runner.py`
calls `get("OPENAI_API_KEY")` at import with no default. With no env var and no mount,
`ct install` would crash-loop the runner. The two obvious fixes both break something:

- a placeholder `extraEnv` in `kind-smoke-values.yaml` is also layered into the CI `dev` run
  (`deploy.sh local -f kind-smoke-values.yaml`, `chart-test.yaml:155-156`), where the env var
  would win over the mount and the chat check would fail on a fake key;
- `secretStore` in `kind-smoke-values.yaml` needs `openai-credentials` to pre-exist in the
  namespace ct installs into, and ct creates a fresh one per install.

**Recommended:** leave `kind-smoke-values.yaml` unchanged and update the README's `ct install`
command to pass a placeholder key, which wins over the absent mount:
`--helm-extra-set-args "--set extraEnv[0].name=OPENAI_API_KEY --set extraEnv[0].value=placeholder"`.
The gate checks that pods start, not that chat works, so a placeholder is enough. `ct install` is
not run in any workflow (`.github/workflows/` has no `ct install`), so CI is unaffected either way.

## Changes from design.md

No requirement changes. Earlier spec-level decisions (the render failure when no tier executes
agents, the in_memory condition on the io placement, the bare-string entry check) are now
requirements in `design.md` under *Deployment*.

**Refinements within the design's wording**:
- the provider re-checks the key (rule 2) so the traversal claim holds for direct callers;
- a UTF-8 decode failure is raised `from None` rather than chained, because chaining would put
  a secret byte in the traceback;
- a candidate that vanishes between listing and reading is a miss;
- `KubernetesSecretProvider` is exported from `agentkernel.secret`;
- validation runs from a helper included in `configmap-env.yaml`, so it fails every release, not
  only those that render an agent-executing Deployment.
