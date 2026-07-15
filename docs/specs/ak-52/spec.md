# AK-52: Shared database drivers for Session, Multimodal, Response Store, and Thread backends

This change extracts the duplicated database connection drivers (Redis, Valkey, DynamoDB, Cosmos DB,
Firestore) out of the Session, Multimodal attachment, Response Store, and Thread subsystems into a
single shared package, `ak-py/src/agentkernel/core/util/driver/`. The stores keep their
subsystem-specific data layouts, key schemas, and factories; only the connection layer (client
creation, lazy connect, retry, health-check/reconnect, TTL plumbing) becomes shared.

## Motivation

The same connection logic is copy-pasted across four subsystems today:

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
4. **Thread stores** (`ak-py/src/agentkernel/core/thread/store/`, added by the conversational
   threads feature, #348) — `RedisThreadStore` (`redis.py:27`), `DynamoDBThreadStore`
   (`dynamodb.py:42`), `CosmosDBThreadStore` (`cosmosdb.py:44`), and `FirestoreThreadStore`
   (`firestore.py:33`) inline the connection logic directly in the store classes (no separate
   driver classes). Each has the same lazy client and 3-retry/2-second `_connect()` clone —
   including Cosmos's `__health_check__` probe verbatim — and each reads its own
   `AKConfig.get().thread.*` section in `__init__` with a missing-config `ValueError`. The Redis
   one has **no ping health-check/reconnect and no `socket_connect_timeout`**, and all four hold
   their client handles as class attributes.

Concrete duplication:

- `core/session/redis.py` and `core/session/valkey.py` are near-identical clones of each other
  (the `valkey` Python client is a fork of `redis-py` with an identical API). They differ only in
  the missing-config `ValueError` check (Valkey has one, Redis does not) and in `exists()` error
  handling (see Behavioural changes). The twin relationship between `response_store/redis.py` and
  `response_store/valkey.py` is exact.
- The `_connect()` retry loop (3 attempts, 2 s delay, re-raise last error) appears in eleven
  places.
- The lazy-client-plus-ping health check appears in three places (session Redis, session Valkey,
  multimodal Redis) and is *missing* from the three response stores and from the Redis thread
  store (which has lazy connect and retry but never pings an established client).
- The DynamoDB "boto3 resource → `Table(...)`" sequence appears in four places (with the
  `.load()` existence check in three of them — the response store skips it), and the
  `expiry_time = now + ttl` TTL-attribute logic in four places.
- Config classes for the same connection parameters are defined repeatedly: the response-store
  configs already subclass the session ones (`_ResponseStoreRedisConfig(_RedisConfig)` at
  `core/config.py:280`), but the multimodal configs (`_MultimodalStorageRedisConfig` at
  `core/config.py:178`, `_MultimodalStorageDynamoDBConfig` at `core/config.py:184`) and the
  thread configs (`_ThreadRedisConfig` at `core/config.py:215`, `_ThreadDynamoDBConfig` at
  `core/config.py:221`, `_ThreadFirestoreConfig` at `core/config.py:229`) redefine
  `url`/`ttl`/`prefix`/`table_name`/`collection_name` from scratch.

Any fix to connection handling (timeouts, retry policy, reconnect behaviour) currently has to be
made in up to eleven files, and in practice hasn't been — which is how the response stores ended
up without retry or reconnect at all, and how the brand-new Redis thread store shipped without
the ping/reconnect and connect timeout the session drivers already had.

## Design

### New package: `core/util/driver/`

```
ak-py/src/agentkernel/core/util/driver/
├── __init__.py        # no eager imports of optional client libraries
├── base.py            # shared retry helper, parameterized by exception scope
├── redis_like.py      # _RedisLikeDriver — all Redis/Valkey logic, client-library-agnostic
├── redis.py           # RedisDriver(_RedisLikeDriver)
├── valkey.py          # ValkeyDriver(_RedisLikeDriver)   (requires the `valkey` extra)
├── dynamodb.py        # DynamoDBDriver
├── cosmosdb.py        # CosmosDBDriver                   (requires the `azure` extra)
└── firestore.py       # FirestoreDriver                  (requires the `gcp` extra)
```

Three rules govern the package:

1. **Drivers never read `AKConfig`.** All connection parameters are explicit constructor arguments
   (the pattern the multimodal drivers already use). Config reading, config-section validation, and
   "which backend?" decisions stay in the stores and factories. This is what makes the drivers
   reusable from both `core/` and `deployment/` without coupling `core/util` to specific config
   sections.
2. **Drivers own the connection lifecycle and a generic command surface; data layout stays in the
   stores.** Key schemas (session hash layout, attachment index lists, response-message items,
   thread meta/message items), serialization (`BinarySerde`, JSON, Pydantic), and pruning logic
   remain in the store classes.
3. **Drivers expose their lazy, retry-guarded native handle for consumers whose data operations
   exceed the generic surface.** `_RedisLikeDriver.client`, `DynamoDBDriver.table`,
   `CosmosDBDriver.table_client`, and `FirestoreDriver.collection` are public parts of the driver
   contract, not implementation details. The thread stores are the consumer that needs this: their
   DynamoDB/Cosmos/Firestore data operations (conditional puts, update expressions,
   `begins_with` range queries, filtered scans, subcollections) are data-layout-specific and would
   bloat the generic surface, so those stores use the native handle directly and share only the
   connection lifecycle (lazy connect, retry, `.load()`/health-check probe). The Redis thread
   store's commands, by contrast, are generic Redis commands, so they extend the shared command
   surface instead (see `_RedisLikeDriver`).

`driver/__init__.py` must not import the driver modules eagerly: `redis`, `valkey`,
`azure-data-tables`, and `google-cloud-firestore` are all optional dependencies (via the `redis`,
`valkey`, `azure`, and `gcp` extras respectively), and the existing factories import backend
modules lazily (the Valkey selection paths in `SessionStoreBuilder.build()` and
`ResponseDBHandler.__init__` additionally wrap the import in `try/except ImportError`; the other
paths let a missing extra surface as a raw `ImportError`). Consumers import the concrete module
(`from agentkernel.core.util.driver.redis import RedisDriver`) exactly as they import store
modules today.

All drivers get the uniform connection behaviour that the session drivers have today: lazy connect
on first use, 3 connection attempts with a 2-second delay, re-raise of the last error, and (for
Redis/Valkey) a ping health-check with automatic reconnect on every `client` access.

All driver state (client handle, connection lock, parameters) is instance state initialized in
`__init__`. The current drivers hold their client handles as *class* attributes
(`RedisAttachmentDriver._redis_client` at `storage/redis.py:23`, `DynamoDBDriver._ddb_resource` /
`_ddb_table` at `core/session/dynamodb.py:21`, and likewise Cosmos/Firestore) and only work because
`_connect()` shadows them with instance attributes; that pattern must not be carried over — it is
incompatible with the per-instance `threading.Lock` anyway.

The retry helper in `base.py` takes the exception type(s) to retry on as a parameter, preserving
each family's current scope: `_RedisLikeDriver` passes its `_error_class`
(`redis.RedisError`/`valkey.ValkeyError`), so non-connection errors — e.g. a malformed-URL
`ValueError` from `from_url` — fail fast instead of burning 3 × 2 s of retries; the
DynamoDB/Cosmos/Firestore drivers pass `Exception`, keeping their current broad scope (boto3,
azure, and gcp clients raise varied exception hierarchies, and narrowing them is out of scope).
See Behavioural changes 5 for the two consumers this changes.

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
    def client(self): ...        # lazy connect; else ping, reconnect on _error_class;
                                 # a ping failure outside _error_class propagates to the caller
                                 # (see Behavioural changes 7)
                                 # _connect() is guarded by a threading.Lock; the lock holder
                                 # re-verifies before connecting — first use: _client is still
                                 # None; reconnect: _client is still the exact object whose ping
                                 # failed (identity compare; skip if another thread already
                                 # replaced it) — so concurrent first use or concurrent failed
                                 # pings produce exactly one connect and cannot leak a client
    @property
    def ttl(self) -> int: ...
    def key(self, suffix: str) -> str: ...          # f"{prefix}{suffix}"

    # string ops
    def set(self, key, value, nx: bool = False) -> bool: ...  # applies ex=ttl when ttl > 0;
                                                    # nx=True is a conditional SET NX (used by
                                                    # thread create); returns whether the SET
                                                    # was applied
    def get(self, key) -> Any: ...
    def delete(self, *keys) -> None: ...
    def exists(self, key) -> bool: ...
    # hash ops (used by session stores)
    def hset(self, key, field, value) -> None: ...
    def hget(self, key, field) -> Optional[bytes]: ...
    def hkeys(self, key) -> list[str]: ...          # decodes bytes field names
    # list ops (used by the attachment index and thread messages)
    def rpush(self, key, value) -> None: ...
    def lpop(self, key) -> Optional[str]: ...       # decodes bytes
    def llen(self, key) -> int: ...
    def lrem(self, key, count, value) -> None: ...
    def lrange(self, key, start, end) -> list: ...  # raw elements (thread store JSON-decodes)
    # set ops (used by the thread user/group indexes)
    def sadd(self, key, member) -> None: ...
    def smembers(self, key) -> set[str]: ...        # decodes bytes members
    # key iteration (used by thread list_threads)
    def scan_keys(self, match_suffix: str) -> list[str]: ...  # scan_iter(match=f"{prefix}{match_suffix}"),
                                                    # decodes bytes key names
    # maintenance
    def expire(self, key) -> None: ...              # applies the configured ttl; no-op when
                                                    # ttl <= 0 (a raw EXPIRE key 0 would delete
                                                    # the key)
    def clear_prefix(self) -> None: ...             # scan_iter(match=f"{prefix}*") + delete
```

The command surface is the union of what the four subsystems use today — nothing speculative.
Connections always use `socket_connect_timeout=5` (currently applied by the session and
attachment drivers but not the response stores or the thread store). `decode_responses` is a
parameter because the session/attachment/thread stores need raw bytes (`BinarySerde`,
`model_validate_json` over bytes) while the response stores use decoded strings.

`driver/valkey.py` imports `valkey` at module top, mirroring `core/session/valkey.py`; the
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
| `DynamoDBThreadStore` | `session_id` | `sk` | uses `driver.table` natively (rule 3): conditional puts, update expressions, `begins_with` queries, filtered scans; TTL attribute logic stays in the store (constructs the driver with `ttl=0`) |

`get()` returns the whole item so the driver stays agnostic of value attribute names; the stores
extract `value` / `data` / `body` themselves. The thread store shares only the connection layer —
its generic-surface usage is nil, but it gains the lazy retry-guarded `table` (and keeps its
existing `.load()` verification).

`put()` must not mutate the caller's dict when attaching `expiry_time` (copy first) —
`DynamoDBResponseStore.add_message` copies the message today (`message = dict(message)`) before
adding the TTL attribute, and callers may reuse the message object after the write.

### `CosmosDBDriver` and `FirestoreDriver`

These now have two consumers each: the session stores (generic surface) and the thread stores
(native handle per rule 3 — `CosmosDBThreadStore._connect` is a verbatim clone of the session
driver's, including the `__health_check__` probe, and `FirestoreThreadStore` needs subcollection
access the per-field session surface can't express). Method bodies
(Cosmos's manual TTL checks, Firestore's `expiry_time` TTL field, batch deletion) move unchanged,
but Cosmos adopts the same method names as `DynamoDBDriver` so the shared package has one name per
operation: `query_keys` → `query_sort_keys`, `delete_entity` → `delete`, `scan_and_clear_all` →
`clear_all` (the renamed methods' single consumer, `CosmosDBSessionStore`, is already being
edited in Task 3; the thread store uses `table_client` directly and is unaffected by the renames).
Firestore's surface (`put`/`get`/`get_all_keys`/`delete_all`) moves as-is — it has no
partition/sort-key model, so the DynamoDB/Cosmos names don't map onto it. The other change is the
constructor: explicit parameters (`connection_string`/`table_name`/`ttl`;
`collection_name`/`project_id`/`database_id`/`ttl`) instead of reading `AKConfig.get().session.*`.
Firestore keeps its function-level `from google.cloud import firestore` import inside `_connect()`.

### Consumer changes

**Session stores** (`core/session/redis.py`, `valkey.py`, `dynamodb.py`, `cosmosdb.py`,
`firestore.py`): the local driver classes are deleted. Each store's `__init__` reads its
`AKConfig.get().session.<backend>` section (keeping the existing missing-config `ValueError`s,
e.g. the `session.valkey config block is required...` message from `valkey.py:25`; note the Redis
store has no such check today — a missing `session.redis` block raises `AttributeError` — and it
gains a matching `ValueError` for parity) and constructs
the shared driver with explicit parameters. `load`/`new`/`store`/`clear` bodies are unchanged for
Redis/Valkey (same method names); the DynamoDB store adapts to the generic item-dict interface
(`driver.put({...})`, `driver.get(sid, k)` — which returns `None` for a missing item, so the store
keeps its existing `payload is None: continue` guard before extracting `["value"]` —
`driver.query_sort_keys(sid)`, `driver.clear_all()`). `SessionStoreBuilder`
(`core/builder.py:116`) is untouched — it imports the
store classes, not the drivers.

**Multimodal attachment stores** (`core/multimodal/storage/redis.py`, `dynamodb.py`):
`RedisAttachmentDriver` and `DynamoDBAttachmentDriver` are deleted. `RedisAttachmentStore` holds a
shared `RedisDriver(url, prefix, ttl)` and keeps its key schema in the store: attachment keys are
`driver.key(f"{session_id}:{attachment_id}")`, the index key is `driver.key(f"{session_id}:_index")`,
and JSON encoding plus the prune-oldest loop stay where they are. The index-key TTL refresh moves
into the store too: today `append_index` re-applies the TTL to the `_index` list key after every
`rpush` (`storage/redis.py:104`), and since `append_index` is deleted, the store must call
`driver.expire(index_key)` after `driver.rpush(...)` (the driver's `expire` already no-ops the
right way when `ttl == 0` — see the command surface) — otherwise `_index` keys would be written
without a TTL and outlive their attachments indefinitely. `DynamoDBAttachmentStore` holds a
shared `DynamoDBDriver(table_name, "session_id", "attachment_id", ttl=ttl)` and keeps the
`_index`-item bookkeeping. `AttachmentStorageManager._build_driver()`
(`storage_manager.py:32`) is unchanged — it imports the store classes, which keep their names and
modules.

**Response stores** (`deployment/aws/core/response_store/redis.py`, `valkey.py`, `dynamodb.py`):
the classes and their public constructor signatures are kept (they subclass the `ResponseStore`
ABC and are selected by `ResponseDBHandler`), but the inline eager clients are replaced with shared
drivers: `RedisResponseStore`/`ValkeyResponseStore` build a driver with
`decode_responses=True` and use `driver.set/get/delete` (the driver's `set` applies the TTL, so the
separate `expire` call disappears); `DynamoDBResponseStore` builds
`DynamoDBDriver(table_name, "request_id", region=region, ttl=ttl)` and drops its hand-rolled
`expiry_time` logic. `ResponseDBHandler` (`handler.py`) is unchanged.

**Thread stores** (`core/thread/store/redis.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`):
the inline `_connect()` clones, class-attribute client handles, and `client`/`table`/
`table_client`/`collection` properties are deleted; each store's `__init__` keeps its existing
config reading and missing-config `ValueError`s and constructs a shared driver with explicit
parameters.

- `RedisThreadStore` holds a `RedisDriver(url, prefix, ttl)` and uses the generic surface
  (`set` with `nx=True` for atomic thread creation, `get`, `rpush`, `lrange`, `llen`, `sadd`,
  `smembers`, `expire`, `scan_keys`, `clear_prefix`). Its key schema (`:meta`, `:updated_at`,
  `:messages`, `index:user:`, `index:group:`) and the multi-key `_expire` TTL-refresh logic stay
  in the store. The driver's `set` applying `ex=ttl` atomically is redundant-but-harmless with the
  store's explicit `_expire` refreshes — the refresh loop must stay, because the shared user/group
  index sets need their TTL renewed on every append.
- `DynamoDBThreadStore` holds a `DynamoDBDriver(table_name, "session_id", "sk")` and replaces its
  `table` property with `driver.table`; every data operation and the `expiry_time` logic stay
  in the store (rule 3).
- `CosmosDBThreadStore` holds a `CosmosDBDriver(connection_string, table_name)` and replaces its
  `table_client` property with `driver.table_client`; entities, OData filters, and pagination
  stay in the store.
- `FirestoreThreadStore` holds a `FirestoreDriver(collection_name, project_id, database_id)` and
  replaces its `collection` property with `driver.collection`; the `messages` subcollection
  layout and `expiry_time` fields stay in the store.

`ThreadStoreBuilder.build()` (`core/thread/store/base.py:160`) is untouched — it imports the store
classes, not the drivers.

### Config consolidation

In `core/config.py`, the multimodal storage and thread configs become subclasses of the base
connection configs, the same way the response-store configs already are:

- `_MultimodalStorageRedisConfig(_RedisConfig)` — overrides only
  `prefix: str = "ak:attachments:"`.
- `_MultimodalStorageDynamoDBConfig(_DynamoDBConfig)` — overrides only the `table_name` default
  (`"ak-attachments"`) and its description.
- `_ThreadRedisConfig(_RedisConfig)` — overrides `prefix` (`"ak:thread:"`) and `ttl`
  (`2592000`, with its thread-oriented description).
- `_ThreadDynamoDBConfig(_DynamoDBConfig)` — overrides the `table_name` default
  (`"ak-agent-threads"`) and `ttl` (`0`), with their descriptions.
- `_ThreadFirestoreConfig(_FirestoreConfig)` — overrides the `collection_name` default
  (`"ak-agent-threads"`) and `ttl` (`0`), with their descriptions.
- `_ThreadCosmosDBConfig` stays independent: it has no `ttl` field (the Cosmos thread store does
  no TTL management), so subclassing `_CosmosDBConfig` would *add* an unused inherited `ttl`
  field to the schema — a silently-accepted config knob that does nothing. Its `table_name`
  default also differs (`"akagentthreads"`); duplicating two fields is cheaper than the false
  affordance.

Field names, types, and defaults are preserved exactly (verified: `_RedisConfig.url` and
`_MultimodalStorageRedisConfig.url` share the `redis://localhost:6379` default, and both `ttl`s
default to `604800`; the thread overrides above preserve every current thread default), so YAML
files and `AK_MULTIMODAL__*` / `AK_THREAD__*` environment variables are unaffected.
Field *descriptions* that are not overridden change to the inherited session-oriented wording:
the multimodal `ttl` description would become "Redis saved value TTL in seconds" instead of
"Attachment TTL in seconds" — override the `ttl` descriptions to keep the attachment-specific
wording, since these descriptions surface in generated config documentation. The multimodal `url`
description also changes, from "Redis connection URL" to the inherited "Redis connection URL. Use
rediss:// for SSL" — keep that one inherited; the SSL hint is an improvement, not a loss.

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
5. **Multimodal and thread Redis retry scope narrows from `Exception` to `redis.RedisError`.**
   The retry helper takes its exception scope as a parameter (see Design); the session
   Redis/Valkey drivers already retry only on `RedisError`/`ValkeyError`, and the shared
   `_RedisLikeDriver` unifies on that. The consumers whose scope changes are
   `RedisAttachmentStore` and `RedisThreadStore`: non-connection errors (e.g. a malformed URL)
   now fail fast instead of being retried. The DynamoDB/Cosmos/Firestore drivers keep their
   current bare-`Exception` scope.
6. **Response-store operations gain one health-check round trip and become safe under concurrent
   use.** Every `client` access pings (a sub-millisecond `PING` on an established connection),
   including the polling read path (`execution.response_store.retry_count`, default 5 reads per
   request) — accepted in exchange for reconnect-on-failure, which the response stores currently
   lack entirely. Since response stores are shared across `ECSOutputConsumer` consumer threads
   (`no_of_consumers`, default 2) and the REST `GET /chat/{id}` path, `_connect()` is guarded by
   a `threading.Lock`, and the lock holder re-verifies before connecting (first use: `_client` is
   still `None`; reconnect: `_client` is still the identical object whose ping failed — if another
   thread already replaced it, skip), so concurrent first use or concurrent failed pings produce
   exactly one connect and cannot leak a client — an exposure the session drivers (one per event
   loop) never had.
7. **A ping failure outside `_error_class` propagates.** The two families disagree today: the
   session Redis/Valkey drivers catch a non-`RedisError`/`ValkeyError` ping exception, log it, and
   return the possibly-stale client anyway (`core/session/redis.py:40`) — a latent bug, since the
   caller then issues commands on a client whose health check just failed — while the multimodal
   Redis driver reconnects on *any* `Exception` (`storage/redis.py:46`). The shared driver
   reconnects only on `_error_class` and lets anything else raise: an unexpected error during a
   health check is a programming or environment fault the caller should see, not something to
   paper over with a stale client or an unnecessary reconnect. This changes both families (session:
   swallow → raise; multimodal: reconnect → raise); in practice a healthy client's `ping()` raises
   only `_error_class` subtypes, so the path is unreachable outside genuine faults.
8. **The Redis thread store gains the health-check/reconnect, `socket_connect_timeout=5`, and
   atomic `SET ... EX`.** Today `RedisThreadStore` never pings an established client (a dropped
   connection surfaces as a raw command error with no reconnect), passes no connect timeout, and
   sets TTLs via separate `EXPIRE` calls. It picks up the shared driver's ping-and-reconnect on
   every `client` access and the connect timeout; its plain `set` calls now also apply `ex=ttl`
   atomically, which is redundant with (but not a replacement for) the store's multi-key
   `_expire` refresh of the shared user/group index sets. The DynamoDB/Cosmos/Firestore thread
   stores are behaviourally unchanged — they already had lazy connect and retry, and keep their
   data operations verbatim via the native handle.

Non-changes: stored data layouts, key schemas, serialization, and TTL semantics are untouched —
data written before this refactor is read back identically after it. No public exports change:
the driver classes were internal (never exported from `agentkernel` or the subsystem
`__init__.py`s); the store classes keep their names, modules, and constructor signatures.

### Non-goals

- **Unifying the four factories** (`SessionStoreBuilder.build()`,
  `AttachmentStorageManager._build_driver()`, `ResponseDBHandler.__init__`,
  `ThreadStoreBuilder.build()`) into a generic "type → import → instantiate" registry. Their type
  enums, fallback behaviour (session and thread fall back to in-memory; the others raise), and
  error messages differ deliberately. All four lazily import store classes, whose names and
  modules are unchanged, so the factories are untouched.
- **Adding new backend/subsystem combinations** (e.g. Valkey attachment storage, Cosmos DB response
  storage, Valkey thread storage). The shared layer makes these near-trivial follow-ups, but none
  are added here.
- **Async drivers.** All current consumers are synchronous; the shared drivers stay synchronous.

## Error handling

- Connection failures: every driver retries 3 times with a 2-second delay and re-raises the last
  error — now uniformly, including the response stores. Retries cover only the driver's configured
  exception scope (`_error_class` for Redis/Valkey, `Exception` for DynamoDB/Cosmos/Firestore);
  anything outside it propagates immediately.
- Redis/Valkey ping failure on an established client: warn + reconnect when the failure is an
  `_error_class` instance (existing session-driver behaviour, now everywhere); any other exception
  propagates to the caller (Behavioural changes 7). Connect/reconnect is serialized by a `threading.Lock`; the lock
  holder skips the reconnect if `_client` is no longer the object whose ping failed (another
  thread already replaced it), so concurrent failed pings produce exactly one reconnect.
- Missing/invalid config sections: validated in the stores (unchanged messages), never in the
  drivers. Drivers treat their constructor arguments as trusted.
- Missing optional dependencies: unchanged — the factories keep their lazy store imports (with
  `try/except ImportError` guidance on the Valkey paths only), and since each store module imports
  only its own backend's driver module, a missing extra surfaces exactly as it does today.

## Implementation plan

### Task 1: Create the shared driver package (Redis/Valkey)

**Files:** `core/util/driver/__init__.py`, `base.py`, `redis_like.py`, `redis.py`, `valkey.py` (all new)

1. Add `base.py` with the shared retry helper (`retries=3`, `delay=2`, re-raise last error) used by
   all drivers. It takes the exception type(s) to retry on as a parameter; exceptions outside that
   scope propagate immediately without retries.
2. Implement `_RedisLikeDriver` in `redis_like.py` with the full command surface above, the lazy
   `client` property with ping/reconnect (retrying on `_error_class`, with `_connect()` guarded by
   a `threading.Lock` whose holder re-verifies before connecting: `_client` is still `None` on
   first use, or on reconnect still the identical object whose ping failed — skip if another
   thread already replaced it), `socket_connect_timeout=5`, and the `decode_responses`
   parameter. `redis_like.py` must not import `redis` or `valkey` itself.
3. Implement `RedisDriver` and `ValkeyDriver` as thin subclasses supplying `_from_url`,
   `_error_class`, and `_backend_name`.
4. Keep `driver/__init__.py` free of eager driver imports. (Note: `core/util/` itself has no
   `__init__.py` today — it works as an implicit namespace package — and that stays as-is; only
   the new `driver/` subpackage gets an `__init__.py`.)

### Task 2: Add DynamoDB, Cosmos DB, and Firestore drivers

**Files:** `core/util/driver/dynamodb.py`, `cosmosdb.py`, `firestore.py` (all new)

1. Implement `DynamoDBDriver` with the parameterized key schema
   (`partition_key`/`sort_key`/`region`/`ttl`), lazy `table` with `.load()` verification, and the
   generic `put`/`get`/`delete`/`query_sort_keys`/`clear_all` surface (pagination preserved).
2. Move `CosmosDBDriver` and `FirestoreDriver` from `core/session/` with constructors converted to
   explicit parameters; method bodies (manual TTL handling, batch deletion) unchanged. Rename the
   Cosmos methods to the shared names (`query_sort_keys`, `delete`, `clear_all`); Firestore's
   surface moves as-is. Do **not** carry over the class-attribute client state
   (`_table_service_client`/`_table_client`, `_client`, `_ddb_resource`/`_ddb_table`) — all state
   becomes instance attributes initialized in `__init__` (see Design).

### Task 3: Migrate the session stores

**Files:** `core/session/redis.py`, `valkey.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`

1. Delete the five local driver classes; import the shared drivers.
2. Move config reading and missing-config validation into each store's `__init__`; construct
   drivers with explicit parameters.
3. Adapt `DynamoDBSessionStore` to the item-dict interface (Binary wrap/unwrap in the store;
   keep the existing missing-item `None` guard in `load()`). Adapt `CosmosDBSessionStore` to the
   renamed driver methods (`query_sort_keys`, `delete`, `clear_all`).
4. Verify `SessionStoreBuilder` and `core/session/__init__.py` exports need no changes; update the
   stale `RedisDriver()` mention in the `build()` docstring (`core/builder.py:130`).

### Task 4: Migrate the multimodal attachment stores

**Files:** `core/multimodal/storage/redis.py`, `core/multimodal/storage/dynamodb.py`

1. Delete `RedisAttachmentDriver` and `DynamoDBAttachmentDriver`.
2. `RedisAttachmentStore`: hold a shared `RedisDriver`; keep key composition
   (`{session_id}:{attachment_id}`, `{session_id}:_index`), JSON encoding, and pruning in the
   store. After each `driver.rpush(index_key, ...)`, call `driver.expire(index_key)` to preserve
   the index-key TTL refresh that `append_index` performs today (see Consumer changes).
3. `DynamoDBAttachmentStore`: hold a shared `DynamoDBDriver`; keep `_index` bookkeeping in the
   store.
4. `AttachmentStorageManager._build_driver()` remains behaviourally identical.

### Task 5: Migrate the response stores

**Files:** `deployment/aws/core/response_store/redis.py`, `valkey.py`, `dynamodb.py`

1. Replace the eager inline clients with shared drivers (`decode_responses=True` for
   Redis/Valkey), keeping class names and constructor signatures.
2. Remove the hand-rolled `_key`, `expire`, and `expiry_time` logic in favour of the drivers'.
3. `ResponseDBHandler` is unchanged; confirm both selection paths still work.

### Task 6: Migrate the thread stores

**Files:** `core/thread/store/redis.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`

1. Delete the four inline `_connect()` methods, the class-attribute client handles, and the
   `client`/`table`/`table_client`/`collection` properties; keep config reading and the
   missing-config `ValueError`s in each store's `__init__`.
2. `RedisThreadStore`: hold a shared `RedisDriver(url, prefix, ttl)`; replace raw client calls
   with the generic surface (`set(..., nx=True)` for `create`, `get`, `rpush`, `lrange`, `llen`,
   `sadd`, `smembers`, `expire`, `scan_keys` for `list_threads`, `clear_prefix` for `clear`).
   Key composition and the multi-key `_expire` refresh (user/group index sets) stay in the store.
3. `DynamoDBThreadStore` / `CosmosDBThreadStore` / `FirestoreThreadStore`: hold shared drivers
   constructed with explicit parameters and access `driver.table` / `driver.table_client` /
   `driver.collection` (rule 3); all data operations, TTL attribute logic, and pagination move
   nowhere.
4. `ThreadStoreBuilder.build()` and `core/thread/store/__init__.py` exports need no changes;
   verify.

### Task 7: Consolidate config classes

**File:** `core/config.py`

1. `_MultimodalStorageRedisConfig` extends `_RedisConfig`, overriding only the `prefix` default.
2. `_MultimodalStorageDynamoDBConfig` extends `_DynamoDBConfig`, overriding only the `table_name`
   default/description.
3. `_ThreadRedisConfig` extends `_RedisConfig` (overrides `prefix`, `ttl`);
   `_ThreadDynamoDBConfig` extends `_DynamoDBConfig` (overrides `table_name`, `ttl`);
   `_ThreadFirestoreConfig` extends `_FirestoreConfig` (overrides `collection_name`, `ttl`).
   `_ThreadCosmosDBConfig` stays independent (no `ttl` field — see Config consolidation).
4. Assert the effective schema (field names, types, defaults) is unchanged.

### Task 8: Tests

**File:** `ak-py/tests/test_shared_drivers.py` (new)

1. Retry exhaustion re-raises the last error after 3 attempts (with `time.sleep` patched out) —
   for `_RedisLikeDriver` and `DynamoDBDriver`. An exception outside the configured retry scope
   (e.g. a `ValueError` from `from_url` in a `_RedisLikeDriver`) raises immediately with no
   retries.
2. Ping failure on an established Redis/Valkey client triggers reconnect; healthy ping does not.
   A ping failure outside `_error_class` (e.g. a `TypeError`) propagates to the caller without
   reconnecting (behavioural change 7). Concurrent failed pings on the same client produce exactly
   one reconnect: the second lock holder sees `_client` already replaced (identity compare against
   the object whose ping failed) and skips connecting.
3. `set` applies `ex=ttl` only when `ttl > 0`, and with `nx=True` returns whether the SET was
   applied; `expire` uses the configured TTL and is a no-op when `ttl <= 0` (never issues
   `EXPIRE key 0`, which would delete the key); `key()` applies the prefix; `clear_prefix` scans
   and deletes; `smembers` and `scan_keys` decode bytes.
4. `DynamoDBDriver.put` attaches `expiry_time` only when `ttl > 0`; `get` returns the raw item;
   `query_sort_keys` follows `LastEvaluatedKey` pagination; sort-key-less mode works
   (`request_id`-style tables).

**File:** `ak-py/tests/test_sessions_dynamodb.py` (new)

5. `DynamoDBSessionStore` is the consumer whose store body changes the most (item-dict interface,
   Binary wrap/unwrap moving into the store) and has no existing test file. Add store-level tests
   with a mocked driver: a round trip asserting payloads are wrapped in `boto3 Binary` on `store()`
   and unwrapped via `.value` on `load()`, and a missing-item case asserting `load()` skips keys
   for which `driver.get()` returns `None` (the `payload is None: continue` guard) instead of
   raising.

**File:** `ak-py/tests/test_multimodal_redis_store.py` (new)

6. `RedisAttachmentStore` with a mocked driver: `save()` calls `driver.expire(index_key)` after
   `driver.rpush(index_key, ...)` — the index-key TTL refresh that moves from the deleted
   `append_index` into the store (Task 4.2) and has no other test coverage.

**Files:** existing tests

7. `test_sessions_redis.py`, `test_sessions_valkey.py`: update driver import paths
   (`agentkernel.core.util.driver.*`) and monkeypatch targets (`from_url` now lives in the shared
   driver modules); behaviour assertions stay the same. Add a case asserting the new
   `session.redis config block is required...` `ValueError` (behavioural change 4).
8. `test_response_store_valkey.py`: update the `from_url` patch point; adjust for lazy connection
   (the client is created on first operation, not in `__init__`). With TTL now applied atomically
   via `SET ... EX` (behavioural change 3), `FakeValkeyClient.set` must accept the `ex=` keyword
   and the `expirations`-dict assertions must be reworked to check the `ex` value passed to `set`,
   since `expire()` is no longer called.
9. `test_firestore_database_id.py`: `FirestoreDriver` now takes constructor parameters — build it
   directly with `project_id`/`database_id` instead of mocking `AKConfig`, or mock `AKConfig` at
   the store level.
10. `test_thread_store_redis.py`: the fixture injects the mocked client via the class attribute
   (`store._redis_client = MagicMock()`, reset with `RedisThreadStore._redis_client = None`) —
   both disappear with the migration; inject a mocked `RedisDriver` on the store instead, and
   rework the `store.client.expire` call assertions to `driver.expire`. Note the driver's `set`
   now applies `ex=ttl` itself, so TTL assertions must accept `ex` on `set` in addition to the
   explicit `_expire` refreshes.
11. `test_thread_store.py`: the DynamoDB cases inject `store._ddb_table = MagicMock()` and reset
   the `DynamoDBThreadStore._ddb_table` class attribute — inject the mock on the store's driver
   (`store._driver`) instead; the data-operation assertions are unchanged since the store keeps
   its native `table` calls.
12. Run the full suite: `cd ak-py && uv run pytest`.

### Task 9: Sync docs and skills

1. Update `.agents/skills/ak-dev-architecture` (directory map: `core/util/driver/`; the
   multimodal storage-backend table's "connection pooling" traits at `SKILL.md:152`; any thread
   store coverage the #348 skill sync adds in the meantime) and `ak-dev-new-multimodal-storage`
   (its backend-traits table mentions "connection pooling"; it does not reference the deleted
   attachment driver classes by name).
2. Update `.agents/skills/ak-dev-testing-conventions`: the test-file table (`SKILL.md:67`)
   references `FirestoreDriver` for `test_firestore_database_id.py` — reflect the driver's move to
   `core/util/driver/` and its new constructor-parameter interface, and add the new test files
   (`test_shared_drivers.py`, `test_sessions_dynamodb.py`, `test_multimodal_redis_store.py`) to
   the table.
3. Docs website (`docs/docs/`): verified no page documents the per-subsystem driver classes,
   connection retry/reconnect behaviour, or the response stores' eager-connect timing;
   `docs/docs/advanced/threads.md` mentions connection parameters only in its config sample (no
   connection-behaviour claims); and the config field descriptions are unchanged (Task 7
   overrides them) — no docs-site changes needed. Confirm with the `ak-dev-sync-docs-from-branch`
   flow before merge.
