---
name: ak-dev-new-secret-provider
description: >
  Step-by-step guide for adding a new built-in secret provider to Agent Kernel's secret-resolution
  capability (beyond env and aws_ssm). Use this skill when you need a new managed secret store
  (e.g. AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, HashiCorp Vault) addressable by a
  short `secret.provider.type` name. Covers the SecretProvider contract, addressing, factory
  registration, configuration, optional dependencies, the SecretProviderContract test suite,
  deployment IAM wiring, and docs.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Secret Provider

This guide walks through adding a built-in provider to the secret-resolution capability
(`ak-py/src/agentkernel/secret/`). Use `AWSSMSecretProvider`
(`ak-py/src/agentkernel/secret/providers/aws_ssm.py`) as the reference implementation, since it is
the only built-in that talks to a remote store. The `ak-dev-architecture` skill's *Secret
Resolution* section covers the manager, cache and resolution order this guide builds on.

## Existing Providers

| Provider | `type` value | Addressing | Extra |
|---|---|---|---|
| Environment (default) | `env` | the key **is** the variable name, read verbatim | — (stdlib) |
| AWS SSM Parameter Store | `aws_ssm` | `/ak/{prefix}/{key.lower()}`, `GetParameter(WithDecryption=True)` | `agentkernel[aws]` |
| Bring-your-own | dotted path, e.g. `myapp.secrets.VaultProvider` | whatever the subclass implements | the user's own |

## Do You Need a Built-in?

A dotted path already lets a user plug in any `SecretProvider` subclass with no core change:
`resolve_dotted(..., base=SecretProvider)` imports it and calls its `from_config`. AWS Secrets
Manager ships this way in v1 (see `docs/specs/749-secret-resolution/design.md`, Non-goals). Add a
built-in only when the backend is broadly useful, has a stable SDK, and deserves a short name,
tested IAM wiring and docs. Otherwise, document the dotted-path route in
`docs/docs/advanced/secrets.md` (*Custom providers*) and stop there.

## The Contract

`SecretProvider` (`secret/base.py`) is small. The rules around it are what matter:

- **`get_secret(key) -> Optional[str]`**: return the stored value, or `None` when the backend
  does not hold it. A **miss is not an error**. Raise `SecretError` (`secret/errors.py`) only
  when the backend *failed* (credentials, network, throttling, authorization), and never put the
  value in the message.
- **The provider owns its addressing.** `key` is always an environment-variable-style name
  (`^[A-Z][A-Z0-9_]*$`, e.g. `OPENAI_API_KEY`). Translating it to the backend's name (path, secret
  id, lowercase) happens here and nowhere else. The manager transforms nothing.
- **Never cache and never fall back.** `SecretManager` owns the environment → cache → provider
  order and `SecretCache` owns TTLs. A provider that caches breaks `invalidate()` and rotation.
- **Tolerate concurrent calls.** The manager calls the provider outside any lock, and concurrent
  cold reads may each call it. Create SDK clients lazily behind a lock (the double-checked
  `client` property in `aws_ssm.py`).
- **Return values verbatim.** Don't strip whitespace or parse JSON, because values are flat
  strings. Treat an empty value as absent (`EnvSecretProvider` returns `os.environ.get(key) or None`).
- **`from_config(cls, config: _SecretConfig)`** receives the **whole** `secret` block, not just
  `secret.provider`, so the deployment-wide `secret.prefix` is shared by every backend. Validate
  settings here and raise `AKConfigError` (`core/util/factory.py`) on unusable values, the way
  `AWSSMSecretProvider._normalize_prefix` rejects an empty or nested prefix. It fires at the first
  `SecretManager.current()`, so misconfiguration fails at startup, not on first read.

## Step-by-Step

### 1. Create the Provider File

`ak-py/src/agentkernel/secret/providers/<name>.py`, one class named `<Backend>SecretProvider`,
with a logger `ak.secret.provider.<name>`:

```python
class VaultSecretProvider(SecretProvider):
    """HashiCorp Vault KV v2. Addressing: OPENAI_API_KEY → secret/data/ak/{prefix}/openai_api_key."""

    _log = logging.getLogger("ak.secret.provider.vault")

    def __init__(self, prefix: str) -> None:
        """:raises AKConfigError: If prefix is empty."""
        ...
        self._client: Optional[Any] = None
        self._client_lock = Lock()

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "VaultSecretProvider":
        return cls(prefix=config.prefix)

    def get_secret(self, key: str) -> Optional[str]:
        """:raises SecretError: If Vault failed for any reason other than not-found."""
        ...
```

Map exactly one backend error to `None` (the not-found code, like `ParameterNotFound` in
`aws_ssm.py`). Everything else becomes `SecretError(...) from exc`, including SDK transport
errors.

### 2. Register with the Factory

In `secret/factory.py`, add the short name to `_BUILTIN_SECRET_PROVIDERS` and add a branch in
`SecretProviderFactory.create` before the dotted-path fallback. Import the module lazily inside
`require_extra` so a missing SDK raises a clear install hint:

```python
if key == "vault":
    with require_extra("vault", "secret.provider.type: vault"):
        from .providers.vault import VaultSecretProvider

    return VaultSecretProvider.from_config(config)
```

`create` takes the block explicitly and must never call `AKConfig.get()`
(`test_create_never_reads_akconfig` guards this).

### 3. Configuration

- **Reuse first.** `secret.prefix` already expresses the deployment scope. Derive the backend path
  from it instead of adding a per-provider path field. Region and credentials come from the SDK's
  own environment defaults (the `boto3.client("ssm")` precedent), not from new fields.
- Only if the backend truly needs settings `prefix` can't express (e.g. a Vault address or mount),
  add a `_Secret<Backend>Config` model under `_SecretProviderConfig` in `core/config.py`, with
  `Field(description=...)` on every field. Update the `type` field's description to list the new
  short name.
- There is no `enabled` flag: selecting the provider type is the opt-in.

### 4. Optional Dependency Extra

Add the SDK to an extra in `ak-py/pyproject.toml`, or reuse one that already carries it (`aws`
carries `boto3` for any AWS backend). Match the extra name to the `require_extra(...)` call.

### 5. Tests

- **Contract:** in `ak-py/tests/test_secret_providers.py`, subclass `SecretProviderContract`
  (`secret/testing.py`, which is deliberately not exported from `agentkernel.secret`). Override the
  `provider` fixture and `seed(provider, key, value)`. Seed through a fake SDK client, not the
  network, the way `TestAWSSMProviderContract` seeds `_FakeSSMClient.parameters`. Leave
  `reads_environment = False` unless the store *is* the environment.
- **Provider-specific tests** in the same file: the exact name requested for a key, not-found →
  `None`, each failure class → `SecretError` with no value in the message, config validation
  → `AKConfigError`, and lazy/single client creation.
- **Factory tests** in `ak-py/tests/test_secret_factory.py`: short name (case-insensitive) builds
  the provider, a missing extra raises before any settings check, and the provider receives the
  whole block.
- If the new provider adds a factory-level rule, extend `ak-py/tests/test_secret_manager.py`'s
  environment-always-wins assertions to include it.

### 6. Deployment Wiring (Cloud Stores)

If the backend is a cloud store the Terraform modules can grant, mirror `ssm_enabled` in
`ak-deployment/ak-aws/{serverless,containerized}` (`variables.tf`, `state.tf`,
`modules/*/main.tf`). Use one `bool` defaulting to `false`, keep every resource `count`-gated so
the default plan is empty, and attach a read-only grant scoped to the prefix to each application
role. Keep injecting `AK_SECRET__PREFIX` from the module's own `prefix` so the path and the grant
can't drift. Never create secret values in Terraform.

### 7. Documentation

- `docs/docs/advanced/secrets.md`: a `### <name>` subsection under *Providers* (addressing, IAM,
  extra, failure behavior) and the new value in the `secret.provider.type` row.
- `ak-dev-architecture/SKILL.md`, *Secret Resolution*: add the provider to the **Providers** bullet
  and the factory mapping.
- `ak-py/README.md`: the extra, if new.
- The bundled `ak-cloud-deploy` skill (`ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md`), if
  you added a deployment flag.

## Checklist

- [ ] `secret/providers/<name>.py`: owns addressing, `None` on miss, `SecretError` on failure, no caching, thread-safe lazy client
- [ ] `from_config` validates settings and raises `AKConfigError` at construction
- [ ] Factory branch behind `require_extra` + name in `_BUILTIN_SECRET_PROVIDERS` (`secret/factory.py`)
- [ ] Config: `secret.prefix` reused; a `_Secret<Backend>Config` only if unavoidable (`core/config.py`)
- [ ] Optional dependency extra in `ak-py/pyproject.toml`
- [ ] `SecretProviderContract` subclass + provider-specific tests (`tests/test_secret_providers.py`)
- [ ] Factory tests (`tests/test_secret_factory.py`)
- [ ] Terraform grant flag, if a cloud store (`ak-deployment/`)
- [ ] Docs: `docs/docs/advanced/secrets.md`, architecture skill, `ak-py/README.md`
- [ ] `cd ak-py && uv run pytest tests/test_secret_*.py` and `make lint-check-all` clean
