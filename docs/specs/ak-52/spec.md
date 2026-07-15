# AK-52: Shared database drivers for Session, Multimodal, and Response Store backends

This change extracts the duplicated database connection drivers (Redis, Valkey, DynamoDB, Cosmos DB,
Firestore) out of the Session, Multimodal attachment, and Response Store subsystems into a single
shared package, `ak-py/src/agentkernel/core/util/drivers/`. The stores keep their subsystem-specific
data layouts, key schemas, and factories; only the connection layer (client creation, lazy connect,
retry, health-check/reconnect, TTL plumbing) becomes shared.

## Motivation

The same connection logic is copy-pasted across three subsystems today:

1. **Session stores** (`ak-py/src/agentkernel/core/session/`) — `RedisDriver` (`redis.py:14`),
   `ValkeyDriver` (`valkey.py:14`), `DynamoDBDriver` (`dynamodb.py:15`), `CosmosDBDriver`
   (`cosmosdb.py:14`), `FirestoreDriver` (`firestore.py:15`). Each has a lazy client, a `_connect()`
   with 3 retries and a 2-second delay, and (for Redis/Valkey) a `client` property that pings and
   reconnects on failure. Each reads its own `AKConfig.get().session.*` section in `__init__`.
2. **Multimodal attachment stores** (`ak-py/src/agentkernel/core/multimodal/storage/`) —
   `RedisAttachmentDriver` (`redis.py:16`) and `DynamoDBAttachmentDriver` (`dynamodb.py:21`) are
   near-identical re-implementations of the session drivers, differing only in that they take
   explicit constructor parameters instead of reading `AKConfig`.
3. **Response stores** (`ak-py/src/agentkernel/deployment/aws/core/response_store/`) —
   `RedisResponseStore` (`redis.py:8`), `ValkeyResponseStore` (`valkey.py:8`), and
   `DynamoDBResponseStore` (`dynamodb.py:8`) create their clients eagerly in `__init__` with **no
   retry and no health-check/reconnect** — an existing inconsistency versus the other two families.

Concrete duplication:

- `core/session/redis.py` and `core/session/valkey.py` are near-identical clones of each other
  (the `valkey` Python client is a fork of `redis-py` with an identical API). They differ only in
  the missing-config `ValueError` check (Valkey has one, Redis does not) and in `exists()` error
  handling (see Behavioural changes). The twin relationship between `response_store/redis.py` and
  `response_store/valkey.py` is exact.
- The `_connect()` retry loop (3 attempts, 2 s delay, re-raise last error) appears in seven places.
- The lazy-client-plus-ping health check appears in three places (session Redis, session Valkey,
  multimodal Redis) and is *missing* from the three response stores.
- The DynamoDB "boto3 resource → `Table(...)`" sequence appears in three places (with the
  `.load()` existence check in two of them — the response store skips it), and the
  `expiry_time = now + ttl` TTL-attribute logic in three places.
- Config classes for the same connection parameters are defined twice: the response-store configs
  already subclass the session ones (`_ResponseStoreRedisConfig(_RedisConfig)` at
  `core/config.py:235`), but the multimodal configs (`_MultimodalStorageRedisConfig` at
  `core/config.py:178`, `_MultimodalStorageDynamoDBConfig` at `core/config.py:184`) redefine
  `url`/`ttl`/`prefix`/`table_name` from scratch.

Any fix to connection handling (timeouts, retry policy, reconnect behaviour) currently has to be
made in up to seven files, and in practice hasn't been — which is how the response stores ended up
without retry or reconnect at all.

## Design

### New package: `core/util/drivers/`

```
ak-py/src/agentkernel/core/util/drivers/
├── __init__.py        # no eager imports of optional client libraries
├── base.py            # shared retry helper
├── redis_like.py      # _RedisLikeDriver — all Redis/Valkey logic, client-library-agnostic
├── redis.py           # RedisDriver(_RedisLikeDriver)
├── valkey.py          # ValkeyDriver(_RedisLikeDriver)   (requires the `valkey` extra)
├── dynamodb.py        # DynamoDBDriver
├── cosmosdb.py        # CosmosDBDriver                   (requires the `azure` extra)
└── firestore.py       # FirestoreDriver                  (requires the `gcp` extra)
```

Two rules govern the package:

1. **Drivers never read `AKConfig`.** All connection parameters are explicit constructor arguments
   (the pattern the multimodal drivers already use). Config reading, config-section validation, and
   "which backend?" decisions stay in the stores and factories. This is what makes the drivers
   reusable from both `core/` and `deployment/` without coupling `core/util` to specific config
   sections.
2. **Drivers own the connection lifecycle and a generic command surface; data layout stays in the
   stores.** Key schemas (session hash layout, attachment index lists, response-message items),
   serialization (`BinarySerde`, JSON), and pruning logic remain in the store classes.

`drivers/__init__.py` must not import the driver modules eagerly: `redis`, `valkey`,
`azure-data-tables`, and `google-cloud-firestore` are all optional dependencies (via the `redis`,
`valkey`, `azure`, and `gcp` extras respectively), and the existing factories import backend
modules lazily behind `try/except ImportError`. Consumers import the concrete module
(`from agentkernel.core.util.drivers.redis import RedisDriver`) exactly as they import store
modules today.

All drivers get the uniform connection behaviour that the session drivers have today: lazy connect
on first use, 3 connection attempts with a 2-second delay, re-raise of the last error, and (for
Redis/Valkey) a ping health-check with automatic reconnect on every `client` access.

### `_RedisLikeDriver`, `RedisDriver`, `ValkeyDriver`

Since `valkey-py` mirrors `redis-py`'s API, all logic lives once in `_RedisLikeDriver`; the two
concrete classes only supply the client library:

```python
class _RedisLikeDriver:
    # subclasses set these
    _backend_name: str            # "Redis" / "Valkey" — used in log messages
    _error_class: type[Exception] # redis.RedisError / valkey.ValkeyError

    def __init__(self, url: str, prefix: str = "", ttl: int = 0, decode_responses: bool = False): ...

    def _from_url(self, url: str, **kwargs): ...   # abstract: redis.from_url / valkey.from_url

    @property
    def client(self): ...        # lazy connect; else ping, reconnect on _error_class
    @property
    def ttl(self) -> int: ...
    def key(self, suffix: str) -> str: ...          # f"{prefix}{suffix}"

    # string ops
    def set(self, key, value) -> None: ...          # applies ex=ttl when ttl > 0
    def get(self, key) -> Any: ...
    def delete(self, *keys) -> None: ...
    def exists(self, key) -> bool: ...
    # hash ops (used by session stores)
    def hset(self, key, field, value) -> None: ...
    def hget(self, key, field) -> Optional[bytes]: ...
    def hkeys(self, key) -> list[str]: ...          # decodes bytes field names
    # list ops (used by the attachment index)
    def rpush(self, key, value) -> None: ...
    def lpop(self, key) -> Optional[str]: ...       # decodes bytes
    def llen(self, key) -> int: ...
    def lrem(self, key, count, value) -> None: ...
    # maintenance
    def expire(self, key) -> None: ...              # applies the configured ttl
    def clear_prefix(self) -> None: ...             # scan_iter(match=f"{prefix}*") + delete
```

The command surface is the union of what the three subsystems use today — nothing speculative.
Connections always use `socket_connect_timeout=5` (currently applied by the session and
attachment drivers but not the response stores). `decode_responses` is a parameter because the
session/attachment stores need raw bytes (`BinarySerde`) while the response stores use decoded
strings.

`drivers/valkey.py` imports `valkey` at module top, mirroring `core/session/valkey.py`; the
factories that select it keep their existing `try/except ImportError` guidance to install
`agentkernel[valkey]`.

### `DynamoDBDriver`

One driver parameterized by table and key schema, replacing the three copies:

```python
class DynamoDBDriver:
    def __init__(self, table_name: str, partition_key: str, sort_key: Optional[str] = None,
                 region: Optional[str] = None, ttl: int = 0): ...

    @property
    def table(self): ...                             # lazy boto3 resource + Table + .load(), with retry

    def put(self, item: dict) -> None: ...           # adds expiry_time = now + ttl when ttl > 0
    def get(self, pk_value, sk_value=None) -> Optional[dict]: ...   # returns the raw item dict
    def delete(self, pk_value, sk_value=None) -> None: ...
    def query_sort_keys(self, pk_value) -> list[str]: ...  # paginated; requires sort_key
    def clear_all(self) -> None: ...                 # paginated scan + batch delete (dev/test only)
```

Subsystem mapping:

| Consumer | `partition_key` | `sort_key` | Value handling (stays in the store) |
|---|---|---|---|
| `DynamoDBSessionStore` | `session_id` | `key` | wraps payloads in `boto3 Binary`, unwraps `.value` on read |
| `DynamoDBAttachmentStore` | `session_id` | `attachment_id` | JSON-encodes/decodes the `data` attribute; `_index` item |
| `DynamoDBResponseStore` | `request_id` | — | stores the message dict as the item; reads `item["body"]` |

`get()` returns the whole item so the driver stays agnostic of value attribute names; the stores
extract `value` / `data` / `body` themselves.

`put()` must not mutate the caller's dict when attaching `expiry_time` (copy first) —
`DynamoDBResponseStore.add_message` copies the message today (`message = dict(message)`) before
adding the TTL attribute, and callers may reuse the message object after the write.

### `CosmosDBDriver` and `FirestoreDriver`

These have a single consumer (session stores) today, but they move to `core/util/drivers/` so the
pattern is uniform and future consumers (e.g. attachment stores) get them for free. Their method
surfaces (`put`/`get`/`query_keys`/`delete_entity`/`scan_and_clear_all` for Cosmos;
`put`/`get`/`get_all_keys`/`delete_all` for Firestore) move as-is, including Cosmos's manual TTL
checks and Firestore's `expiry_time` TTL field. The only change is the constructor: explicit
parameters (`connection_string`/`table_name`/`ttl`; `collection_name`/`project_id`/`database_id`/`ttl`)
instead of reading `AKConfig.get().session.*`. Firestore keeps its function-level
`from google.cloud import firestore` import inside `_connect()`.

### Consumer changes

**Session stores** (`core/session/redis.py`, `valkey.py`, `dynamodb.py`, `cosmosdb.py`,
`firestore.py`): the local driver classes are deleted. Each store's `__init__` reads its
`AKConfig.get().session.<backend>` section (keeping the existing missing-config `ValueError`s,
e.g. the `session.valkey config block is required...` message from `valkey.py:25`; note the Redis
store has no such check today — a missing `session.redis` block raises `AttributeError` — and it
gains a matching `ValueError` for parity) and constructs
the shared driver with explicit parameters. `load`/`new`/`store`/`clear` bodies are unchanged for
Redis/Valkey (same method names); the DynamoDB store adapts to the generic item-dict interface
(`driver.put({...})`, `driver.get(sid, k)["value"]`, `driver.query_sort_keys(sid)`,
`driver.clear_all()`). `SessionStoreBuilder` (`core/builder.py:116`) is untouched — it imports the
store classes, not the drivers.

**Multimodal attachment stores** (`core/multimodal/storage/redis.py`, `dynamodb.py`):
`RedisAttachmentDriver` and `DynamoDBAttachmentDriver` are deleted. `RedisAttachmentStore` holds a
shared `RedisDriver(url, prefix, ttl)` and keeps its key schema in the store: attachment keys are
`driver.key(f"{session_id}:{attachment_id}")`, the index key is `driver.key(f"{session_id}:_index")`,
and JSON encoding plus the prune-oldest loop stay where they are. `DynamoDBAttachmentStore` holds a
shared `DynamoDBDriver(table_name, "session_id", "attachment_id", ttl=ttl)` and keeps the
`_index`-item bookkeeping. `AttachmentStorageManager._build_driver()`
(`storage_manager.py:32`) is unchanged apart from the import targets.

**Response stores** (`deployment/aws/core/response_store/redis.py`, `valkey.py`, `dynamodb.py`):
the classes and their public constructor signatures are kept (they subclass the `ResponseStore`
ABC and are selected by `ResponseDBHandler`), but the inline eager clients are replaced with shared
drivers: `RedisResponseStore`/`ValkeyResponseStore` build a driver with
`decode_responses=True` and use `driver.set/get/delete` (the driver's `set` applies the TTL, so the
separate `expire` call disappears); `DynamoDBResponseStore` builds
`DynamoDBDriver(table_name, "request_id", region=region, ttl=ttl)` and drops its hand-rolled
`expiry_time` logic. `ResponseDBHandler` (`handler.py`) is unchanged.

### Config consolidation

In `core/config.py`, the multimodal storage configs become subclasses of the base connection
configs, the same way the response-store configs already are:

- `_MultimodalStorageRedisConfig(_RedisConfig)` — overrides only
  `prefix: str = "ak:attachments:"`.
- `_MultimodalStorageDynamoDBConfig(_DynamoDBConfig)` — overrides only the `table_name` default
  (`"ak-attachments"`) and its description.

Field names, types, and defaults are preserved exactly (verified: `_RedisConfig.url` and
`_MultimodalStorageRedisConfig.url` share the `redis://localhost:6379` default, and both `ttl`s
default to `604800`), so YAML files and `AK_MULTIMODAL__*` environment variables are unaffected.
Field *descriptions* that are not overridden change to the inherited session-oriented wording
(e.g. the multimodal `ttl` description becomes "Redis saved value TTL in seconds" instead of
"Attachment TTL in seconds"); also override the `ttl` descriptions to keep the attachment-specific
wording, since these descriptions surface in generated config documentation.

### Behavioural changes

Intentional, all in the direction of unifying on the session-driver behaviour:

1. **Response stores gain lazy connect, retry, and health-check/reconnect.** Consequence: a bad
   URL/table no longer fails at construction time (inside `ResponseDBHandler.__init__`) but at the
   first operation, after 3 retries — matching how every other store in the codebase behaves.
   `DynamoDBResponseStore` additionally gains the `.load()` table-existence verification on first
   use.
2. **Session Redis `exists()` no longer swallows errors.** Today `core/session/redis.py:116`
   returns `False` on any `RedisError` (silently creating a fresh session on a flaky connection),
   while its Valkey twin propagates the error. The shared driver propagates, unifying on the
   Valkey behaviour: a connection failure during `load()` surfaces instead of silently discarding
   session history.
3. **Response-store Redis/Valkey TTL is applied atomically** via `SET ... EX` instead of
   `SET` + `EXPIRE` (removes a window where a key could persist without TTL).
4. **Session Redis gains a missing-config check.** A missing `session.redis` block currently
   raises `AttributeError` from the driver's config reads; the store now raises a `ValueError`
   with a `session.redis config block is required...` message, matching the Valkey store.

Non-changes: stored data layouts, key schemas, serialization, and TTL semantics are untouched —
data written before this refactor is read back identically after it. No public exports change:
the driver classes were internal (never exported from `agentkernel` or the subsystem
`__init__.py`s); the store classes keep their names, modules, and constructor signatures.

### Non-goals

- **Unifying the three factories** (`SessionStoreBuilder.build()`,
  `AttachmentStorageManager._build_driver()`, `ResponseDBHandler.__init__`) into a generic
  "type → import → instantiate" registry. Their type enums, fallback behaviour (session falls back
  to in-memory; the others raise), and error messages differ deliberately. Only their lazy-import
  targets change.
- **Adding new backend/subsystem combinations** (e.g. Valkey attachment storage, Cosmos DB response
  storage). The shared layer makes these near-trivial follow-ups, but none are added here.
- **Async drivers.** All current consumers are synchronous; the shared drivers stay synchronous.

## Error handling

- Connection failures: every driver retries 3 times with a 2-second delay and re-raises the last
  error — now uniformly, including the response stores.
- Redis/Valkey ping failure on an established client: warn + reconnect (existing session-driver
  behaviour, now everywhere).
- Missing/invalid config sections: validated in the stores (unchanged messages), never in the
  drivers. Drivers treat their constructor arguments as trusted.
- Missing optional dependencies: unchanged — the factories' `try/except ImportError` around the
  store imports also covers the driver modules, since each store module imports only its own
  backend's driver module.

## Implementation plan

### Task 1: Create the shared driver package (Redis/Valkey)

**Files:** `core/util/drivers/__init__.py`, `base.py`, `redis_like.py`, `redis.py`, `valkey.py` (all new)

1. Add `base.py` with the shared retry helper (`retries=3`, `delay=2`, re-raise last error) used by
   all drivers.
2. Implement `_RedisLikeDriver` in `redis_like.py` with the full command surface above, the lazy
   `client` property with ping/reconnect, `socket_connect_timeout=5`, and the `decode_responses`
   parameter. `redis_like.py` must not import `redis` or `valkey` itself.
3. Implement `RedisDriver` and `ValkeyDriver` as thin subclasses supplying `_from_url`,
   `_error_class`, and `_backend_name`.
4. Keep `drivers/__init__.py` free of eager driver imports. (Note: `core/util/` itself has no
   `__init__.py` today — it works as an implicit namespace package — and that stays as-is; only
   the new `drivers/` subpackage gets an `__init__.py`.)

### Task 2: Add DynamoDB, Cosmos DB, and Firestore drivers

**Files:** `core/util/drivers/dynamodb.py`, `cosmosdb.py`, `firestore.py` (all new)

1. Implement `DynamoDBDriver` with the parameterized key schema
   (`partition_key`/`sort_key`/`region`/`ttl`), lazy `table` with `.load()` verification, and the
   generic `put`/`get`/`delete`/`query_sort_keys`/`clear_all` surface (pagination preserved).
2. Move `CosmosDBDriver` and `FirestoreDriver` from `core/session/` with constructors converted to
   explicit parameters; method bodies (manual TTL handling, batch deletion) unchanged.

### Task 3: Migrate the session stores

**Files:** `core/session/redis.py`, `valkey.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`

1. Delete the five local driver classes; import the shared drivers.
2. Move config reading and missing-config validation into each store's `__init__`; construct
   drivers with explicit parameters.
3. Adapt `DynamoDBSessionStore` to the item-dict interface (Binary wrap/unwrap in the store).
4. Verify `SessionStoreBuilder` and `core/session/__init__.py` exports need no changes; update the
   stale `RedisDriver()` mention in the `build()` docstring (`core/builder.py:130`).

### Task 4: Migrate the multimodal attachment stores

**Files:** `core/multimodal/storage/redis.py`, `core/multimodal/storage/dynamodb.py`

1. Delete `RedisAttachmentDriver` and `DynamoDBAttachmentDriver`.
2. `RedisAttachmentStore`: hold a shared `RedisDriver`; keep key composition
   (`{session_id}:{attachment_id}`, `{session_id}:_index`), JSON encoding, and pruning in the store.
3. `DynamoDBAttachmentStore`: hold a shared `DynamoDBDriver`; keep `_index` bookkeeping in the
   store.
4. `AttachmentStorageManager._build_driver()` remains behaviourally identical.

### Task 5: Migrate the response stores

**Files:** `deployment/aws/core/response_store/redis.py`, `valkey.py`, `dynamodb.py`

1. Replace the eager inline clients with shared drivers (`decode_responses=True` for
   Redis/Valkey), keeping class names and constructor signatures.
2. Remove the hand-rolled `_key`, `expire`, and `expiry_time` logic in favour of the drivers'.
3. `ResponseDBHandler` is unchanged; confirm both selection paths still work.

### Task 6: Consolidate config classes

**File:** `core/config.py`

1. `_MultimodalStorageRedisConfig` extends `_RedisConfig`, overriding only the `prefix` default.
2. `_MultimodalStorageDynamoDBConfig` extends `_DynamoDBConfig`, overriding only the `table_name`
   default/description.
3. Assert the effective schema (field names, types, defaults) is unchanged.

### Task 7: Tests

**File:** `ak-py/tests/test_shared_drivers.py` (new)

1. Retry exhaustion re-raises the last error after 3 attempts (with `time.sleep` patched out) —
   for `_RedisLikeDriver` and `DynamoDBDriver`.
2. Ping failure on an established Redis/Valkey client triggers reconnect; healthy ping does not.
3. `set` applies `ex=ttl` only when `ttl > 0`; `expire` uses the configured TTL; `key()` applies
   the prefix; `clear_prefix` scans and deletes.
4. `DynamoDBDriver.put` attaches `expiry_time` only when `ttl > 0`; `get` returns the raw item;
   `query_sort_keys` follows `LastEvaluatedKey` pagination; sort-key-less mode works
   (`request_id`-style tables).

**Files:** existing tests

5. `test_sessions_redis.py`, `test_sessions_valkey.py`: update driver import paths
   (`agentkernel.core.util.drivers.*`) and monkeypatch targets (`from_url` now lives in the shared
   driver modules); behaviour assertions stay the same. Add a case asserting the new
   `session.redis config block is required...` `ValueError` (behavioural change 4).
6. `test_response_store_valkey.py`: update the `from_url` patch point; adjust for lazy connection
   (the client is created on first operation, not in `__init__`).
7. `test_firestore_database_id.py`: `FirestoreDriver` now takes constructor parameters — build it
   directly with `project_id`/`database_id` instead of mocking `AKConfig`, or mock `AKConfig` at
   the store level.
8. Run the full suite: `cd ak-py && uv run pytest`.

### Task 8: Sync docs and skills

1. Update `.agents/skills/ak-dev-architecture` (directory map: `core/util/drivers/`; the
   multimodal storage-backend table's "connection pooling" traits at `SKILL.md:152`) and
   `ak-dev-new-multimodal-storage` (its backend-traits table mentions "connection pooling";
   it does not reference the deleted attachment driver classes by name).
2. Update `.agents/skills/ak-dev-testing-conventions`: the test-file table (`SKILL.md:67`)
   references `FirestoreDriver` for `test_firestore_database_id.py` — reflect the driver's move to
   `core/util/drivers/` and its new constructor-parameter interface, and add the new
   `test_shared_drivers.py` to the table.
3. Docs website (`docs/docs/`): verified no page documents the per-subsystem driver classes,
   connection retry/reconnect behaviour, or the response stores' eager-connect timing, and the
   config field descriptions are unchanged (Task 6 overrides them) — no docs-site changes needed.
   Confirm with the `ak-dev-sync-docs-from-branch` flow before merge.
