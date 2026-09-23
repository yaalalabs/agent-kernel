# #749: Resolve secrets from the environment, falling back to a managed store — Implementation Spec

Adds `agentkernel/secret/`, a top-level capability package beside `sandbox/` and `schedule/`, that
resolves an **environment-variable-style key** (`OPENAI_API_KEY`) to a value through a fixed
three-layer order: `os.environ[key]`, then the process cache, then the configured provider. **A set,
non-empty environment variable always wins**; the provider only supplies keys the environment does
not, and an empty variable is a miss. The manager is a plain key → value mapping in that one
currency — it composes no paths and transforms no names — and each provider owns its own addressing:
`AWSSMSecretProvider` is what turns `OPENAI_API_KEY` into the SSM parameter
`/ak/{prefix}/openai_api_key`. `SecretManager` is one concrete class and is not configurable; the
only config-keyed seam is `SecretProvider` (`secret.provider.type`: built-ins `env` — the default —
and `aws_ssm`, or a dotted path to a bring-your-own subclass), which owns where a value lives. The AWS Terraform root modules gain one additive `ssm_enabled` flag that injects
`AK_SECRET__PREFIX` and grants `ssm:GetParameter` on `parameter/ak/${prefix}/*`.

[`design.md`](design.md) is the requirements source and has been updated to carry the key-shape
change and the non-pluggable manager this spec implements; [Changes from design.md](#changes-from-designmd) is the change log of
what moved, for a reviewer who read the earlier draft. The one question left open while writing this spec
is settled in [Resolved open questions](#resolved-open-questions).

## Design

### Package layout

```
ak-py/src/agentkernel/secret/
├── __init__.py          # public surface (testing.py deliberately excluded)
├── base.py              # SecretProvider ABC
├── errors.py            # SecretError, SecretNotFoundError
├── cache.py             # SecretCache
├── manager.py           # SecretManager (+ current()/reset())
├── factory.py           # SecretProviderFactory
├── testing.py           # SecretProviderContract (imports pytest)
└── providers/
    ├── __init__.py
    ├── env.py           # EnvSecretProvider      — the default; os.environ as the backing store
    └── aws_ssm.py       # AWSSMSecretProvider    — AWS SSM Parameter Store; aws extra
```

Governing rules, in the shape the shared-driver and pipeline rules take:

1. **`secret/` imports `core` only.** Nothing in `core/`, `pipeline/`, `api/`, `deployment/` or
   `integration/` imports `secret/`. The capability is reached by application code calling
   `SecretManager.current()`; no AK entrypoint calls it (design.md, Public API).
2. **The manager's currency is one key, unchanged end to end.** It reads `os.environ` under the key it
   was given, caches under that same key, and hands that same key to the provider. There is no case
   folding, no prefixing and no path composition anywhere in the manager. A future provider
   (Secrets Manager, Vault, Key Vault) therefore needs no manager change.
3. **Each provider owns its own addressing.** `get_secret(key)` receives the env-style key and
   translates it however its backend requires — `AWSSMSecretProvider` to `/ak/{prefix}/{key.lower()}`,
   `EnvSecretProvider` to `os.environ[key]`. A provider never caches and never falls back to another
   layer.
4. **Only `SecretManager.current()` calls `AKConfig.get()`.** `SecretManager.__init__` takes explicit
   parameters (`provider`, `cache_ttl`); `SecretProviderFactory.create` takes the `secret` block
   explicitly. Same rule the shared DB drivers and the #503 factory seams follow.
5. **Every component is a class.** The module-level names are constants only (`_KEY_PATTERN`,
   `_UNSET`, `_BUILTIN_SECRET_PROVIDERS`) — there are no module-level
   functions in the package.
6. **No secret value reaches a log record, an exception message, a trace span or a response body.**
   Log lines and exception messages carry the key name, or the provider's composed address, only.

### `secret/errors.py`

Mirrors `schedule/errors.py`: a flat, documented hierarchy, not a deep one.

```python
class SecretError(Exception):
    """A secret could not be resolved because the backend failed.

    Raised for provider failures — credentials, network, throttling, authorization. A provider
    *miss* is not an error: the provider returns None and the manager reports the miss. Never
    carries a value.
    """


class SecretNotFoundError(SecretError):
    """No layer had the key, and no ``default`` was supplied."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"secret '{key}' not found: no '{key}' environment variable and no provider entry")
```

`SecretNotFoundError` names the key only. Under the old shape it also named the composed path; with
addressing now owned by the provider, the manager has no path to name — a provider that wants its
address diagnosable logs it at DEBUG on the miss (`AWSSMSecretProvider` does).

`SecretNotFoundError` subclasses `SecretError` so a caller that only wants "the capability failed"
catches the base, while a caller distinguishing "absent" from "broken" catches the subclass first.
The reverse hierarchy would force every caller to catch two types.

### `secret/base.py` — `SecretProvider`

```python
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
        calls.

        :raises SecretError: If the backend failed (as opposed to not holding the value).
        """
        raise NotImplementedError
```

This is the package's only ABC. The manager is deliberately not one: its resolution order, cache and
key grammar are fixed (design.md, Pluggability), so an abstract base with a single implementation
would be a seam with nothing to plug into it.

### `secret/manager.py` — `SecretManager`

```python
# Environment-variable-style keys: the names the SDKs already read. Uppercase-only so one secret has
# exactly one spelling across the cache, the provider and os.environ.
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

_UNSET: Any = object()  # "no default supplied"; typed Any so it can default an Optional[str] parameter


class SecretManager:
    """Resolves an environment-variable-style key to a secret value: environment -> cache -> provider.

    The process-wide instance is SecretManager.current(). Keys are the same names the SDKs already
    read from the environment (OPENAI_API_KEY, NEO4J_PASSWORD), so nothing here renames, prefixes or
    case-folds them. A set, non-empty environment variable always wins. Provider-resolved values are
    returned to the caller and held in the cache only; nothing here ever writes os.environ.
    """

    # Guards construction in current()/reset() only. Resolution takes no manager lock: the cache
    # owns its own write lock, and the provider is called outside any lock.
    _instance: ClassVar[Optional["SecretManager"]] = None
    _instance_lock: ClassVar[RLock] = RLock()
    _log = logging.getLogger("ak.secret.manager")

    def __init__(self, provider: SecretProvider, cache_ttl: int = 300) -> None:
        """Constructor arguments are explicit; config reading stays in current()/from_config.

        :raises AKConfigError: If cache_ttl is negative.
        """
        self._provider = provider
        self._cache = SecretCache(cache_ttl)

    @classmethod
    def from_config(cls, config: _SecretConfig) -> "SecretManager":
        """:raises AKConfigError: If the configured provider or its own settings are unusable."""
        return cls(provider=SecretProviderFactory.create(config), cache_ttl=config.cache_ttl)

    @classmethod
    def current(cls) -> "SecretManager":
        """Return the configured process-wide manager, building it on first access.

        Unlike ScheduleManager.get(), this never returns None: the capability is always available
        and its default (env provider) costs nothing.

        :raises AKConfigError: If `secret.provider.type`, `secret.prefix` or `secret.cache_ttl`
                               cannot be resolved to a usable manager.
        """
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls.from_config(AKConfig.get().secret)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared instance so the next current() rebuilds from config. For testing."""
        with cls._instance_lock:
            cls._instance = None

    # -- public API ----------------------------------------------------------------------

    def get(self, key: str, default: Optional[str] = _UNSET) -> Optional[str]:
        self._validate_key(key)
        value = self._resolve(key)
        if value is not None:
            return value
        if default is _UNSET:
            raise SecretNotFoundError(key)
        return default

    def invalidate(self, key: str) -> None:
        self._validate_key(key)
        self._cache.invalidate(key)

    def clear(self) -> None:
        self._cache.clear()

    # -- internals -----------------------------------------------------------------------

    def _resolve(self, key: str) -> Optional[str]:
        """Environment -> cache -> provider, first hit wins. Holds no lock across the sequence."""
        env_value = os.environ.get(key)
        if env_value:  # set and non-empty wins; "" is a miss. Never cached, so re-read every call.
            return env_value
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        value = self._provider.get_secret(key)  # outside any lock; may raise SecretError
        if value is not None:
            self._cache.set(key, value)
        return value

    @staticmethod
    def _validate_key(key: str) -> None:
        """:raises ValueError: If key does not match ^[A-Z][A-Z0-9_]*$."""
```

`current()` builds the manager directly from `AKConfig.get().secret` — there is no manager factory
and no `secret.type`, because there is nothing to select between. `manager.py` imports
`SecretProviderFactory` at module level; `factory.py` imports only `base.py` and the providers, so
there is no import cycle and no deferred import.

`_UNSET` is annotated `Any` so `default: Optional[str] = _UNSET` type-checks under the repo's mypy
settings while the advertised signature stays `Optional[str]` at both ends (design.md, Public API).

### `secret/cache.py` — `SecretCache`

```python
class SecretCache:
    """TTL'd key -> value store holding provider hits only.

    Keyed by the same environment-variable-style key the caller passed, so a cache entry, a provider
    lookup and an environment variable all name one thing. Nothing here transforms the key.

    Owns the cache write lock: held only while writing, evicting or clearing entries. Reads take no
    lock — each entry is one immutable (value, expires_at) tuple swapped in by a single dict
    assignment, so a reader sees either the old entry or the new one, never a torn one.
    """

    def __init__(self, ttl: int) -> None:
        """:raises AKConfigError: If ttl is negative."""
        if ttl < 0:
            raise AKConfigError(f"secret.cache_ttl must be >= 0 (0 disables caching), got {ttl}")
        self._ttl = ttl
        self._entries: dict[str, tuple[str, float]] = {}  # key -> (value, expires_at monotonic)
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, key: str) -> Optional[str]:
        """Return the cached value, or None when absent or expired. Lock-free read; an expired entry
        is evicted under the write lock."""

    def set(self, key: str, value: str) -> None:
        """Store a provider hit under the write lock. A no-op when caching is disabled (ttl == 0)."""

    def invalidate(self, key: str) -> None:
        """Drop one entry under the write lock. Never raises for an unknown key."""

    def clear(self) -> None:
        """Drop every entry under the write lock."""
```

- Expiry uses `time.monotonic()`, not `time.time()`: a wall-clock step (NTP, a suspended container)
  must not extend or truncate a rotation window.
- **Only provider hits are stored.** Environment hits never reach the cache (layer 1 returns before
  it), and `set` is never called with `None`, so a `get` returning `None` is unambiguously "not
  cached" — which is what makes a miss re-resolve on the next call (design.md, Naming and
  resolution).
- Eviction of an expired entry happens under the write lock and removes the entry **only if it is
  still the same expired tuple the read saw**, so a fresh value a concurrent `set` stored in between
  is never dropped.
- `ttl == 0`: `set` stores nothing, `get` always returns `None`, `invalidate`/`clear` stay callable
  no-ops, so no caller branches on the TTL.
- `ttl < 0` raises at construction. The Pydantic model also constrains `ge=0`, so a negative value in
  YAML or `AK_SECRET__CACHE_TTL` is rejected at config load with a `ValidationError`; this check
  covers the programmatic construction path a test takes (`SecretManager(provider, cache_ttl=-1)`). Both boundaries
  are asserted (see Testing).

### `SecretManager` — ordering and locking decisions

The manager has no `prefix`, no `_compose_path` and no `_env_var_name`: with the key carried through
unchanged, all three disappear. Ordering and locking decisions, each of which is testable:

1. **`_validate_key` runs before anything else**, so a malformed key never reaches the provider and
   never reads `os.environ`. The grammar's job is to keep the *name* well-formed — it rules out `/`,
   whitespace, `=` and NUL, which would make an environment-variable name malformed — and to force a
   single spelling so two keys cannot address one cache entry.
2. **The environment is layer 1, and a set, non-empty variable always wins**, for every provider; no
   provider can override it. That precedence is what keeps the 34 existing example deployments
   working unchanged: a key the environment provides is never looked up in the provider.
   - **`""` is a miss** (`if env_value:`), so resolution continues to the cache and the provider. This
     is what lets a deployment keep an existing `"OPENAI_API_KEY" = var.openai_api_key` injection and
     still resolve from SSM by leaving the variable empty.
   - **Environment hits are not cached.** The environment is re-read on every call and is always
     first, so the cache can never shadow a variable that is set later, and caching an env hit would
     buy nothing.
3. **The manager never writes `os.environ`.** There is no `inject`: layer 1 is a read, and a value
   resolved from the provider lives only in `SecretCache` and in whatever the caller does with the
   returned string. A store-held secret therefore never becomes visible to child processes or to any
   other code reading the environment, and a value deleted from the provider stops resolving once its
   cache entry expires — nothing this process wrote keeps it alive.
4. **Two locks, each with one job; the provider call holds neither** (design.md, Public API →
   Concurrency). `_instance_lock` guards construction in `current()`/`reset()`; `SecretCache._lock`
   guards writes, eviction and clearing. Cache reads are lock-free, and `_resolve` holds no lock
   across check→fetch→store, so a slow provider call blocks only its own caller — a `get` for an
   environment-held or cached key never waits behind a cold SSM round trip.
   - **Consequence, accepted:** concurrent `get`s for the same cold key may each call the provider;
     the last write wins, and all writes carry the same value. There is no single-flight. Acceptable
     because resolution belongs to startup.
   - A bring-your-own provider that re-enters the manager (resolving its own credential through
     `get`) cannot deadlock, because no manager lock is held when it is called.
5. **A provider failure propagates out of `_resolve`**, so it is never mistaken for a miss: nothing is
   cached and `get`'s `default` is not returned. `default` is returned on a miss only.
6. **`invalidate`/`clear` touch the cache only.** Neither writes to the provider or the environment,
   and neither can affect a key the environment supplies.

### `secret/factory.py` — `SecretProviderFactory`

Follows the `core/util/factory.py` house shape exactly as `ScheduleProviderFactory`
(`schedule/provider/base.py:103-142`) does: `if`/`elif` real-import branches for built-ins,
`require_extra` around an optional SDK, `resolve_dotted` for any dotted value, `AKConfigError` for an
unknown short name. It is the package's only factory.

```python
_BUILTIN_SECRET_PROVIDERS = ["env", "aws_ssm"]


class SecretProviderFactory:
    """Creates the SecretProvider named by `secret.provider.type`."""

    _log = logging.getLogger("ak.secret.provider.factory")

    @staticmethod
    def create(config: _SecretConfig) -> SecretProvider:
        provider_type = config.provider.type
        SecretProviderFactory._log.info(f"Building '{provider_type}' secret provider")
        key = provider_type.lower()
        if key == "env":
            from .providers.env import EnvSecretProvider

            return EnvSecretProvider.from_config(config)
        if key == "aws_ssm":
            with require_extra("aws", "secret.provider.type: aws_ssm"):
                from .providers.aws_ssm import AWSSMSecretProvider

            return AWSSMSecretProvider.from_config(config)
        if "." not in provider_type:
            raise AKConfigError(
                f"unknown secret provider type '{provider_type}'; expected one of {_BUILTIN_SECRET_PROVIDERS} "
                "or a dotted path to a SecretProvider subclass"
            )
        return resolve_dotted(provider_type, base=SecretProvider).from_config(config)
```

`SecretProviderFactory.create` takes the `secret` block **explicitly** rather than reading `AKConfig`
itself — unlike `ScheduleProviderFactory.create()`, which reads config. `SecretManager.from_config`
already holds the block when it builds its provider, so a second `AKConfig.get()` would re-read a
value the caller has, and a test can build a provider from any `_SecretConfig` without patching
`AKConfig`. This is the same explicit-config seam #503 added to
`QueueTransportFactory.create(queues_config=...)` and `ResponseStoreFactory.create(...)`.

`require_extra` wraps only the `import`, not the construction — matching
`schedule/provider/base.py:133-136`, so an `AKConfigError` raised while validating the prefix is not
relabelled as a missing extra.

### `secret/providers/env.py` — `EnvSecretProvider`

```python
class EnvSecretProvider(SecretProvider):
    """The default backend: os.environ as the store, the key IS the variable name, read verbatim.

    An empty variable is treated as absent, matching the manager's layer-1 rule."""

    def get_secret(self, key: str) -> Optional[str]:
        return os.environ.get(key) or None
```

No credentials, no network, no configuration. This is the local-development and
unchanged-deployment path, and it is why the capability needs no `enabled` flag.

**Under this provider, resolution is effectively environment-only** (design.md, Pluggability):
the provider is reached only after layer 1 has already missed on the same `os.environ[key]`, so it
misses too, and the cache is never populated. The redundant read is a dict lookup that agrees with
layer 1 by construction, so it is left in rather than special-cased: the manager never branches on
which provider it holds. That overlap is stated here rather than left for a reviewer to notice.

No other dependency-free provider ships. Tests that need a seedable backend define one locally and,
where the factory path matters, select it by dotted path (see Testing).

### `secret/providers/aws_ssm.py` — `AWSSMSecretProvider`

This is the only component that knows about paths, prefixes or case.

```python
class AWSSMSecretProvider(SecretProvider):
    """AWS SSM Parameter Store, read-only, one call: GetParameter(WithDecryption=True).

    Addressing: the env-style key OPENAI_API_KEY becomes the parameter /ak/{prefix}/openai_api_key.
    The leading slash is required — SSM rejects a hierarchical name without one — and the IAM
    resource ARN parameter/ak/{prefix}/* is the ARN of exactly this name.
    """

    _log = logging.getLogger("ak.secret.provider.aws_ssm")

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
  `SecretManager.current()`. Without it every lookup would compose `/ak//openai_api_key` — outside
  the provisioned grant — and fail on the first `get` instead of at startup as the configuration
  error it is. The message names `secret.prefix` and `AK_SECRET__PREFIX`.
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
| `ClientError` with code `AccessDeniedException` | **failure** → `SecretError` | The IAM policy is provisioned from the same `prefix` the path is composed from, so a denial means the deployment is misconfigured. Tolerating it as a miss would turn every IAM mistake into a `SecretNotFoundError` — or, worse, a silently returned `default`. |
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
ABC's "must tolerate concurrent calls" requirement.

Per-operation cost: one `GetParameter` per uncached resolution. SSM's standard `GetParameter`
throughput is 40 TPS per account and region and this capability does nothing to raise it. A key the
environment supplies never reaches the provider, but a **miss is not cached**, so a key that is in
neither the environment nor SSM costs a round trip on every call for the life of the process.
Nothing in the code constrains where calls are made from, so the rule the docs carry is: resolve
secrets during startup, never on the request hot path.

### `secret/testing.py` — `SecretProviderContract`

Same conventions as `sandbox/testing.py` and `pipeline/testing.py`: the module imports `pytest`, the
class is deliberately **not** prefixed `Test` so pytest does not collect it on its own, and it is not
exported from `secret/__init__.py` so `import agentkernel.secret` stays free of a pytest dependency.
There is no manager contract suite: the manager is not replaceable, so its behavior is pinned by
`test_secret_manager.py` directly.

```python
class SecretProviderContract:
    """Conformance suite every SecretProvider subclasses. Override `provider` and `seed`.

    One declared capability flag, *read by the suite*, never an ad-hoc skip, so a bring-your-own
    provider gets the same treatment and no provider can quietly opt out of an assertion.
    """

    # True for a backend whose store IS the environment (EnvSecretProvider).
    reads_environment: bool = False

    @pytest.fixture
    def provider(self) -> SecretProvider:
        raise NotImplementedError("subclasses must override the `provider` fixture")

    def seed(self, provider: SecretProvider, key: str, value: str) -> None:
        """Store `value` under `key` in this backend."""
        raise NotImplementedError("subclasses must override `seed`")

    def test_contract_seeded_value_round_trips_verbatim(self, provider): ...
    def test_contract_absent_key_returns_none(self, provider): ...
    def test_contract_key_is_used_verbatim(self, provider): ...
    def test_contract_environment_is_consulted_only_when_declared(self, provider, monkeypatch): ...
```

- **A seeded value round-trips verbatim** — including leading/trailing whitespace and a multi-line
  value, so no backend trims or re-encodes what it was given.
- **An absent key returns `None` rather than raising**, so the manager can report a miss (the
  caller's `default` or `SecretNotFoundError`) distinctly from a failure.
- **The key is used verbatim**: seeding under `CONTRACT_KEY_A` and reading `CONTRACT_KEY_B` misses,
  and reading `CONTRACT_KEY_A` hits — pinning that the provider neither case-folds the key it was
  handed nor collapses two keys onto one address. (How `CONTRACT_KEY_A` is *spelled inside* the
  backend is the provider's business — `AWSSMSecretProvider` legitimately lowercases it into a path;
  what the contract forbids is two distinct keys resolving to one entry.)
- **The environment is consulted only when declared**: with `reads_environment` False, setting
  `os.environ[key]` for an unseeded key must still miss; with it True the same setup must **hit**, so
  the flag cannot be set carelessly just to silence the first form.
- **An omitted fixture or `seed` fails loudly rather than silently skipping**: the base
  implementations `raise NotImplementedError`, so a subclass that forgets one gets an error, not a
  green run. This is the mechanism `SandboxProviderContract.provider` (`sandbox/testing.py:151-154`)
  uses; it is not `pytest.skip`.

### `secret/__init__.py`

```python
__all__ = [
    "errors",
    "EnvSecretProvider",
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
dotted path. `SecretProviderContract` is not exported either (pytest dependency), matching `agentkernel.sandbox`'s treatment of `sandbox/testing.py`.

No top-level alias module (`agentkernel/secret.py`) is added: `agentkernel.schedule` and
`agentkernel.sandbox` are imported by their package path, and the alias modules
(`agentkernel/thread.py`, `agentkernel/agui.py`) exist only for packages that live under
`integration/`.

### Consumer changes

**None.** Every consumer in design.md's Motivation — `knowledgebase/neo4j.py:43-45`,
`knowledgebase/starburst.py:12-15`, `guardrail/walledai.py:46`, `integration/slack/adapter.py:285`,
`sandbox/providers/e2b.py:107`, `sandbox/providers/daytona.py:125` — keeps reading its environment
variable exactly as today. Because the capability never writes `os.environ`, a store-held value does
not reach them on its own; an application that wants one passes `SecretManager.current().get(...)` to
that consumer explicitly (a constructor argument where the consumer takes one). Migrating them is a
design.md non-goal.

**Verified unchanged — no AK entrypoint calls `get`.** `AgentRunner.run()`,
`WebSocketGateway.run()`, `IOHandler.run()`, `RESTAPI.run()`, `ECSIOHandler.run()`,
`ServerlessAgentRunner.handle()` and the Lambda handlers are untouched. Every resolution is an
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
        default="env",
        description="Secret backend: a built-in short name (env, aws_ssm) or a dotted path to a SecretProvider subclass. "
        "'env' reads the environment variable named by the key. 'aws_ssm' is AWS SSM Parameter Store and requires "
        "secret.prefix. Whatever the provider, a set, non-empty environment variable named by the key always wins; "
        "the provider is consulted only when that variable is unset or empty.",
    )


class _SecretConfig(BaseModel):
    """Configuration for secret resolution (deployment scope, backend, cache).

    Always available and free at its defaults, so there is no `enabled` flag: selecting a provider
    other than `env` is the only opt-in, and `provider.type` already expresses it. The resolution
    order is fixed, so there is no manager selector."""

    prefix: str = Field(
        default="",
        description="Deployment scope a provider uses to namespace its secrets, e.g. 'myproduct-dev-agents'. The aws_ssm "
        "provider reads OPENAI_API_KEY from the SSM parameter /ak/{prefix}/openai_api_key. Injected by the AWS Terraform "
        "modules as AK_SECRET__PREFIX from their own resource-naming prefix. Required by aws_ssm; ignored by env",
    )
    provider: _SecretProviderConfig = Field(default_factory=_SecretProviderConfig, description="Backend the secret values are read from")
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
| `secret.prefix` | `AWSSMSecretProvider.from_config` → `__init__` → `_compose_path` | The Terraform `prefix` variable (`ak-deployment/ak-aws/serverless/variables.tf:6`) is not injected into the runtime today, so nothing in `AKConfig` carries the deployment identifier. |
| `secret.provider.type` | `SecretProviderFactory.create` | The factory selector. Nested to match `schedule.provider.type` (`_ScheduleProviderConfig:356`) and to leave room for a provider's own settings sub-block. |
| `secret.cache_ttl` | `SecretCache.__init__`, via `SecretManager.from_config` | The rotation-pickup window; differs per deployment, so it cannot be a constant. Flat rather than a `cache:` sub-block because there is exactly one cache setting. |

- **No `secret.type` manager selector.** `SecretManager` is one concrete class; a selector with a
  single possible value would be a knob with nothing to choose between.
- **No `enabled` flag.** The capability is always available and costs nothing at its default, so
  nothing has to be opted into — the house rule reserves `enabled` for features with a real cost
  (`sandbox.enabled`, `trace.enabled`).
- **No `secret.provider.aws_ssm` sub-block.** `prefix` stays top-level because it is a deployment-wide
  scope a second managed-store provider would key off identically; putting it under `aws_ssm` would
  force the next provider to redeclare it, and would change the `AK_SECRET__PREFIX` variable the
  Terraform modules inject. Nothing else about the SSM provider is configurable: region and
  credentials come from the boto3 environment default, and decryption rides the AWS-managed key.
- **`_SecretConfig` is non-`Optional` with a `default_factory`**, unlike `thread` and `schedule`.
  Those use block presence as their enabled-check; this capability has no enabled-check, and a
  non-`Optional` block means `AKConfig.get().secret` never needs a `None` guard.

**Compatibility.** Every field has a default and the default provider (`env`) changes no behavior, so:
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
  description = "Grant the application roles read access to /ak/<prefix>/* in SSM Parameter Store and inject AK_SECRET__PREFIX, so the application's `secret.provider.type: aws_ssm` can resolve secrets. Terraform does not create the parameters."
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
The parameter ARN wildcards the account segment (`arn:aws:ssm:<region>:*:parameter/...`), so no
module needs an `account_id` for it. All six already have `region` and `prefix`.

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
        Resource = "arn:aws:ssm:${var.region}:*:parameter/ak/${var.prefix}/*"
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
   `get()`; scoping the grant to a subset would make the capability work in one entrypoint and
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
5. **Terraform never sets `AK_SECRET__PROVIDER__TYPE`**, and never creates a
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
Each **keeps** its existing `OPENAI_API_KEY` injection and makes it optional, so the same deployment
demonstrates both paths (design.md, Examples and docs):

- `openai_api_key` set → the variable is injected non-empty and wins (today's behavior).
- `openai_api_key` left empty → `""` is injected, which is a miss, so the key resolves from
  `/ak/<prefix>/openai_api_key` — and no secret value is in Terraform state.

**`examples/aws-serverless/openai`** (queue mode; request handler + agent runner + response handler):

- `deploy/main.tf`: add `ssm_enabled = true`. The `"OPENAI_API_KEY" = var.openai_api_key` entries in
  the `request_handler` (`:53`) and `agent_runner` (`:67`) blocks are **kept unchanged**.
- `deploy/variables.tf`: give `variable "openai_api_key"` (`:17`) `default = ""` and a description
  saying that leaving it empty resolves the key from SSM.
- `config.yaml`: add
  ```yaml
  secret:
    provider:
      type: aws_ssm
    # prefix is injected by Terraform as AK_SECRET__PREFIX
  ```
- `lambda_agent_runner.py`: as the first statements, before the `Agent(...)` definitions and
  `OpenAIModule([...])`:
  ```python
  from agents import set_default_openai_key
  from agentkernel.secret import SecretManager

  set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))
  ```
  `set_default_openai_key` is the OpenAI Agents SDK's in-memory key setter, so a key resolved from
  SSM reaches the SDK without passing through `os.environ`. When the variable is set, `get` returns
  it from layer 1 and the call is a harmless re-set of the value the SDK would read anyway.
- `README.md`: make the `export TF_VAR_openai_api_key=...` step (`:25`) optional and document the two
  paths: set it (environment wins), or leave it unset and create the parameter first:
  ```bash
  aws ssm put-parameter --name "/ak/<prefix>/openai_api_key" \
      --type SecureString --value "$OPENAI_API_KEY" --overwrite
  ```
  plus the rotation story.

**`examples/aws-containerized/openai-dynamodb-scalable`** (`queue_mode = true`; rest service + agent runner):

- `deploy/main.tf`: add `ssm_enabled = true`. The `OPENAI_API_KEY = var.openai_api_key` entries in the
  `rest_service` (`:29-31`) and `agent_runner` (`:79-81`) blocks are **kept unchanged**.
- `deploy/variables.tf`: give the `openai_api_key` variable (`:17`) `default = ""`.
- `config.yaml`: same `secret:` block.
- `app_agent_runner.py`: the same `set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))`
  before the agents are built. `app_rest_service.py` is left unchanged — it never calls the model.
- `README.md`: same two-path, prerequisite and rotation sections (`TF_VAR_openai_api_key` at `:59`).

Each example is deployed and exercised on **both** paths — variable set, variable empty — before the
change merges (design.md, Examples and docs).

The key passed to `get` is the SDK's own variable name, and the parameter it resolves from is
`/ak/<prefix>/openai_api_key` — the lowercase mapping `AWSSMSecretProvider` applies, which both
READMEs show side by side so the correspondence is not left implicit.

Both examples pin the **published** Terraform modules (`yaalalabs/ak-serverless/aws` and
`yaalalabs/ak-containerized/aws`, both `version = "0.9.1"`), so `ssm_enabled = true` only applies once
a release publishes the modules carrying it and `scripts/update_examples_version.py` bumps the pins —
the same release sequencing every Terraform-side change in this repo follows.

**CI matrix — no change.** The integration workflows already export
`TF_VAR_openai_api_key: ${{ secrets.OPENAI_API_KEY }}` (`.github/workflows/integration-test.yaml:116`,
`integration-test-weekly.yaml:128` and siblings), so in CI the variable is injected non-empty and
wins; `examples/aws-serverless/openai` (`deployment_base`, `.github/integration-test-config.yaml:5-8`)
and `examples/aws-containerized/openai-dynamodb-scalable` (`weekly.tests`, `:52-54`) both stay where
they are and keep passing. With `ssm_enabled = true` the tiers also carry `AK_SECRET__PREFIX` and the
`ssm:GetParameter` grant, so `AWSSMSecretProvider` constructs cleanly at `current()` even though it is
never called. The SSM path itself is exercised by the manual variable-empty deployment above, not by
CI.

The other example deployments stay on environment variables unchanged.

**Docs surfaces** carrying the key convention (`OPENAI_API_KEY` → `/ak/{prefix}/openai_api_key`), the
resolution order (environment first, `""` is a miss), the supported provider types (`env`, `aws_ssm`,
dotted path), the IAM permissions, creating the parameter manually as a `SecureString`, the startup-not-hot-path rule with
the uncached-miss cost behind it, that resolved values are never exported to the environment and must
be handed to the SDK, and the rotation story (update the parameter, then `invalidate` or wait out
`cache_ttl`, then hand the newly resolved value to the SDK): `ak-deployment/ak-aws/serverless/README.md`,
`ak-deployment/ak-aws/containerized/README.md`, the two example READMEs, and a new page on the docs
site under `docs/docs/`. The plan's final iteration names the exact files.

### Behavioural changes

Exhaustive; each intentional with its justification.

1. **In `examples/aws-serverless/openai` and `examples/aws-containerized/openai-dynamodb-scalable`,
   `openai_api_key` becomes optional** (`default = ""`), the tiers gain the SSM grant and
   `AK_SECRET__PREFIX`, and the agent runner hands the resolved key to the SDK. With the variable set
   — as CI and every existing deployer set it — behavior is unchanged; left empty, the key resolves
   from the SSM parameter the operator creates. Intentional: it is the demonstration #749 asks for.
   Documented in both READMEs.

No CI matrix entry changes.

**Non-changes** — verified, and asserted where a test can:

- No existing `AKConfig` field, default, type or description changes. Existing `config.yaml` files and
  `AK_*` variables keep their meaning.
- No existing public export changes; `secret/` adds names, removes none.
- No existing consumer changes, including `knowledgebase/starburst.py`.
- No AK entrypoint gains a `get` call, a startup sweep, or any knowledge of `secret/`.
- No data layout changes: the capability persists nothing.
- `terraform plan` is empty for any deployment that leaves `ssm_enabled` at its default.
- The `AK_SECRETS_PATH` / `<file:...>` config-load substitution is untouched.
- The capability never writes `os.environ` or the provider; it is read-only against both.
- The SSM parameter naming convention is unchanged from design.md — `/ak/{prefix}/openai_api_key` —
  so nothing an operator has already provisioned has to be renamed.

## Error handling

| Condition | Raised | Where | Surfaces as |
|---|---|---|---|
| Key does not match `^[A-Z][A-Z0-9_]*$` | `ValueError` | `SecretManager._validate_key`, before `os.environ` and before the provider | Programming error; propagates to the caller |
| Environment variable set to `""` | — | `SecretManager._resolve` | A miss: continues to the cache and the provider |
| No layer had the key, no `default` | `SecretNotFoundError` | `get` | Message names the key, never a value |
| No layer had the key, `default` supplied | — | `get` returns `default` | Miss only; never on a failure; not cached |
| Provider miss (`ParameterNotFound`) | — | provider returns `None` | `get` returns `default` or raises `SecretNotFoundError` |
| Provider failure (`AccessDenied`, throttle, credentials, network, any other `ClientError`/`BotoCoreError`) | `SecretError` | `AWSSMSecretProvider.get_secret` | Propagates out of `get`; **never** treated as a miss, never cached |
| `secret.prefix` empty with `provider.type: aws_ssm` | `AKConfigError` | `AWSSMSecretProvider.__init__` | At first `SecretManager.current()` |
| `secret.prefix` contains an interior `/` with `provider.type: aws_ssm` | `AKConfigError` | `AWSSMSecretProvider._normalize_prefix` | At first `SecretManager.current()` |
| `secret.cache_ttl` negative in YAML/env | pydantic `ValidationError` | `AKConfig` load (`ge=0`) | At config load |
| `secret.cache_ttl` negative programmatically | `AKConfigError` | `SecretCache.__init__` | At construction |
| Unknown `secret.provider.type` short name | `AKConfigError` | `SecretProviderFactory.create` | At first `SecretManager.current()` |
| Dotted path that will not import or is not a subclass | `AKConfigError` | `resolve_dotted` | At first `SecretManager.current()` |
| `provider.type: aws_ssm` without `boto3` | `ImportError` naming the `aws` extra | `require_extra` in `SecretProviderFactory.create` | At first `SecretManager.current()` |

**Prefix validation belongs to the provider.** The empty-prefix fail-fast lives in
`AWSSMSecretProvider`, the one component that cannot work without it — not in the manager, because
`env` has no use for a prefix and a bring-your-own provider may have none either. A BYO provider
needing a prefix reads `config.prefix` in its own `from_config` and validates it there.

**Where the config failures fire.** The capability has no mount step of its own (unlike the schedule
handler's `get_router()`), so every configuration failure surfaces at the first
`SecretManager.current()`. An application that wants them at build time calls `current()` during
startup — which is where secrets are resolved anyway. No `validate_configuration()` classmethod is
added: there is no second surface that would call it.

**Silence rules.** No secret value appears in a log record, an exception message, a trace span or a
response body. The SSM provider logs at
DEBUG on a miss naming the composed path only.

## Testing

New files under `ak-py/tests/`:

**`tests/test_secret_manager.py`** — `SecretManager` and its `current()` singleton. Driven against a
test-local `_DictSecretProvider(SecretProvider)` — a seedable, `Lock`-guarded dict that counts calls,
so it is safe under the concurrent calls the ABC requires and a faithful stand-in in the concurrency
tests. It lives in the test module, not the package, and is also referenced by dotted path where the
factory path is under test:

- Three-layer order, first hit wins: a set, non-empty environment variable is returned **and the
  provider is not called**, even when the provider is seeded with a different value and the cache
  holds one; with the variable unset, a cache hit does not call the provider; with both missing, the
  provider is called.
- **The environment wins for every provider** — `env`, `aws_ssm` seeded with a different value (the
  fake client records no `get_parameter` call), and a seeded dotted-path `_DictSecretProvider` (zero
  provider calls) — no provider can override it.
- **`""` is a miss**: with `monkeypatch.setenv(key, "")` and a seeded provider, `get` returns the
  provider's value — including `aws_ssm`, whose fake client then records the call.
- **Environment hits are not cached**: after an env hit, `delenv` the variable — the next `get` goes to
  the provider (hit) or raises `SecretNotFoundError` (unseeded), never returns the old env value.
- A variable set **after** a provider hit was cached wins on the next `get` — the cache never shadows
  the environment.
- **The key is carried through unchanged**: layer 1 reads `os.environ["OPENAI_API_KEY"]`, the cache
  entry is under `OPENAI_API_KEY`, and the provider receives exactly `OPENAI_API_KEY` — no case folding
  and no prefixing anywhere in the manager.
- A provider hit is cached; **a miss is not** — a provider seeded after the first failed `get` resolves
  on the next call, and the provider is called twice.
- `get(key)` on a total miss raises `SecretNotFoundError` whose message contains the key and **does
  not** contain any seeded value.
- `get(key, default="x")` returns `"x"` on a miss, and `get(key, default=None)` returns `None` rather
  than raising — the sentinel assertion.
- `get(key, default="x")` **re-raises** a provider `SecretError` instead of returning the default.
- **`get` never writes `os.environ`**: after a provider hit for an unset variable, the variable is
  still absent; after a provider hit for a variable set to `""`, it is still `""`. There is no
  `inject` attribute on `SecretManager`.
- Key grammar: `"openai_api_key"`, `"Mixed_Case"`, `"BAD-KEY"`, `"1BAD"`, `"BAD/KEY"`, `"A B"`,
  `"A=B"`, `""` each raise `ValueError` from `get`, and a rejected key leaves
  `os.environ` untouched.
- `cache_ttl`: `>0` serves from cache within the window and re-resolves after it (monkeypatched
  `time.monotonic`); `0` re-resolves every call and leaves `invalidate`/`clear` callable; `-1` raises
  `AKConfigError` from `SecretCache`, and a negative value in the model raises a pydantic
  `ValidationError`.
- `invalidate(key)` drops one entry and forces one re-resolution; `clear()` drops all; neither touches
  the provider or the environment.
- **Concurrent cold reads**: 8 threads calling `get` on one cold key against a provider that sleeps
  briefly produce eight identical values and between 1 and 8 provider calls — pinning correctness,
  not single-flight, which design.md deliberately does not provide.
- **The provider call holds no lock**: while one thread is parked inside a provider call for key `A`
  (blocked on a `threading.Event`), a `get` for a cached key `B` and a `get` for an environment-held
  key `C` both return without waiting; `invalidate`/`clear` also return.
- A provider that re-enters the manager (`get_secret` calls `SecretManager.current().get(...)` for a
  different, environment-held key) completes without deadlock.
- `SecretCache` eviction never drops a fresh entry: an expired entry replaced by a concurrent `set`
  between the read and the eviction survives (driven deterministically with a monkeypatched
  `time.monotonic`).
- `SecretManager.current()` returns the same instance across calls, is built from
  `AKConfig.get().secret`, and is rebuilt after `reset()`.
- `invalidate`/`clear` are callable and non-raising on an unknown key.

**`tests/test_secret_providers.py`** — both built-ins, each against the contract suite:

- `TestEnvProviderContract(SecretProviderContract)` with `reads_environment = True`, seeding via
  `monkeypatch.setenv`. The environment assertion runs in its inverted form and must pass.
- `EnvSecretProvider` returns `None` for a variable set to `""`.
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
- `TestDictProviderContract(SecretProviderContract)` runs the suite against the test-local
  `_DictSecretProvider`, so the double the manager tests rely on is itself held to the contract.

**`tests/test_secret_factory.py`** — `SecretProviderFactory`:

- `secret.provider.type` for each of `env`, `aws_ssm`, a dotted path to a `SecretProvider` subclass, an
  unknown short name (`AKConfigError` naming `env` and `aws_ssm`), a dotted path to a non-subclass, and
  an unimportable dotted path. `noop`, `in_memory` and the old spelling `awssm` are asserted to be
  **unknown** short names.
- `provider.type: aws_ssm` with `boto3` made unimportable raises `ImportError` whose message names the
  `aws` extra — and does so *before* the empty-prefix `AKConfigError`, so a missing dependency is not
  reported as a misconfiguration.
- `provider.type: env` and a dotted-path provider build successfully with an **empty**
  `secret.prefix`, pinning that the prefix requirement belongs to `aws_ssm` alone.
- `SecretProviderFactory.create(config)` never calls `AKConfig.get()` — asserted loudly by
  monkeypatching `AKConfig.get` to raise, the `tests/test_pipeline_factory_seams.py` pattern.
- A dotted-path provider is constructed through its own `from_config` and receives the whole
  `secret` block, including `prefix`.

**Changed existing files:**

- `tests/test_config.py` — cases that `AKConfig.get().secret` exists with defaults
  (`prefix=""`, `provider.type="env"`, `cache_ttl=300`, and no `type` field), that
  `AK_SECRET__PREFIX` / `AK_SECRET__PROVIDER__TYPE` / `AK_SECRET__CACHE_TTL` populate it through the
  `AK_` + `__` env mechanism, and that `AK_SECRET__CACHE_TTL=-1` is rejected at load. No existing
  assertion changes.
- No patch target moves, so no other test file changes.

**Fixtures.** `tests/test_secret_manager.py` and `tests/test_secret_factory.py` carry an `autouse`
fixture calling `SecretManager.reset()` before and after each test (the `ScheduleManager.reset()`
fixture at `tests/test_schedule_manager.py:92-97`), and configure the block with the
`_configure_schedule` shape (`tests/test_schedule_manager.py:125-130`): `AKConfig._reset()`, then
`monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"secret": ...})))`.
Every test touching `os.environ` uses `monkeypatch.setenv`/`delenv` so seeded variables do not leak
between tests.

**Run:**

```bash
cd ak-py && uv run pytest tests/test_secret_manager.py tests/test_secret_providers.py \
  tests/test_secret_factory.py tests/test_config.py
cd ak-py && uv run pytest          # full suite, no regressions
make lint-check-all
```

Terraform is validated with `terraform init -backend=false && terraform validate` in both root
modules, plus a `terraform plan` on an existing deployment with `ssm_enabled` unset asserting an empty
diff.

## Resolved open questions

Taken by the requester while this spec was being written.

1. **How the examples get their SSM parameter** — resolved by design.md's environment-first order:
   each example **keeps** its `OPENAI_API_KEY` injection with `openai_api_key` defaulting to `""`, and
   its README documents `aws ssm put-parameter` as the prerequisite for the variable-empty path.
   Setting the variable keeps today's behavior; leaving it empty resolves from SSM. CI keeps setting
   the variable, so neither example leaves its matrix and no deployed Lambda fails at init. The
   trade, stated rather than hidden: **CI never exercises the SSM path** — it is covered by the
   manual both-path deployment each example gets before merge. If unattended SSM coverage is wanted
   later, the follow-up is an example `deploy.sh` that runs `aws ssm put-parameter` and deploys with
   the variable empty.

## Changes from design.md

Four rounds of change, all folded into `design.md`, so this section is a change log for a reviewer
who read an earlier draft rather than an outstanding action.

**Round 1 — the key is the environment-variable name, and each provider owns its addressing.**

1. **Key grammar is `^[A-Z][A-Z0-9_]*$`, not `^[a-z][a-z0-9_]*$`** (design.md, Naming and resolution).
   Callers pass `OPENAI_API_KEY`. The grammar still rules out `/`, whitespace, `=` and NUL, and still
   forces one spelling per secret.
   - **Consequence that needs your eye:** the grammar no longer bounds *which* environment variables
     `inject` can write. The earlier argument — "`inject("path")` would clobber `PATH`" — worked
     because the key was lowercase and got uppercased; with no transformation, `inject("PATH")` is a
     well-formed call. Handled at the time as a documented caller responsibility; made moot by
     round 3, which removes `inject`.
2. **The manager composes no path and does no case transformation.** `UPPERCASE(key)`,
   `/ak/{prefix}/{key}` composition and `secret.prefix` all move out of the manager.
   `SecretProvider.get_secret` takes the **key**, not a composed path, and `SecretProvider.from_config`
   takes the whole `_SecretConfig` (so a provider can read `prefix`) rather than just
   `_SecretProviderConfig`. The parameter naming convention itself is unchanged —
   `AWSSMSecretProvider` still produces `/ak/{prefix}/openai_api_key` — so Terraform, IAM and any
   already-provisioned parameter are unaffected.
3. **The provider short name is `awssm`, not `ssm`**, and the class is `AWSSMSecretProvider` in
   `providers/awssm.py`. (Renamed to `aws_ssm` / `providers/aws_ssm.py` in round 4.)
4. **The empty-prefix fail-fast moved** from the manager's `from_config` to
   `AWSSMSecretProvider.__init__`, since it is the only provider that needs a prefix.
5. **`SecretProviderContract`'s "path used exactly as given" assertion became "the key is used
   verbatim"**, since addressing is now the provider's, and it gained the `reads_environment` flag for
   `EnvSecretProvider`.

**Round 2 — the manager is not pluggable, and the provider set is `env`, `awssm`, dotted path.**

6. **`secret.type` is removed.** There is no `SecretManager` ABC, no `LayeredSecretManager`, no
   `SecretManagerFactory` and no `SecretManagerContract`. `SecretManager` is one concrete class in
   `manager.py` that owns `current()`/`reset()` and builds itself from `AKConfig.get().secret`. The
   behaviors the manager contract asserted (miss raises, default on miss only, `default=None`, key grammar, `invalidate`/`clear` non-raising) are asserted directly in
   `test_secret_manager.py`.
7. **`noop` and `in_memory` are removed; `env` is the default.** Supported `secret.provider.type`
   values are `env`, `awssm` and a dotted path to a `SecretProvider` subclass.
   - **Consequence:** with `env` as the default, the provider and the manager's third layer read the
     same place, so resolution at the default is cache + environment — the same observable behavior
     `noop` had. Stated in the `EnvSecretProvider` section.
   - **Consequence:** the seedable test double moves out of the package into
     `tests/test_secret_manager.py` as `_DictSecretProvider`, held to `SecretProviderContract` and
     reachable by dotted path.
   - `SecretProviderContract` loses its `supports_round_trip` flag, which existed only for `noop`.

**Round 3 — no `inject`; values stay in memory.**

8. **`inject` is removed.** The public API is `get`/`invalidate`/`clear`. A resolved value is held in
   `SecretCache` and returned to the caller; the capability never writes `os.environ`, and layer 3 is
   a read only. The examples hand the key to the OpenAI Agents SDK with
   `set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))`.
9. **The Starburst change is dropped.** Moving `knowledgebase/starburst.py`'s reads into `__init__`
   existed only so `inject` could reach an import-time reader; with no `inject`, no existing consumer
   is reached by a store-held value either way, so the change, its test file and design.md's open
   question are removed. This change touches no existing consumer.

**Round 4 — the environment comes first.**

10. **Resolution order is environment → cache → provider**, replacing cache → provider → environment.
    A set, non-empty variable always wins and the provider only supplies keys the environment does
    not; the issue's store-first order is a requester-confirmed non-goal (design.md, Non-goals).
    - **`""` is a miss**, so an existing injection left empty resolves from the provider.
    - **Environment hits are not cached**; only provider hits are.
    - **Consequence:** under `env`, resolution is environment-only rather than cache + environment.
11. **Two locks, no single-flight.** The single `RLock` held across check→fetch→store is replaced by
    the singleton lock plus a write-only lock owned by `SecretCache`; cache reads are lock-free and the
    provider is called outside any lock. Concurrent cold reads may each call the provider. The
    single-flight test is replaced by concurrent-correctness, no-lock-across-provider and re-entrancy
    tests.
12. **The provider short name is `aws_ssm`**, module `providers/aws_ssm.py`, logger
    `ak.secret.provider.aws_ssm` — matching the repo's snake_case built-in names (`ec2_ssm`,
    `bedrock_agentcore`). The class stays `AWSSMSecretProvider`.
13. **The examples keep their `OPENAI_API_KEY` injection**, with `openai_api_key` defaulting to `""`,
    instead of dropping it. Consequence: no CI matrix change; the SSM path is exercised manually.
14. **`EnvSecretProvider` treats `""` as absent**, matching the layer-1 rule.

One spec-level detail design.md does not restate:

- **`SecretCache.__init__` raises `AKConfigError` on a negative TTL in addition to the model's
  `ge=0`** — two different boundaries (config load vs. programmatic construction). design.md states
  both behaviours; which object enforces which is this document's.
