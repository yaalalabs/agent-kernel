# #749: Resolve secrets from a managed store with environment-variable fallback — Implementation Spec

Adds `agentkernel/secret/`, a top-level capability package beside `sandbox/` and `schedule/`, that
resolves an **environment-variable-style key** (`OPENAI_API_KEY`) to a value through a fixed
three-layer order: process cache, the configured provider, `os.environ[key]`. The manager is a plain
key → value mapping in that one currency — it composes no paths and transforms no names — and each
provider owns its own addressing: `AWSSMSecretProvider` is what turns `OPENAI_API_KEY` into the SSM
parameter `/ak/{prefix}/openai_api_key`. Two seams are config-keyed with dotted-path bring-your-own on
both: `SecretManager` (`secret.type`, built-in `layered`) owns the resolution strategy,
`SecretProvider` (`secret.provider.type`, built-ins `noop`, `in_memory`, `env`, `awssm`) owns where a
value lives. The AWS Terraform root modules gain one additive `ssm_enabled` flag that injects
`AK_SECRET__PREFIX` and grants `ssm:GetParameter` on `parameter/ak/${prefix}/*`.

[`design.md`](design.md) is the requirements source and has been updated to carry the key-shape
change this spec implements; [Changes from design.md](#changes-from-designmd) is the change log of
what moved, for a reviewer who read the earlier draft. The two questions design.md left open are
settled in [Resolved open questions](#resolved-open-questions).

## Design

### Package layout

```
ak-py/src/agentkernel/secret/
├── __init__.py          # public surface (testing.py deliberately excluded)
├── base.py              # SecretManager ABC (+ current()/reset()), SecretProvider ABC
├── errors.py            # SecretError, SecretNotFoundError
├── cache.py             # SecretCache
├── manager.py           # LayeredSecretManager
├── factory.py           # SecretManagerFactory, SecretProviderFactory
├── testing.py           # SecretProviderContract, SecretManagerContract (imports pytest)
└── providers/
    ├── __init__.py
    ├── noop.py          # NoOpSecretProvider     — the default; always misses
    ├── in_memory.py     # InMemorySecretProvider — seedable dict, for tests and local dev
    ├── env.py           # EnvSecretProvider      — os.environ as the backing store
    └── awssm.py         # AWSSMSecretProvider    — AWS SSM Parameter Store; aws extra
```

Governing rules, in the shape the shared-driver and pipeline rules take:

1. **`secret/` imports `core` only.** Nothing in `core/`, `pipeline/`, `api/`, `deployment/` or
   `integration/` imports `secret/`. The capability is reached by application code calling
   `SecretManager.current()`; no AK entrypoint calls it (design.md, Public API).
2. **The manager's currency is one key, unchanged end to end.** It caches under the key it was given,
   hands that same key to the provider, and reads `os.environ` under that same key. There is no case
   folding, no prefixing and no path composition anywhere in the manager. A future provider
   (Secrets Manager, Vault, Key Vault) therefore needs no manager change.
3. **Each provider owns its own addressing.** `get_secret(key)` receives the env-style key and
   translates it however its backend requires — `AWSSMSecretProvider` to `/ak/{prefix}/{key.lower()}`,
   `EnvSecretProvider` to `os.environ[key]`, `InMemorySecretProvider` to a dict lookup. A provider
   never caches and never falls back to another layer.
4. **Only the factories call `AKConfig.get()`.** `LayeredSecretManager.__init__` takes explicit
   parameters (`provider`, `cache_ttl`); `SecretProviderFactory.create` takes the `secret` block
   explicitly. Same rule the shared DB drivers and the #503 factory seams follow.
5. **Every component is a class.** The module-level names are constants only (`_KEY_PATTERN`,
   `_UNSET`, `_BUILTIN_SECRET_MANAGERS`, `_BUILTIN_SECRET_PROVIDERS`) — there are no module-level
   functions in the package.
6. **No secret value reaches a log record, an exception message, a trace span or a response body.**
   Log lines and exception messages carry the key name, or the provider's composed address, only.

### `secret/errors.py`

Mirrors `schedule/errors.py`: a flat, documented hierarchy, not a deep one.

```python
class SecretError(Exception):
    """A secret could not be resolved because the backend failed.

    Raised for provider failures — credentials, network, throttling, authorization. A provider
    *miss* is not an error: it falls through to the environment layer. Never carries a value.
    """


class SecretNotFoundError(SecretError):
    """No layer had the key, and no ``default`` was supplied."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"secret '{key}' not found: no provider entry and no '{key}' environment variable")
```

`SecretNotFoundError` names the key only. Under the old shape it also named the composed path; with
addressing now owned by the provider, the manager has no path to name — a provider that wants its
address diagnosable logs it at DEBUG on the miss (`AWSSMSecretProvider` does).

`SecretNotFoundError` subclasses `SecretError` so a caller that only wants "the capability failed"
catches the base, while a caller distinguishing "absent" from "broken" catches the subclass first.
The reverse hierarchy would force every caller to catch two types.

### `secret/base.py` — the two ABCs

```python
_UNSET: Any = object()  # "no default supplied"; typed Any so it can default an Optional[str] parameter


class SecretManager(ABC):
    """Resolves an environment-variable-style key to a secret value.

    The process-wide instance is SecretManager.current(). Keys are the same names the SDKs already
    read from the environment (OPENAI_API_KEY, NEO4J_PASSWORD), so nothing in the manager renames,
    prefixes or case-folds them.
    """

    # Guards the singleton only. Resolution locking is each implementation's own.
    _instance: ClassVar[Optional["SecretManager"]] = None
    _instance_lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.secret.manager")

    @classmethod
    def current(cls) -> "SecretManager":
        """Return the configured process-wide manager, building it on first access.

        Unlike ScheduleManager.get(), this never returns None: the capability is always available
        and its default (noop provider) costs nothing.

        :raises AKConfigError: If `secret.type`, `secret.provider.type`, `secret.prefix` or
                               `secret.cache_ttl` cannot be resolved to a usable manager.
        """
        # SecretManager._instance, not cls._instance: a subclass calling current() must get the
        # one configured manager, not start a second singleton under its own class attribute.
        with SecretManager._instance_lock:
            if SecretManager._instance is None:
                from .factory import SecretManagerFactory  # deferred: factory imports this module

                SecretManager._instance = SecretManagerFactory.create()
            return SecretManager._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance so the next current() rebuilds from config. For testing."""
        with SecretManager._instance_lock:
            SecretManager._instance = None

    @classmethod
    def from_config(cls, config: "_SecretConfig") -> "SecretManager":
        """Build the manager from the `secret` block. The single construction seam the factory uses."""
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str, default: Optional[str] = _UNSET) -> Optional[str]: ...

    @abstractmethod
    def inject(self, key: str) -> None: ...

    @abstractmethod
    def invalidate(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...


class SecretProvider(ABC):
    """A backend that holds secrets, addressed by an environment-variable-style key."""

    @classmethod
    def from_config(cls, config: "_SecretConfig") -> "SecretProvider":
        """Build the provider from the `secret` block.

        The whole block, not just `secret.provider`: `secret.prefix` is a deployment-wide scope that
        more than one backend can key off (SSM today, Secrets Manager or Key Vault later), so it
        stays one field rather than being redeclared per provider. A provider needing no settings
        inherits this default and ignores the block (the ScheduleProvider.from_config precedent).

        :raises AKConfigError: If the settings this provider needs are missing or malformed.
        """
        return cls()

    @abstractmethod
    def get_secret(self, key: str) -> Optional[str]:
        """Return the value stored for `key`, or None when this backend does not have it.

        The provider owns its own addressing — it translates `key` to whatever its backend uses —
        and it never caches and never falls back to another layer. It MUST tolerate concurrent
        calls: the built-in manager serializes them, a bring-your-own one need not.

        :raises SecretError: If the backend failed (as opposed to not holding the value).
        """
        raise NotImplementedError
```

`from_config` on `SecretManager` is declared but not abstract, so a bring-your-own manager that takes
no configuration is constructed by the inherited default the same way a provider is. It raises
`NotImplementedError` rather than returning `cls()` because a manager built with no provider cannot
resolve anything — the failure should be loud.

`_UNSET` is annotated `Any` so `default: Optional[str] = _UNSET` type-checks under the repo's mypy
settings while the advertised signature stays `Optional[str]` at both ends (design.md, Public API).

### `secret/cache.py` — `SecretCache`

```python
class SecretCache:
    """TTL'd key -> value store holding resolved hits only.

    Keyed by the same environment-variable-style key the caller passed, so a cache entry, a provider
    lookup and an environment variable all name one thing. Nothing here transforms the key.

    Not internally locked: LayeredSecretManager holds its resolution lock across the whole
    check -> fetch -> store sequence, so a second lock here would be redundant and would invite the
    belief that the cache alone is the critical section.
    """

    def __init__(self, ttl: int) -> None:
        """:raises AKConfigError: If ttl is negative."""
        if ttl < 0:
            raise AKConfigError(f"secret.cache_ttl must be >= 0 (0 disables caching), got {ttl}")
        self._ttl = ttl
        self._entries: dict[str, tuple[str, float]] = {}  # key -> (value, expires_at monotonic)

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, key: str) -> Optional[str]:
        """Return the cached value, or None when absent or expired (expired entries are dropped)."""

    def set(self, key: str, value: str) -> None:
        """Store a hit. A no-op when caching is disabled (ttl == 0)."""

    def invalidate(self, key: str) -> None:
        """Drop one entry. Never raises for an unknown key."""

    def clear(self) -> None:
        """Drop every entry."""
```

- Expiry uses `time.monotonic()`, not `time.time()`: a wall-clock step (NTP, a suspended container)
  must not extend or truncate a rotation window.
- **Only hits are stored.** `set` is never called with `None`, so a `get` returning `None` is
  unambiguously "not cached" — which is what makes a miss re-resolve on the next call (design.md,
  Naming and resolution).
- `ttl == 0`: `set` stores nothing, `get` always returns `None`, `invalidate`/`clear` stay callable
  no-ops, so no caller branches on the TTL.
- `ttl < 0` raises at construction. The Pydantic model also constrains `ge=0`, so a negative value in
  YAML or `AK_SECRET__CACHE_TTL` is rejected at config load with a `ValidationError`; this check
  covers the programmatic construction path a test or a bring-your-own manager takes. Both boundaries
  are asserted (see Testing).

### `secret/manager.py` — `LayeredSecretManager`

```python
# Environment-variable-style keys: the names the SDKs already read. Uppercase-only so one secret has
# exactly one spelling across the cache, the provider and os.environ.
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class LayeredSecretManager(SecretManager):
    """The built-in manager: cache -> provider -> environment, over one unchanged key."""

    def __init__(self, provider: SecretProvider, cache_ttl: int = 300) -> None:
        """Constructor arguments are explicit; config reading stays in from_config/the factory.

        :raises AKConfigError: If cache_ttl is negative.
        """
        self._provider = provider
        self._cache = SecretCache(cache_ttl)
        self._lock = RLock()

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "LayeredSecretManager":
        """:raises AKConfigError: If the configured provider's own settings are unusable."""
        return cls(provider=SecretProviderFactory.create(config), cache_ttl=config.cache_ttl)

    # -- public API ----------------------------------------------------------------------

    def get(self, key: str, default: Optional[str] = _UNSET) -> Optional[str]:
        self._validate_key(key)
        value = self._resolve(key)
        if value is not None:
            return value
        if default is _UNSET:
            raise SecretNotFoundError(key)
        return default

    def inject(self, key: str) -> None:
        self._validate_key(key)
        value = self._resolve(key)
        if value is None:
            raise SecretNotFoundError(key)
        os.environ[key] = value
        self._log.debug("Injected secret into environment variable %s", key)

    def invalidate(self, key: str) -> None:
        self._validate_key(key)
        with self._lock:
            self._cache.invalidate(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- internals -----------------------------------------------------------------------

    def _resolve(self, key: str) -> Optional[str]:
        """Cache -> provider -> environment, first hit wins, under one lock for the whole sequence."""
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            value = self._provider.get_secret(key)  # may raise SecretError
            if value is None:
                value = os.environ.get(key)
            if value is not None:
                self._cache.set(key, value)
            return value

    @staticmethod
    def _validate_key(key: str) -> None:
        """:raises ValueError: If key does not match ^[A-Z][A-Z0-9_]*$."""
```

The manager has no `prefix`, no `_compose_path` and no `_env_var_name`: with the key carried through
unchanged, all three disappear. Ordering and locking decisions, each of which is testable:

1. **`_validate_key` runs before anything else**, so a malformed key never reaches the provider and
   never reads or writes `os.environ`. The grammar's job is now to keep the *name* well-formed — it
   rules out `/`, whitespace, `=` and NUL, which would make an environment-variable name malformed,
   and it forces a single spelling so two keys cannot address one cache entry.
2. **The grammar no longer hides a transformation, so it no longer bounds which variables `inject`
   can reach.** `inject("PATH")` and `inject("AWS_SECRET_ACCESS_KEY")` are now well-formed calls that
   overwrite those variables. This is a deliberate consequence of dropping the `UPPERCASE(key)` step:
   the caller now writes the exact variable name it means, so clobbering `PATH` is an explicit act
   rather than a surprise produced by case folding. It is a caller responsibility, documented on
   `inject` and in the deployment docs; no denylist is added, because any list of "dangerous" names
   would be arbitrary and incomplete, and injecting AWS credentials is a legitimate use.
3. **The lock spans the whole resolution.** Guarding the cache alone would leave check→fetch→store
   interleaved, so a cold key requested by *n* threads would cost *n* provider round trips. Holding
   it across the sequence makes a cold key **single-flight**: the first caller fetches, the rest wait
   and read the entry it wrote. `RLock`, not `Lock`, so a bring-your-own provider that re-enters the
   manager (a provider resolving its own credential through `get`) deadlocks on a second thread
   rather than on itself.
4. **A provider failure propagates out of `_resolve`**, so it is never mistaken for a miss and never
   falls through to the environment. `get`'s `default` is therefore returned on a miss only.
5. **`inject` writes `os.environ` outside the resolution lock.** The write is a single dict
   assignment and is idempotent for a given key/value; serializing it would extend the critical
   section for no guarantee.
6. **`invalidate`/`clear` touch the cache only.** Neither writes to the provider, neither unsets an
   injected variable. An injected key therefore makes the environment layer permanently non-empty
   for that key — documented, not mitigated (design.md, Public API).

### `secret/factory.py` — the two factories

Both follow the `core/util/factory.py` house shape exactly as `ScheduleProviderFactory`
(`schedule/provider/base.py:103-142`) does: `if`/`elif` real-import branches for built-ins,
`require_extra` around an optional SDK, `resolve_dotted` for any dotted value, `AKConfigError` for an
unknown short name.

```python
_BUILTIN_SECRET_MANAGERS = ["layered"]
_BUILTIN_SECRET_PROVIDERS = ["noop", "in_memory", "env", "awssm"]


class SecretManagerFactory:
    """Creates the SecretManager named by `secret.type`."""

    _log = logging.getLogger("ak.secret.factory")

    @staticmethod
    def create() -> SecretManager:
        secret_config = AKConfig.get().secret
        manager_type = secret_config.type
        SecretManagerFactory._log.info(f"Building '{manager_type}' secret manager")
        if manager_type.lower() == "layered":
            from .manager import LayeredSecretManager

            return LayeredSecretManager.from_config(secret_config)
        if "." not in manager_type:
            raise AKConfigError(
                f"unknown secret manager type '{manager_type}'; expected one of {_BUILTIN_SECRET_MANAGERS} "
                "or a dotted path to a SecretManager subclass"
            )
        return resolve_dotted(manager_type, base=SecretManager).from_config(secret_config)


class SecretProviderFactory:
    """Creates the SecretProvider named by `secret.provider.type`."""

    _log = logging.getLogger("ak.secret.provider.factory")

    @staticmethod
    def create(config: _SecretConfig) -> SecretProvider:
        provider_type = config.provider.type
        SecretProviderFactory._log.info(f"Building '{provider_type}' secret provider")
        key = provider_type.lower()
        if key == "noop":
            from .providers.noop import NoOpSecretProvider

            return NoOpSecretProvider.from_config(config)
        if key == "in_memory":
            from .providers.in_memory import InMemorySecretProvider

            return InMemorySecretProvider.from_config(config)
        if key == "env":
            from .providers.env import EnvSecretProvider

            return EnvSecretProvider.from_config(config)
        if key == "awssm":
            with require_extra("aws", "secret.provider.type: awssm"):
                from .providers.awssm import AWSSMSecretProvider

            return AWSSMSecretProvider.from_config(config)
        if "." not in provider_type:
            raise AKConfigError(
                f"unknown secret provider type '{provider_type}'; expected one of {_BUILTIN_SECRET_PROVIDERS} "
                "or a dotted path to a SecretProvider subclass"
            )
        return resolve_dotted(provider_type, base=SecretProvider).from_config(config)
```

`SecretProviderFactory.create` takes the `secret` block **explicitly** rather than reading `AKConfig`
itself — unlike `ScheduleProviderFactory.create()`, which reads config. Two reasons:
`LayeredSecretManager` already holds the block when it builds its provider, so a second
`AKConfig.get()` would re-read a value the caller has; and a bring-your-own manager that wants to
reuse the provider seam (design.md, Manager seam) can hand it any `_SecretConfig` it likes rather
than being forced onto `AKConfig`. This is the same explicit-config seam #503 added to
`QueueTransportFactory.create(queues_config=...)` and `ResponseStoreFactory.create(...)`.

`require_extra` wraps only the `import`, not the construction — matching
`schedule/provider/base.py:133-136`, so an `AKConfigError` raised while validating the prefix is not
relabelled as a missing extra.

### `secret/providers/noop.py` — `NoOpSecretProvider`

```python
class NoOpSecretProvider(SecretProvider):
    """The null backend and the default: resolution collapses to cache + environment.

    Distinct from EnvSecretProvider: this one never reads the environment. The manager's third layer
    does that, unconditionally and for every provider.
    """

    def get_secret(self, key: str) -> Optional[str]:
        return None
```

No credentials, no network, no configuration. This is the local-development and
unchanged-deployment path, and it is why the capability needs no `enabled` flag.

### `secret/providers/in_memory.py` — `InMemorySecretProvider`

```python
class InMemorySecretProvider(SecretProvider):
    """Seedable dict-backed backend: the test double of the provider seam, and a local-dev store.

    Instance state, not class-level: unlike InMemoryTransport (whose queues must be shared across
    the producer and consumer threads of one process), nothing here needs to be visible to a second
    manager, and process-wide state would leak seeded secrets between tests.
    """

    def __init__(self, secrets: Optional[dict[str, str]] = None) -> None:
        self._secrets: dict[str, str] = dict(secrets or {})
        self._lock = Lock()

    def put(self, key: str, value: str) -> None:
        """Seed a value. Not part of SecretProvider — the ABC is read-only by design."""
        with self._lock:
            self._secrets[key] = value

    def get_secret(self, key: str) -> Optional[str]:
        with self._lock:
            return self._secrets.get(key)
```

`put` is this class's own method, not an ABC addition: `SecretProvider` stays read-only (design.md,
Non-goals — nothing writes to a backend from the runtime), and each backend seeds differently, which
is exactly why `SecretProviderContract` delegates seeding to the subclass.

The `Lock` makes it safe under the concurrent calls the ABC requires, so it is a faithful stand-in
for a real backend in the single-flight test rather than one that only passes because it is trivial.

### `secret/providers/env.py` — `EnvSecretProvider`

```python
class EnvSecretProvider(SecretProvider):
    """os.environ as the backing store: the key IS the variable name, read verbatim."""

    def get_secret(self, key: str) -> Optional[str]:
        return os.environ.get(key)
```

**Under `LayeredSecretManager` this provider is observably equivalent to `noop`**, because that
manager's third layer already reads `os.environ[key]` unconditionally for every provider (design.md,
Naming and resolution — a settled requirement this spec does not touch). It earns its place for two
other readers: a **bring-your-own manager**, which owns its whole resolution and may have no
environment layer at all, gets the environment as a composable provider instead of re-implementing
it; and the **contract suite** gets a second real, dependency-free backend that actually returns
values, so the provider seam is exercised end to end without a cloud SDK. That overlap is stated here
rather than left for a reviewer to notice.

### `secret/providers/awssm.py` — `AWSSMSecretProvider`

This is the only component that knows about paths, prefixes or case.

```python
class AWSSMSecretProvider(SecretProvider):
    """AWS SSM Parameter Store, read-only, one call: GetParameter(WithDecryption=True).

    Addressing: the env-style key OPENAI_API_KEY becomes the parameter /ak/{prefix}/openai_api_key.
    The leading slash is required — SSM rejects a hierarchical name without one — and the IAM
    resource ARN parameter/ak/{prefix}/* is the ARN of exactly this name.
    """

    _log = logging.getLogger("ak.secret.provider.awssm")

    def __init__(self, prefix: str) -> None:
        """:raises AKConfigError: If prefix is empty, or still contains '/' after stripping."""
        self._prefix = self._normalize_prefix(prefix)
        self._client: Optional[Any] = None
        self._client_lock = Lock()

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "AWSSMSecretProvider":
        return cls(prefix=config.prefix)

    @property
    def client(self) -> Any:
        """Lazily created boto3 SSM client. Region and credentials come from the boto3 environment
        default, matching DynamoDBDriver (core/util/driver/dynamodb.py:38)."""
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = boto3.client("ssm")
        return self._client

    def get_secret(self, key: str) -> Optional[str]:
        path = self._compose_path(key)
        try:
            response = self.client.get_parameter(Name=path, WithDecryption=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ParameterNotFound":
                self._log.debug("No SSM parameter at %s", path)
                return None
            raise SecretError(f"SSM GetParameter failed for '{path}': {code}") from exc
        except BotoCoreError as exc:
            raise SecretError(f"SSM GetParameter failed for '{path}': {type(exc).__name__}") from exc
        return response["Parameter"]["Value"]

    def _compose_path(self, key: str) -> str:
        return f"/ak/{self._prefix}/{key.lower()}"

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        """:raises AKConfigError: If prefix is empty, or contains '/' after stripping leading/trailing."""
```

**Prefix rules**, all enforced here rather than in the manager:

- Empty (after stripping `/`) → `AKConfigError` at construction, i.e. at the first
  `SecretManager.current()`. Without it every lookup would compose `/ak//openai_api_key` and miss
  silently into the environment layer. The message names `secret.prefix` and `AK_SECRET__PREFIX`.
- Leading and trailing `/` are stripped, so `myproduct-dev`, `/myproduct-dev` and `myproduct-dev/`
  compose identically.
- An **interior** `/` → `AKConfigError`, because a nested path would compose outside the
  `parameter/ak/{prefix}/*` grant the Terraform modules provision and would then fail as an
  authorization error rather than as the configuration error it is.
- `key.lower()` is applied only here. The manager's grammar guarantees the key is already uppercase
  ASCII letters, digits and underscores, so the mapping is total and collision-free: two distinct
  keys can never produce one parameter name.

**Exception scope**, stated rather than left to the implementation:

| Condition | Classified as | Why |
|---|---|---|
| `ClientError` with code `ParameterNotFound` | **miss** → `None` | The parameter is genuinely absent at a path the role may read. |
| `ClientError` with code `AccessDeniedException` | **failure** → `SecretError` | The IAM policy is provisioned from the same `prefix` the path is composed from, so a denial means the deployment is misconfigured. Tolerating it would make every IAM mistake resolve silently from the environment. |
| Any other `ClientError` (throttling, `InvalidKeyId`, `InternalServerError`, …) | **failure** → `SecretError` | Same reasoning. |
| `BotoCoreError` (credentials, endpoint resolution, connection) | **failure** → `SecretError` | Same reasoning. |
| `ImportError` on `boto3`/`botocore` | `ImportError` naming the `aws` extra | Raised by `require_extra` at factory time, not here. |

`botocore.exceptions.ClientError` and `BotoCoreError` are caught, not the client's dynamically built
`client.exceptions.ParameterNotFound` — the latter requires a live client to name the class and makes
the provider awkward to test against a fake client. `ClientError` is a subclass of `Exception`, not of
`BotoCoreError`, so the two `except` clauses do not overlap.

Exception messages carry the **path and the error code only**. `response["Parameter"]["Value"]` is
never logged, never repr'd into an exception.

Concurrency: boto3 clients are safe to call from multiple threads but **creating** one is not, so
lazy creation is guarded by a per-instance `Lock` — the same double-checked shape the shared DB
drivers use for connect/reconnect. The provider holds no other mutable state, so it satisfies the
ABC's "must tolerate concurrent calls" requirement whatever manager drives it.

Per-operation cost: one `GetParameter` per uncached resolution. SSM's standard `GetParameter`
throughput is 40 TPS per account and region and this capability does nothing to raise it; a **miss is
not cached**, so a key that lives only in the environment costs a round trip on every call for the
life of the process. Nothing in the code constrains where calls are made from, so the rule the docs
carry is: resolve secrets during startup, never on the request hot path. A deployment whose keys all
come from the environment selects `provider.type: noop` and pays nothing.

### `secret/testing.py` — the two contract suites

Same conventions as `sandbox/testing.py` and `pipeline/testing.py`: the module imports `pytest`, the
classes are deliberately **not** prefixed `Test` so pytest does not collect them on their own, and
neither class is exported from `secret/__init__.py` so `import agentkernel.secret` stays free of a
pytest dependency.

```python
class SecretProviderContract:
    """Conformance suite every SecretProvider subclasses. Override `provider` and `seed`.

    Two declared capability flags let a backend opt out of an assertion its nature makes
    meaningless. Each is *read by the suite*, never an ad-hoc skip, so a bring-your-own provider
    gets the same treatment and no provider can quietly opt out of an assertion that does apply.
    """

    # False for a backend that structurally cannot hold a value (NoOpSecretProvider).
    supports_round_trip: bool = True
    # True for a backend whose store IS the environment (EnvSecretProvider).
    reads_environment: bool = False

    @pytest.fixture
    def provider(self) -> SecretProvider:
        raise NotImplementedError("subclasses must override the `provider` fixture")

    def seed(self, provider: SecretProvider, key: str, value: str) -> None:
        """Store `value` under `key` in this backend. Required when supports_round_trip is True."""
        raise NotImplementedError("subclasses with supports_round_trip must override `seed`")

    def test_contract_seeded_value_round_trips_verbatim(self, provider): ...
    def test_contract_absent_key_returns_none(self, provider): ...
    def test_contract_key_is_used_verbatim(self, provider): ...
    def test_contract_environment_is_consulted_only_when_declared(self, provider, monkeypatch): ...
```

- **A seeded value round-trips verbatim** — including leading/trailing whitespace and a multi-line
  value, so no backend trims or re-encodes what it was given. Skipped by declaration when
  `supports_round_trip` is False.
- **An absent key returns `None` rather than raising**, so the manager can fall through to the
  environment layer.
- **The key is used verbatim**: seeding under `CONTRACT_KEY_A` and reading `CONTRACT_KEY_B` misses,
  and reading `CONTRACT_KEY_A` hits — pinning that the provider neither case-folds the key it was
  handed nor collapses two keys onto one address. (How `CONTRACT_KEY_A` is *spelled inside* the
  backend is the provider's business — `AWSSMSecretProvider` legitimately lowercases it into a path;
  what the contract forbids is two distinct keys resolving to one entry.)
- **The environment is consulted only when declared**: with `reads_environment` False, setting
  `os.environ[key]` for an unseeded key must still miss; with it True the same setup must **hit**, so
  the flag cannot be set carelessly just to silence the first form.

```python
class SecretManagerContract:
    """Conformance suite every SecretManager subclasses. Override `manager`,
    `resolvable_key` and `unresolvable_key`."""

    @pytest.fixture
    def manager(self) -> SecretManager:
        raise NotImplementedError("subclasses must override the `manager` fixture")

    @pytest.fixture
    def resolvable_key(self) -> str:
        raise NotImplementedError("subclasses must override the `resolvable_key` fixture")

    @pytest.fixture
    def unresolvable_key(self) -> str:
        raise NotImplementedError("subclasses must override the `unresolvable_key` fixture")

    def test_contract_get_raises_on_a_miss(self, manager, unresolvable_key): ...
    def test_contract_get_returns_the_default_on_a_miss(self, manager, unresolvable_key): ...
    def test_contract_get_default_none_returns_none_rather_than_raising(self, manager, unresolvable_key): ...
    def test_contract_inject_sets_the_environment_variable_named_by_the_key(self, manager, resolvable_key, monkeypatch): ...
    def test_contract_invalidate_and_clear_are_callable_and_non_raising(self, manager, resolvable_key): ...
    def test_contract_malformed_key_raises_value_error(self, manager): ...
```

- **A generic suite cannot know which keys a given manager resolves**, so the subclass supplies the
  instance under contract, one key it resolves and one it does not — the
  `SandboxProviderContract`/`QueueTransportContract` pattern.
- **An omitted fixture fails loudly rather than silently skipping**: the base implementations
  `raise NotImplementedError`, so a subclass that forgets one gets an error at setup, not a green
  run. This is the mechanism `SandboxProviderContract.provider` (`sandbox/testing.py:151-154`) uses;
  it is not `pytest.skip`.
- `inject` is asserted to set `os.environ[key]` **under the key itself** — the assertion that pins
  the no-transformation rule.

### `secret/__init__.py`

```python
__all__ = [
    "errors",
    "EnvSecretProvider",
    "InMemorySecretProvider",
    "LayeredSecretManager",
    "NoOpSecretProvider",
    "SecretCache",
    "SecretError",
    "SecretManager",
    "SecretNotFoundError",
    "SecretProvider",
]
```

Eager imports only — nothing here pulls FastAPI or boto3, so the lazy `__getattr__` indirection
`schedule/__init__.py` needs is unnecessary. `AWSSMSecretProvider` is deliberately **not** exported:
importing it eagerly would drag `boto3` into every process that touches `agentkernel.secret`; the
factory imports it behind `require_extra`, and an application that wants the class by name uses its
dotted path. `SecretProviderContract`/`SecretManagerContract` are not exported either (pytest
dependency), matching `agentkernel.sandbox`'s treatment of `sandbox/testing.py`.

No top-level alias module (`agentkernel/secret.py`) is added: `agentkernel.schedule` and
`agentkernel.sandbox` are imported by their package path, and the alias modules
(`agentkernel/thread.py`, `agentkernel/agui.py`) exist only for packages that live under
`integration/`.

### Consumer changes

**Changed — `ak-py/src/agentkernel/knowledgebase/starburst.py`.** The four module-level constants at
`:12-15` are deleted and their `os.getenv` calls move into `StarburstManager.__init__`, where they
are already consumed at `:62-65`:

```python
# deleted from module scope (:12-15)
STARBURST_HOST = os.getenv("STARBURST_HOST", "")
STARBURST_USER = os.getenv("STARBURST_USER", "")
STARBURST_PASSWORD = os.getenv("STARBURST_PASSWORD", "")
STARBURST_PORT = int(os.getenv("STARBURST_PORT", "443"))

# in __init__ (was :62-65), matching Neo4jManager (knowledgebase/neo4j.py:43-45)
self.host = host or os.getenv("STARBURST_HOST", "")
self.port = port or int(os.getenv("STARBURST_PORT", "443"))
self.user = user or os.getenv("STARBURST_USER", "")
self.password = password or os.getenv("STARBURST_PASSWORD", "")
```

This is the resolution of design.md's one open question (see [Resolved open
questions](#resolved-open-questions)). It is the only consumer this change touches.

**Verified unchanged — every other consumer in design.md's Motivation.** All four read their
environment variable at call time, so `inject(...)` before the agents are built reaches them with no
code change. Under the new key shape the call is literally the variable's own name:

| Site | Read | `inject` call that serves it |
|---|---|---|
| `knowledgebase/neo4j.py:43-45` | `os.getenv` in `Neo4jManager.__init__` | `inject("NEO4J_PASSWORD")` |
| `guardrail/walledai.py:46` | `os.getenv` in `WalledAI.__init__` | `inject("WALLED_API_KEY")` |
| `integration/slack/adapter.py:285` | `os.environ.get` in `_client()`, per delivery | `inject("SLACK_BOT_TOKEN")` |
| `sandbox/providers/e2b.py:107` | `os.environ.get(self._config.api_key_env)` in `_api_key()` | `inject("E2B_API_KEY")` |
| `sandbox/providers/daytona.py:125` | `os.environ.get(self._config.api_key_env)` in `_client()` | `inject("DAYTONA_API_KEY")` |

The sandbox providers are reached because the key **is** the variable name, so it must match
`sandbox.profiles.*.e2b.api_key_env` (default `E2B_API_KEY`, `core/config.py:661`) and
`...daytona.api_key_env` (default `DAYTONA_API_KEY`, `core/config.py:666`). A deployment that renamed
either field injects under the renamed value — a direct correspondence now, rather than the
`UPPERCASE(key)` coincidence the old shape relied on.

**Verified unchanged — no AK entrypoint calls `inject`.** `AgentRunner.run()`,
`WebSocketGateway.run()`, `IOHandler.run()`, `RESTAPI.run()`, `ECSIOHandler.run()`,
`ServerlessAgentRunner.handle()` and the Lambda handlers are untouched. Every injection is an
explicit call the application makes in its own module before handing off (design.md, Public API).

### Config changes

**Reuse audit.** `grep "class _" ak-py/src/agentkernel/core/config.py` returns 70 models. None
expresses a secret backend, a path prefix or a resolution cache: the connection models
(`_RedisConfig:22`, `_ValkeyConfig:31`, `_DynamoDBConfig:40`, `_CosmosDBConfig:50`,
`_FirestoreConfig:59`) describe a URL/table plus TTL and prefix for a *store*, and `_QueuesConfig:569`
/ `_ResponseStoreConfig:450` describe a transport and a record store. Subclassing any of them would
inherit fields (`url`, `ttl`, `table_name`) that no secret reader would ever read — the defect the
house rule names. A new block is required.

Two new models in `ak-py/src/agentkernel/core/config.py`, placed after `_SandboxConfig` (`:786`) and
before `_AGUIStateConfig` (`:856`):

```python
class _SecretProviderConfig(BaseModel):
    type: str = Field(
        default="noop",
        description="Secret backend: a built-in short name (noop, in_memory, env, awssm) or a dotted path to a "
        "SecretProvider subclass. 'noop' is the null backend — resolution collapses to the process cache plus the "
        "environment variable named by the key. 'awssm' is AWS SSM Parameter Store and requires secret.prefix.",
    )


class _SecretConfig(BaseModel):
    """Configuration for secret resolution (manager strategy, deployment scope, backend, cache).

    Always available and free at its defaults, so there is no `enabled` flag: selecting a provider
    other than `noop` is the only opt-in, and `provider.type` already expresses it."""

    type: str = Field(
        default="layered",
        description="Secret manager: the built-in short name 'layered' (cache -> provider -> environment, keyed by the "
        "environment-variable name itself) or a dotted path to a SecretManager subclass that owns the whole resolution strategy",
    )
    prefix: str = Field(
        default="",
        description="Deployment scope a provider uses to namespace its secrets, e.g. 'myproduct-dev-agents'. The awssm "
        "provider reads OPENAI_API_KEY from the SSM parameter /ak/{prefix}/openai_api_key. Injected by the AWS Terraform "
        "modules as AK_SECRET__PREFIX from their own resource-naming prefix. Required by awssm; ignored by the other built-ins",
    )
    provider: _SecretProviderConfig = Field(
        default_factory=_SecretProviderConfig, description="Backend the secret values are read from"
    )
    cache_ttl: int = Field(
        default=300,
        ge=0,
        description="Seconds a resolved secret is served from the process cache before it is re-resolved. "
        "0 disables caching so every read re-resolves; this is the rotation-pickup window",
    )
```

One new field on `AKConfig` (`:884`), between `sandbox` (`:919`) and `execution` (`:920`):

```python
    secret: _SecretConfig = Field(description="Secret resolution configurations", default_factory=_SecretConfig)
```

Every field justified, with its reader named:

| Field | Reader | Why it cannot be derived |
|---|---|---|
| `secret.type` | `SecretManagerFactory.create` | Chooses the resolution strategy itself; no other configured component implies it. `layered` is the only built-in, so the field exists chiefly as the bring-your-own escape hatch. |
| `secret.prefix` | `AWSSMSecretProvider.from_config` → `__init__` → `_compose_path` | The Terraform `prefix` variable (`ak-deployment/ak-aws/serverless/variables.tf:6`) is not injected into the runtime today, so nothing in `AKConfig` carries the deployment identifier. |
| `secret.provider.type` | `SecretProviderFactory.create` | The factory selector. Nested to match `schedule.provider.type` (`_ScheduleProviderConfig:356`) and to leave room for a provider's own settings sub-block. |
| `secret.cache_ttl` | `SecretCache.__init__`, via `LayeredSecretManager.from_config` | The rotation-pickup window; differs per deployment, so it cannot be a constant. Flat rather than a `cache:` sub-block because there is exactly one cache setting. |

- **No `enabled` flag.** The capability is always available and costs nothing at its default, so
  nothing has to be opted into — the house rule reserves `enabled` for features with a real cost
  (`sandbox.enabled`, `trace.enabled`).
- **No `secret.provider.awssm` sub-block.** `prefix` stays top-level because it is a deployment-wide
  scope a second managed-store provider would key off identically; putting it under `awssm` would
  force the next provider to redeclare it, and would change the `AK_SECRET__PREFIX` variable the
  Terraform modules inject. Nothing else about the SSM provider is configurable: region and
  credentials come from the boto3 environment default, and decryption rides the AWS-managed key.
- **`_SecretConfig` is non-`Optional` with a `default_factory`**, unlike `thread` and `schedule`.
  Those use block presence as their enabled-check; this capability has no enabled-check, and a
  non-`Optional` block means `AKConfig.get().secret` never needs a `None` guard.

**Compatibility.** Every field has a default and the default provider (`noop`) changes no behavior, so:
existing `config.yaml` files parse unchanged and keep their meaning; no existing `AK_*` variable
changes name, type or default; no existing field description changes, so no generated-docs entry is
rewritten. `env_ignore_empty=True` (`core/util/config_yaml_util.py:190`) means `AK_SECRET__PREFIX=""`
is ignored and the default `""` applies — which is exactly the value `AWSSMSecretProvider` rejects, so
an empty injection cannot silently produce `/ak//openai_api_key`.

The existing `AK_SECRETS_PATH` / `<file:...>` mechanism (`core/util/config_yaml_util.py:41-53`) is
untouched: it substitutes file contents into `config.yaml` at load, which is a different layer from
runtime key resolution and remains available.

### Deployment changes (`ak-deployment/ak-aws/`)

Both root modules gain **one** variable, identical in name, type, default and description — the
`enable_scheduling` precedent (`serverless/variables.tf:181`, `containerized/variables.tf:137`):

```hcl
variable "ssm_enabled" {
  type        = bool
  description = "Grant the application roles read access to /ak/<prefix>/* in SSM Parameter Store and inject AK_SECRET__PREFIX, so the application's `secret.provider.type: awssm` can resolve secrets. Terraform does not create the parameters."
  default     = false
}
```

**The change is additive only.** Every resource introduced — one IAM policy document plus one role
attachment per tier — is `count`-gated on `var.ssm_enabled`. No *existing* resource gains a `count`,
changes an argument, or is otherwise modified, so `terraform plan` against a deployment that leaves
the variable at its default is empty.

Propagation, following each root module's own submodule names (they differ, as the `enable_scheduling`
wiring already shows):

| Root | Submodule invocation | Module dir | Role to attach to | Env merge site |
|---|---|---|---|---|
| serverless | `state.tf:544` `module "request_handler"` | `modules/request-handler` | `aws_iam_role.lambda_role` (`main.tf:1`) | `locals.environment_variables` (`main.tf:348`) |
| serverless | `state.tf:628` `module "agent_runner"` | `modules/agent-runner` | `aws_iam_role.agent_runner_lambda_role` (`main.tf:146`) | `locals.environment_variables` (`main.tf:303`) |
| serverless | `state.tf:694` `module "response_handler"` | `modules/response-handler` | `aws_iam_role.response_handler_lambda_role` (`main.tf:64`) | `locals.environment_variables` (`main.tf:242`) |
| serverless | `state.tf:521` `module "ws_connection_handler"` | `modules/ws-connection-handler` | `aws_iam_role.ws_connection_handler_lambda_role` (`main.tf:14`) | `locals.environment_variables` (`main.tf:9`) |
| containerized | `rest_service.tf:4` `module "rest_service"` | `modules/rest-service` | `tasks_iam_role_policies` map (`main.tf:328-338`) | `locals.rest_service_environment` (`main.tf:2-43`) |
| containerized | `queue_mode.tf:23` `module "agent_runner"` | `modules/agent-runner` | `aws_iam_role.agent_runner_task_role` (`main.tf:62`) | `locals.agent_runner_environment` (`main.tf:6`) |

Each of those six submodules gains a same-named `variable "ssm_enabled" { type = bool, default = false }`.
Three of them also need an `account_id` they do not have today, to build the parameter ARN:

- `serverless/modules/response-handler` — **new** `account_id` variable; the root passes
  `data.aws_caller_identity.current.account_id`, as it already does for `request_handler`
  (`state.tf:605`) and `agent_runner` (`state.tf:667`).
- `serverless/modules/ws-connection-handler` — **new** `account_id` variable, same source.
- `containerized/modules/rest-service` — **new** `account_id` variable; the root passes
  `data.aws_caller_identity.current.account_id`, as it already does for the containerized
  `agent_runner` (`queue_mode.tf:73`).

`serverless/modules/request-handler` (`variables.tf:207`), `serverless/modules/agent-runner`
(`variables.tf:105`) and `containerized/modules/agent-runner` (`variables.tf:187`) already have it.
All six already have `region` and `prefix`.

**Environment injection**, added to each module's existing merge, beside the scheduling block it
mirrors (`serverless/modules/request-handler/main.tf:371-375`,
`containerized/modules/rest-service/main.tf:19-23`):

```hcl
    # Secret resolution: the deployment scope only. `secret.provider.type` is deliberately never
    # injected — the application declares it in its committed config.yaml, exactly like `thread.type`.
    var.ssm_enabled ? {
      AK_SECRET__PREFIX = var.prefix
    } : {},
```

`serverless/modules/ws-connection-handler/main.tf:9` is currently a plain assignment
(`environment_variables = var.ws_connection_handler.environment_variables`) and becomes a `merge(...)`
with the same conditional — the only structural edit among the six.

**IAM**, one policy plus one attachment per tier, `count`-gated:

```hcl
resource "aws_iam_policy" "ssm_secret_policy" {
  count = var.ssm_enabled ? 1 : 0
  name  = "${var.prefix}-${local.function_name}-ssm-secret"   # per-module naming, as its siblings do

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadAKSecrets"
        Effect = "Allow"
        # The one call AWSSMSecretProvider makes. No GetParameters, no DescribeParameters,
        # no write or delete action, and never account-wide ssm:*.
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.region}:${var.account_id}:parameter/ak/${var.prefix}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_secret_attachment" {
  count      = var.ssm_enabled ? 1 : 0
  role       = aws_iam_role.<this module's role>.name
  policy_arn = aws_iam_policy.ssm_secret_policy[0].arn
}
```

`containerized/modules/rest-service` has no standalone attachment resources — its task-role policies
go through the upstream ECS module's `tasks_iam_role_policies` map (`main.tf:328-338`), so its entry
is added there instead:

```hcl
    var.ssm_enabled ? {
      SSMSecret = aws_iam_policy.ssm_secret_policy[0].arn
    } : {}
```

Decisions this pins down:

1. **Every tier that receives the variable receives the grant**, including the response handler and
   the WebSocket connection handler. Any of these processes may be the one whose startup calls
   `inject()`; scoping the grant to a subset would make the capability work in one entrypoint and
   fail with an authorization error in another. Note that `ssm_enabled` and the grant are per-tier
   *state*, not a claim that every tier resolves a secret.
2. **The grant lives in the submodule, attached to that submodule's own role**, even though the
   containerized root attaches the *scheduler* policy at root level
   (`containerized/iam.tf:122-126`). The submodule placement is the one both roots can share and is
   what the DynamoDB store policies already do on both sides
   (`containerized/modules/rest-service/main.tf:117`, `serverless/modules/request-handler/main.tf:253`).
3. **No new variable carries the prefix.** `AK_SECRET__PREFIX` is `var.prefix` passed through
   unchanged, so the secret path and the provisioned resource names cannot drift.
4. **No KMS wiring.** `SecureString` parameters are expected to use the AWS-managed `alias/aws/ssm`
   key, whose key policy already permits decryption by principals in the account through the
   `ssm.<region>.amazonaws.com` service condition, so `WithDecryption=True` works with the
   `ssm:GetParameter` grant alone. There is no CMK variable and no `kms:Decrypt` statement; Terraform
   does not create the parameters, so it could not know which key they used.
5. **Terraform never sets `AK_SECRET__PROVIDER__TYPE` or `AK_SECRET__TYPE`**, and never creates a
   parameter. It supplies connection detail; the application declares the backend — the thread and
   schedule split.
6. **The `ssm_enabled` variable is added to both roots in the same change**, even though only one
   deployment mode might be exercised first, because naming and defaulting it identically is what
   keeps the two modes from drifting into incompatible behavior (the `enable_scheduling` precedent).

No root `check` block is added: unlike `enable_scheduling`, `ssm_enabled` has no topology prerequisite
(it works in queue mode and direct mode alike).

Both root READMEs gain a row in their variables table (`serverless/README.md:471` and
`containerized/README.md:368` are the `enable_scheduling` rows to mirror).

### Examples and docs

Two examples move to the SSM path, one per deployment mode, as #749's acceptance criteria require.

**`examples/aws-serverless/openai`** (queue mode; request handler + agent runner + response handler):

- `deploy/main.tf`: add `ssm_enabled = true`; **remove** `"OPENAI_API_KEY" = var.openai_api_key` from
  the `request_handler` (`:53`) and `agent_runner` (`:67`) blocks.
- `deploy/variables.tf`: remove the now-unused `variable "openai_api_key"` (`:17`).
- `config.yaml`: add
  ```yaml
  secret:
    provider:
      type: awssm
    # prefix is injected by Terraform as AK_SECRET__PREFIX
  ```
- `lambda_agent_runner.py`: `SecretManager.current().inject("OPENAI_API_KEY")` as the first statement,
  before the `Agent(...)` definitions and `OpenAIModule([...])`.
- `README.md`: replace the `export TF_VAR_openai_api_key=...` step (`:25`) with the required
  prerequisite, plus the rotation story:
  ```bash
  aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
      --type SecureString --value "$OPENAI_API_KEY" --overwrite
  ```

**`examples/aws-containerized/openai-dynamodb-scalable`** (`queue_mode = true`; rest service + agent runner):

- `deploy/main.tf`: add `ssm_enabled = true`; remove `OPENAI_API_KEY = var.openai_api_key` from the
  `rest_service` (`:29-31`) and `agent_runner` (`:79-81`) blocks.
- `deploy/variables.tf`: remove the now-unused `openai_api_key` variable.
- `config.yaml`: same `secret:` block.
- `app_agent_runner.py`: `SecretManager.current().inject("OPENAI_API_KEY")` before the agents are
  built. `app_rest_service.py` is left unchanged — it never calls the model.
- `README.md`: same prerequisite and rotation sections.

The key passed to `inject` is the SDK's own variable name, and the parameter it resolves from is
`/ak/<prefix>/openai_api_key` — the lowercase mapping `AWSSMSecretProvider` applies, which both
READMEs show side by side so the correspondence is not left implicit.

Both examples pin the **published** Terraform modules (`yaalalabs/ak-serverless/aws` and
`yaalalabs/ak-containerized/aws`, both `version = "0.9.1"`), so `ssm_enabled = true` only applies once
a release publishes the modules carrying it and `scripts/update_examples_version.py` bumps the pins —
the same release sequencing every Terraform-side change in this repo follows.

**CI matrix.** Because the parameter is a manual prerequisite, an unattended deploy cannot resolve the
key: `examples/aws-containerized/openai-dynamodb-scalable` is **removed from `weekly.tests` in
`.github/integration-test-config.yaml:52-54`**. `examples/aws-serverless/openai` needs no matrix edit —
it is `deployment_base` (`.github/integration-test-config.yaml:5-8`), deployed for its VPC/subnet/
security-group outputs and never pytest'd — but its deployed Lambdas will fail at initialization
unless the operator has created the parameter. That is stated here rather than worked around; see
[Resolved open questions](#resolved-open-questions) for the alternative.

The other example deployments stay on environment variables, so both paths are demonstrated side by
side and the unchanged default keeps its coverage.

**Docs surfaces** carrying the key convention (`OPENAI_API_KEY` → `/ak/{prefix}/openai_api_key`), the
resolution order, the four built-in providers, the IAM permissions, the startup-not-hot-path rule with
the uncached-miss cost behind it, the caller responsibility on `inject`, and the rotation story (update
the parameter, then `invalidate` or wait out `cache_ttl`, then re-`inject` if the secret is consumed
through the environment): `ak-deployment/ak-aws/serverless/README.md`,
`ak-deployment/ak-aws/containerized/README.md`, the two example READMEs, and a new page on the docs
site under `docs/docs/`. The plan's final iteration names the exact files.

### Behavioural changes

Exhaustive; each intentional with its justification.

1. **`knowledgebase/starburst.py` reads its four environment variables at construction instead of at
   import.** A process that mutates `os.environ` between importing the module and constructing
   `StarburstManager` now sees the new values. Intentional: it is the point of the change, it brings
   the one outlier in line with `Neo4jManager`, and it is what makes `inject()`'s contract true
   without qualification. A process that sets the variables before import (every documented usage) is
   unaffected.
2. **The module-level names `STARBURST_HOST`/`STARBURST_USER`/`STARBURST_PASSWORD`/`STARBURST_PORT`
   are removed from `agentkernel.knowledgebase.starburst`.** They are undocumented, not in any
   `__all__`, and imported by nothing else in the repo (`starburst.py:62-65` is their only reader),
   but they were importable. Intentional: a constant whose value is frozen at import is exactly the
   defect being fixed, so keeping it as an alias would preserve the bug for anyone reading it. The
   four **environment variables** are unaffected and the documentation that names them stays correct
   (`examples/cli/knowledgebase/openai/starburst/README.md:22-30`,
   `examples/cli/knowledgebase/openai/multi/README.md:29-40`,
   `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:411-414`) — they are now read later, not
   from a different place.
3. **`examples/aws-serverless/openai` and `examples/aws-containerized/openai-dynamodb-scalable` no
   longer receive `OPENAI_API_KEY` from Terraform** and require an SSM parameter the operator creates.
   Intentional: it is the demonstration #749 asks for. Documented in both READMEs.
4. **`examples/aws-containerized/openai-dynamodb-scalable` leaves the weekly CI matrix.** Intentional
   consequence of 3; the coverage loss is called out in the report rather than absorbed.

**Non-changes** — verified, and asserted where a test can:

- No existing `AKConfig` field, default, type or description changes. Existing `config.yaml` files and
  `AK_*` variables keep their meaning.
- No existing public export changes; `secret/` adds names, removes none (except the two starburst
  module constants in 2 above).
- No AK entrypoint gains an `inject` call, a startup sweep, or any knowledge of `secret/`.
- No data layout changes: the capability persists nothing.
- `terraform plan` is empty for any deployment that leaves `ssm_enabled` at its default.
- The `AK_SECRETS_PATH` / `<file:...>` config-load substitution is untouched.
- `inject` never writes to a provider; the capability is read-only against its backend.
- The SSM parameter naming convention is unchanged from design.md — `/ak/{prefix}/openai_api_key` —
  so nothing an operator has already provisioned has to be renamed.

## Error handling

| Condition | Raised | Where | Surfaces as |
|---|---|---|---|
| Key does not match `^[A-Z][A-Z0-9_]*$` | `ValueError` | `LayeredSecretManager._validate_key`, before the provider and before `os.environ` | Programming error; propagates to the caller |
| No layer had the key, no `default` | `SecretNotFoundError` | `get`, `inject` | Message names the key, never a value |
| No layer had the key, `default` supplied | — | `get` returns `default` | Miss only; never on a failure |
| Provider miss (`ParameterNotFound`) | — | falls through to `os.environ[key]` | |
| Provider failure (`AccessDenied`, throttle, credentials, network, any other `ClientError`/`BotoCoreError`) | `SecretError` | `AWSSMSecretProvider.get_secret` | Propagates out of `get`/`inject`; **never** falls through to the environment |
| `secret.prefix` empty with `provider.type: awssm` | `AKConfigError` | `AWSSMSecretProvider.__init__` | At first `SecretManager.current()` |
| `secret.prefix` contains an interior `/` with `provider.type: awssm` | `AKConfigError` | `AWSSMSecretProvider._normalize_prefix` | At first `SecretManager.current()` |
| `secret.cache_ttl` negative in YAML/env | pydantic `ValidationError` | `AKConfig` load (`ge=0`) | At config load |
| `secret.cache_ttl` negative programmatically | `AKConfigError` | `SecretCache.__init__` | At construction |
| Unknown `secret.type` / `secret.provider.type` short name | `AKConfigError` | the factories | At first `SecretManager.current()` |
| Dotted path that will not import or is not a subclass | `AKConfigError` | `resolve_dotted` | At first `SecretManager.current()` |
| `provider.type: awssm` without `boto3` | `ImportError` naming the `aws` extra | `require_extra` in `SecretProviderFactory.create` | At first `SecretManager.current()` |

**Prefix validation belongs to the provider now.** design.md put the empty-prefix fail-fast in
`LayeredSecretManager.from_config` for "any provider other than `noop`". That was correct while the
manager composed the path; it is wrong now, because `in_memory` and `env` are non-`noop` providers
with no use for a prefix and a bring-your-own provider may have none either. The check moved to
`AWSSMSecretProvider`, which is the one component that cannot work without it; a BYO provider needing
a prefix reads `config.prefix` in its own `from_config` and validates it there.

**Where the config failures fire.** The capability has no mount step of its own (unlike the schedule
handler's `get_router()`), so every configuration failure surfaces at the first
`SecretManager.current()`. An application that wants them at build time calls `current()` during
startup — which is where `inject` is called anyway. No `validate_configuration()` classmethod is
added: there is no second surface that would call it.

**Silence rules.** No secret value appears in a log record, an exception message, a trace span or a
response body. `inject` logs at DEBUG naming the variable, never the value. The SSM provider logs at
DEBUG on a miss naming the composed path only.

## Testing

New files under `ak-py/tests/`:

**`tests/test_secret_manager.py`** — `LayeredSecretManager` and the `SecretManager.current()` singleton.
Driven against `InMemorySecretProvider`, which is a real provider rather than a bespoke test double,
so the manager tests and the provider contract exercise the same class:

- Three-layer order, first hit wins: a cache hit does not call the provider; a provider hit does not
  read the environment; a provider miss falls through to `os.environ[key]`.
- **The key is carried through unchanged**: the provider receives exactly `OPENAI_API_KEY`, the cache
  entry is under `OPENAI_API_KEY`, and layer 3 reads `os.environ["OPENAI_API_KEY"]` — no case folding
  and no prefixing anywhere in the manager.
- The environment layer is reached for **every** provider, including `noop`, `in_memory` with nothing
  seeded, and a dotted-path BYO one — no provider can disable it.
- A hit is cached; **a miss is not** — a provider seeded after the first failed `get` resolves on the
  next call, and the provider is called twice.
- `get(key)` on a total miss raises `SecretNotFoundError` whose message contains the key and **does
  not** contain any seeded value.
- `get(key, default="x")` returns `"x"` on a miss, and `get(key, default=None)` returns `None` rather
  than raising — the sentinel assertion.
- `get(key, default="x")` **re-raises** a provider `SecretError` instead of returning the default.
- `inject(key)` sets `os.environ[key]` under that exact name, overwrites an existing value, and raises
  `SecretNotFoundError` on a miss; a resolvable key injected once makes layer 3 non-empty afterwards.
- Key grammar: `"openai_api_key"`, `"Mixed_Case"`, `"BAD-KEY"`, `"1BAD"`, `"BAD/KEY"`, `"A B"`,
  `"A=B"`, `""` each raise `ValueError` from both `get` and `inject`, and a rejected key leaves
  `os.environ` untouched.
- `cache_ttl`: `>0` serves from cache within the window and re-resolves after it (monkeypatched
  `time.monotonic`); `0` re-resolves every call and leaves `invalidate`/`clear` callable; `-1` raises
  `AKConfigError` from `SecretCache`, and a negative value in the model raises a pydantic
  `ValidationError`.
- `invalidate(key)` drops one entry and forces one re-resolution; `clear()` drops all; neither touches
  the provider nor unsets an injected variable.
- **Single-flight**: 8 threads calling `get` on one cold key against a provider that sleeps briefly
  and counts calls produce exactly one provider call and eight identical values.
- `SecretManager.current()` returns the same instance across calls, is rebuilt after `reset()`, and a
  `LayeredSecretManager` subclass calling `current()` gets the configured singleton rather than
  starting its own.
- `TestLayeredManagerContract(SecretManagerContract)` runs the manager contract suite against a
  `LayeredSecretManager` over a seeded `InMemorySecretProvider`.

**`tests/test_secret_providers.py`** — the four built-ins, each against the contract suite:

- `TestNoOpProviderContract(SecretProviderContract)` with `supports_round_trip = False`; plus a direct
  assertion that the declared exemption is honored (the round-trip test does not run for it) and that
  the other assertions do.
- `TestInMemoryProviderContract(SecretProviderContract)`, seeding via `put`. Plus: instances do not
  share state (two providers, one seeded, the other misses) — the assertion that pins instance-level
  rather than class-level storage.
- `TestEnvProviderContract(SecretProviderContract)` with `reads_environment = True`, seeding via
  `monkeypatch.setenv`. The environment assertion runs in its inverted form and must pass.
- `TestAWSSMProviderContract(SecretProviderContract)` with a fake boto3 client (monkeypatched
  `boto3.client`) whose `seed` writes `/ak/<prefix>/<key.lower()>` into the fake's parameter dict, and
  whose `get_parameter` raises a real `botocore.exceptions.ClientError` for an unknown name.
- `AWSSMSecretProvider` addressing, asserted directly rather than only through the contract:
  `OPENAI_API_KEY` requests `Name="/ak/<prefix>/openai_api_key"` with `WithDecryption=True`; `"p"`,
  `"/p"`, `"p/"` and `"/p/"` all compose `/ak/p/...`; `""` and `"a/b"` raise `AKConfigError` at
  construction.
- `AWSSMSecretProvider` error mapping: `ParameterNotFound` → `None`; `AccessDeniedException`,
  `ThrottlingException`, an unrecognized `ClientError` code and a `BotoCoreError` → `SecretError`; and
  a previously returned value never appears in a later exception message.
- Client creation is lazy: constructing the provider calls no boto3 API.

**`tests/test_secret_factory.py`** — both factories:

- `secret.type: layered` builds a `LayeredSecretManager`; an unknown short name raises `AKConfigError`
  naming the built-ins; a dotted path to a `SecretManager` subclass resolves; a dotted path to a
  non-subclass or an unimportable module raises `AKConfigError`.
- `secret.provider.type` for each of `noop`, `in_memory`, `env`, `awssm`, a dotted path, an unknown
  short name, and a non-subclass.
- `provider.type: awssm` with `boto3` made unimportable raises `ImportError` whose message names the
  `aws` extra — and does so *before* the empty-prefix `AKConfigError`, so a missing dependency is not
  reported as a misconfiguration.
- `provider.type: in_memory` / `env` / `noop` build successfully with an **empty** `secret.prefix`,
  pinning that the prefix requirement belongs to `awssm` alone.
- `SecretProviderFactory.create(config)` never calls `AKConfig.get()` — asserted loudly by
  monkeypatching `AKConfig.get` to raise, the `tests/test_pipeline_factory_seams.py` pattern.
- A BYO manager selected by `secret.type` is constructed through its own `from_config` and may ignore
  `prefix`/`provider`/`cache_ttl` entirely.

**`tests/test_knowledgebase_starburst.py`** — new; the riskiest consumer has no test file today:

- `StarburstManager.__init__` reads `STARBURST_HOST/USER/PASSWORD/PORT` from `os.environ` **at
  construction**, so a value set after the module was imported is picked up (the regression this
  change exists for). `trino.dbapi.connect` is monkeypatched, so no network I/O.
- Explicit constructor arguments still win over the environment.
- `STARBURST_PORT` still defaults to `443` and is still coerced to `int`.
- The module no longer exposes the four constants.

**Changed existing files:**

- `tests/test_config.py` — one case that `AKConfig.get().secret` exists with defaults
  (`type="layered"`, `prefix=""`, `provider.type="noop"`, `cache_ttl=300`) and that
  `AK_SECRET__PREFIX` / `AK_SECRET__PROVIDER__TYPE` / `AK_SECRET__CACHE_TTL` populate it through the
  `AK_` + `__` env mechanism. No existing assertion changes.
- No patch target moves, so no other test file changes.

**Fixtures.** `tests/test_secret_manager.py` and `tests/test_secret_factory.py` carry an `autouse`
fixture calling `SecretManager.reset()` before and after each test (the `ScheduleManager.reset()`
fixture at `tests/test_schedule_manager.py:92-97`), and configure the block with the
`_configure_schedule` shape (`tests/test_schedule_manager.py:125-130`): `AKConfig._reset()`, then
`monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"secret": ...})))`.
Every test touching `os.environ` uses `monkeypatch.setenv`/`delenv` so `inject`'s writes do not leak
between tests.

**Run:**

```bash
cd ak-py && uv run pytest tests/test_secret_manager.py tests/test_secret_providers.py \
  tests/test_secret_factory.py tests/test_knowledgebase_starburst.py tests/test_config.py
cd ak-py && uv run pytest          # full suite, no regressions
make lint-check-all
```

Terraform is validated with `terraform init -backend=false && terraform validate` in both root
modules, plus a `terraform plan` on an existing deployment with `ssm_enabled` unset asserting an empty
diff.

## Resolved open questions

Both decisions were taken by the requester while this spec was being written.

1. **`knowledgebase/starburst.py`'s import-time reads** — design.md's only open question. Resolved as
   its recommendation: **move the reads into `StarburstManager.__init__`** (Consumer changes above),
   the `Neo4jManager` shape. It is the only option that leaves `inject()`'s headline claim intact, and
   it is confined to one backend. The alternatives (document the exception; migrate to
   `SecretManager.current().get()`) are not taken — the second was already rejected on the coupling
   rule.
2. **How the examples get their SSM parameter** — resolved as a **README-only manual prerequisite**:
   the examples drop `OPENAI_API_KEY` entirely and their READMEs document `aws ssm put-parameter` as
   required. The consequence, stated rather than hidden, is that
   `examples/aws-containerized/openai-dynamodb-scalable` leaves the weekly CI matrix, and the
   `deployment_base` serverless example deploys Lambdas that fail at init until the parameter exists.
   The alternatives, if that trade is later judged wrong: have each example's `deploy.sh` run
   `aws ssm put-parameter` before `terraform apply` (keeps both in CI and genuinely exercises SSM), or
   keep `OPENAI_API_KEY` as a live fallback (keeps CI green but never resolves from SSM).

## Changes from design.md

The manager's currency changed from a lowercase short key that the manager expanded into a path, to
the environment-variable name itself, with each provider owning its addressing. Four design.md
decisions were superseded; **`design.md` has been updated for all four**, so this section is a change
log rather than an outstanding action.

1. **Key grammar is `^[A-Z][A-Z0-9_]*$`, not `^[a-z][a-z0-9_]*$`** (design.md, Naming and resolution).
   Callers pass `OPENAI_API_KEY`. The grammar still rules out `/`, whitespace, `=` and NUL, and still
   forces one spelling per secret.
   - **Consequence that needs your eye:** the grammar no longer bounds *which* environment variables
     `inject` can write. design.md's argument — "`inject("path")` would clobber `PATH`" — worked
     because the key was lowercase and got uppercased; with no transformation, `inject("PATH")` is a
     well-formed call. Handled as a documented caller responsibility rather than a denylist; see
     `manager.py` decision 2.
2. **The manager composes no path and does no case transformation.** `UPPERCASE(key)`,
   `/ak/{prefix}/{key}` composition and `secret.prefix` all move out of `LayeredSecretManager`.
   `SecretProvider.get_secret` takes the **key**, not a composed path, and `SecretProvider.from_config`
   takes the whole `_SecretConfig` (so a provider can read `prefix`) rather than just
   `_SecretProviderConfig`. The parameter naming convention itself is unchanged —
   `AWSSMSecretProvider` still produces `/ak/{prefix}/openai_api_key` — so Terraform, IAM and any
   already-provisioned parameter are unaffected.
3. **The provider short name is `awssm`, not `ssm`**, and the class is `AWSSMSecretProvider` in
   `providers/awssm.py`. Two more built-ins ship: `in_memory` (seedable, for tests and local dev) and
   `env` (`os.environ` as the backing store, for a BYO manager and for contract coverage without a
   cloud SDK). `noop` remains the default. design.md's argument against naming a provider `env` was
   about the *default*; it still holds, and `env` is not the default.
   - **Consequence:** under `LayeredSecretManager`, `provider.type: env` is observably equivalent to
     `noop`, because layer 3 already reads the same place. Stated in the `EnvSecretProvider` section
     rather than left to be discovered.
4. **The empty-prefix fail-fast moved** from `LayeredSecretManager.from_config` ("any provider other
   than `noop`") to `AWSSMSecretProvider.__init__`. `in_memory` and `env` are non-`noop` providers
   with no use for a prefix, so the old rule would have rejected valid configurations.

Two contract-suite changes, also folded into design.md:

- **`SecretManagerContract` asserts the key grammar** (a sixth assertion), since design.md names the
  grammar as part of the contract a BYO manager must preserve.
- **`SecretProviderContract` has two declared capability flags**, `supports_round_trip` (design.md's
  `NoOpSecretProvider` exemption) and `reads_environment` (new, for `EnvSecretProvider`), and its
  "path used exactly as given" assertion becomes "the key is used verbatim", since addressing is now
  the provider's.

One spec-level detail design.md does not restate:

- **`SecretCache.__init__` raises `AKConfigError` on a negative TTL in addition to the model's
  `ge=0`** — two different boundaries (config load vs. programmatic construction). design.md states
  both behaviours; which object enforces which is this document's.
