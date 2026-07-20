# AK-52 Implementation Plan: Shared database drivers

Implementation plan for [spec.md](spec.md) — extracting the duplicated Redis/Valkey/DynamoDB/
Cosmos DB/Firestore connection drivers out of the Session, Multimodal, Response Store, and Thread
subsystems into one shared package, `ak-py/src/agentkernel/core/util/driver/`.

## Execution order

```
Task 1 (Redis/Valkey drivers) ──┐
Task 2 (DDB/Cosmos/Firestore)  ─┤
                                ├─→ Task 3 (sessions)   ─┐
                                ├─→ Task 4 (multimodal)  ├─→ Task 8 (tests) ─→ Task 9 (docs/skills)
                                ├─→ Task 5 (response)    │
                                └─→ Task 6 (threads)    ─┘
Task 7 (config consolidation) — independent, any time before Task 8
```

Tasks 3–6 are independent of each other once Tasks 1–2 land; Task 7 touches only
`core/config.py`. Run the full suite (`cd ak-py && uv run pytest`) after each consumer task, not
just at the end — each task leaves the tree green on its own.

## Task 1: Shared driver package — Redis/Valkey

**New files:** `core/util/driver/__init__.py`, `base.py`, `redis_like.py`, `redis.py`, `valkey.py`

Note: `core/util/` has no `__init__.py` today (implicit namespace package) — leave that as-is;
only the new `driver/` subpackage gets an `__init__.py`, and it must contain **no eager imports**
of driver modules (all client libraries are optional extras).

### 1.1 `base.py` — retry helper

One module-level function used by every driver:

```python
def connect_with_retries(connect, retry_on, log, retries=3, delay=2.0):
    """Call `connect()` up to `retries` times, sleeping `delay` between attempts.
    Only exceptions matching `retry_on` (type or tuple) are retried; anything
    else propagates immediately. Re-raises the last error on exhaustion."""
```

- Retry scope is a parameter: `_RedisLikeDriver` passes its `_error_class`
  (`redis.RedisError` / `valkey.ValkeyError`); DynamoDB/Cosmos/Firestore pass `Exception`
  (their current broad scope — behavioural change 5 applies only to the Redis consumers).
- A non-matching exception (e.g. `ValueError` from a malformed URL in `from_url`) raises
  immediately, with zero sleeps.

### 1.2 `redis_like.py` — `_RedisLikeDriver`

All Redis/Valkey logic once; **must not import `redis` or `valkey`** itself. Subclass contract:
`_backend_name: str` (log messages), `_error_class: type[Exception]`, `_from_url(url, **kwargs)`.

Constructor and state — all instance state, initialized in `__init__` (no class attributes):

```python
def __init__(self, url: str, prefix: str = "", ttl: int = 0, decode_responses: bool = False):
    self._url, self._prefix, self._ttl = url, prefix, int(ttl)
    self._decode_responses = decode_responses
    self._client = None
    self._lock = threading.Lock()
    self._log = logging.getLogger(f"ak.core.util.driver.{self._backend_name.lower()}")
```

`client` property — the one subtle piece (spec Design + behavioural changes 6/7):

```python
@property
def client(self):
    c = self._client
    if c is None:
        self._ensure_connected(expected=None)          # first use
    else:
        try:
            c.ping()
        except self._error_class:
            self._log.warning("%s client is not alive, reconnecting", self._backend_name)
            self._ensure_connected(expected=c)         # reconnect
        # any other ping exception propagates to the caller (behavioural change 7)
    return self._client

def _ensure_connected(self, expected):
    with self._lock:
        if self._client is not expected:
            return          # another thread already connected/replaced it — skip
        self._connect()     # connect_with_retries(...) around _from_url + ping
```

- The identity compare (`is not expected`) is what makes concurrent first use
  (`expected=None`) and concurrent failed pings (`expected=<stale client>`) produce exactly one
  connect and never leak a client.
- `_connect()` calls `self._from_url(self._url, decode_responses=self._decode_responses,
  socket_connect_timeout=5)` then `ping()`, wrapped in `connect_with_retries(...,
  retry_on=self._error_class, ...)`, and assigns `self._client` only on success.

Command surface — exactly the union the four subsystems use today, nothing speculative
(signatures per the spec's sketch):

| Group | Methods | Notes |
|---|---|---|
| identity | `ttl` property, `key(suffix)` | `key` returns `f"{prefix}{suffix}"` |
| string | `set(key, value, nx=False) -> bool`, `get(key)`, `delete(*keys)`, `exists(key) -> bool` | `set` applies `ex=self._ttl` when `ttl > 0`; returns whether the SET was applied (for `nx=True` thread create). `exists` **propagates** errors (behavioural change 2 — no swallow). |
| hash | `hset(key, field, value)`, `hget(key, field) -> Optional[bytes]`, `hkeys(key) -> list[str]` | `hkeys` decodes bytes field names (as session drivers do today). |
| list | `rpush(key, value)`, `lpop(key) -> Optional[str]` (decodes), `llen(key) -> int`, `lrem(key, count, value)`, `lrange(key, start, end) -> list` (raw) | Used by attachment index and thread messages. |
| set | `sadd(key, member)`, `smembers(key) -> set[str]` (decodes) | Thread user/group indexes. |
| iteration | `scan_keys(match_suffix) -> list[str]` | `scan_iter(match=f"{prefix}{match_suffix}")`, decodes key names. |
| maintenance | `expire(key)` (no-op when `ttl <= 0` — never issue `EXPIRE key 0`), `clear_prefix()` | `clear_prefix`: `scan_iter(match=f"{prefix}*", count=1000)` + `delete(*keys)`. |

### 1.3 `redis.py` / `valkey.py`

Thin subclasses only:

```python
# driver/redis.py
import redis
class RedisDriver(_RedisLikeDriver):
    _backend_name = "Redis"
    _error_class = redis.RedisError
    def _from_url(self, url, **kwargs): return redis.from_url(url, **kwargs)
```

`driver/valkey.py` mirrors with `valkey` imported at module top (same as
`core/session/valkey.py` today); the factories keep their existing `try/except ImportError` →
"install `agentkernel[valkey]`" guidance.

## Task 2: DynamoDB, Cosmos DB, Firestore drivers

**New files:** `core/util/driver/dynamodb.py`, `cosmosdb.py`, `firestore.py`

All three: constructor-parameter based (no `AKConfig` reads), instance-state client handles
(**do not carry over** the class attributes `_ddb_resource`/`_ddb_table`,
`_table_service_client`/`_table_client`, `_client` from the current drivers), lazy connect
guarded by an instance `threading.Lock` (double-checked, same helper shape as
`_ensure_connected`), retries via `connect_with_retries(..., retry_on=Exception)`.

### 2.1 `DynamoDBDriver`

```python
class DynamoDBDriver:
    def __init__(self, table_name: str, partition_key: str, sort_key: Optional[str] = None,
                 region: Optional[str] = None, ttl: int = 0): ...
    @property
    def table(self): ...   # lazy: boto3.resource("dynamodb", region_name=self._region)
                           #       .Table(table_name) + .load(), with retry
    def put(self, item: dict) -> None: ...
    def get(self, pk_value, sk_value=None) -> Optional[dict]: ...
    def delete(self, pk_value, sk_value=None) -> None: ...
    def query_sort_keys(self, pk_value) -> list[str]: ...
    def clear_all(self) -> None: ...
```

- `put`: **copy the dict first** (`item = dict(item)`) before attaching
  `expiry_time = int(time.time()) + ttl` when `ttl > 0` — callers (response store) may reuse the
  message object.
- `get`: returns the **raw item dict** (or `None`) — value-attribute extraction
  (`value`/`data`/`body`) stays in the stores.
- `query_sort_keys`: `KeyConditionExpression=Key(partition_key).eq(pk_value)` with full
  `LastEvaluatedKey` pagination (port from `core/session/dynamodb.py:116-137`); raises if
  `sort_key` is unset.
- `clear_all`: paginated scan projecting the key attributes + `batch_writer` delete (port from
  `core/session/dynamodb.py:139-169`), parameterized by `partition_key`/`sort_key`.
- Keep the log-and-raise wrappers the session driver has on each operation.

### 2.2 `CosmosDBDriver`

Move `core/session/cosmosdb.py:14-232` bodies unchanged; changes only:

- Constructor: `__init__(self, connection_string: str, table_name: str, ttl: int = 0)`.
- Method renames so the package has one name per operation: `query_keys` → `query_sort_keys`,
  `delete_entity` → `delete`, `scan_and_clear_all` → `clear_all`. (`put`/`get` keep their names.)
- `table_client` stays a public lazy property (rule 3 — the Cosmos thread store consumes it
  natively); `_connect` keeps the `__health_check__` probe with the `ResourceNotFoundError`
  pass-through.

### 2.3 `FirestoreDriver`

Move `core/session/firestore.py:15-148` bodies unchanged; changes only:

- Constructor: `__init__(self, collection_name: str, project_id: Optional[str] = None,
  database_id: Optional[str] = None, ttl: int = 0)`.
- Surface moves **as-is** (`put`/`get`/`get_all_keys`/`delete_all` — no partition/sort model, so
  no renames). The `_RESERVED_FIELDS = {"expiry_time"}` constant moves with it.
- Keep the function-level `from google.cloud import firestore` inside `_connect()`.
- `collection` stays a public lazy property (the Firestore thread store needs subcollection
  access through it).

## Task 3: Migrate the session stores

**Files:** `core/session/redis.py`, `valkey.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`,
plus a docstring in `core/builder.py`

Per file — delete the local driver class, import the shared one, move config reading into the
store `__init__`:

1. **`redis.py`** — delete `RedisDriver` (lines 14–134). `RedisSessionStore.__init__`:

   ```python
   cfg = AKConfig.get().session.redis
   if cfg is None:
       raise ValueError("session.redis config block is required when session.type is 'redis'")
   self._driver = RedisDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
   ```

   The `ValueError` is **new** (behavioural change 4 — today a missing block raises
   `AttributeError`); message mirrors the Valkey one. `load`/`new`/`store`/`clear` bodies are
   unchanged — the shared surface has the same method names (`key`, `exists`, `hkeys`, `hget`,
   `hset`, `expire`, `clear_prefix`, `ttl`). Behavioural change 2 comes for free: the shared
   `exists()` no longer catches `RedisError`.
2. **`valkey.py`** — same shape; keep the existing `ValueError` message verbatim
   (`valkey.py:25`). Store bodies unchanged.
3. **`dynamodb.py`** — delete the local `DynamoDBDriver` (lines 15–169). Store constructs
   `DynamoDBDriver(table_name=cfg.table_name, partition_key="session_id", sort_key="key",
   ttl=cfg.ttl)` (keep the existing `ValueError` for missing `table_name`). Adapt to the
   item-dict interface — Binary handling moves **into the store** (`from boto3.dynamodb.types
   import Binary` moves here):
   - `store()`: `self._driver.put({"session_id": session.id, "key": key, "value": Binary(payload)})`
   - `load()`: `keys = self._driver.query_sort_keys(session_id)`; per key
     `item = self._driver.get(session_id, k)`; keep the missing-item guard
     (`if item is None: continue`) then unwrap `val = item["value"]`,
     `payload = val.value if hasattr(val, "value") else val`.
   - `clear()`: `self._driver.clear_all()`.
4. **`cosmosdb.py`** — delete the local `CosmosDBDriver` (lines 14–232). Store constructs
   `CosmosDBDriver(connection_string=cfg.connection_string, table_name=cfg.table_name,
   ttl=cfg.ttl)` (keep both existing `ValueError`s). Adapt call sites to the renamed methods:
   `query_keys(...)` → `query_sort_keys(...)`, `scan_and_clear_all()` → `clear_all()`.
   The `azure.*` imports leave this module (they live in the shared driver now).
5. **`firestore.py`** — delete the local `FirestoreDriver` (lines 15–148, incl.
   `_RESERVED_FIELDS`). Store constructs `FirestoreDriver(collection_name=cfg.collection_name,
   project_id=cfg.project_id, database_id=cfg.database_id, ttl=cfg.ttl)` (keep the existing
   `ValueError`). Method names unchanged.
6. **`core/builder.py:130`** — fix the stale `RedisDriver()` mention in the `build()` docstring.
   `SessionStoreBuilder.build()` itself is untouched (imports store classes only). Verify
   `core/session/__init__.py` never exported the drivers (spec says they were internal) — no
   export changes.

## Task 4: Migrate the multimodal attachment stores

**Files:** `core/multimodal/storage/redis.py`, `core/multimodal/storage/dynamodb.py`

1. **`redis.py`** — delete `RedisAttachmentDriver` (lines 16–119). `RedisAttachmentStore` keeps
   its `(session_id, url, ttl, prefix)` constructor and holds
   `RedisDriver(url=url, prefix=prefix, ttl=ttl)`. Key schema and data handling stay in the
   store:
   - Key helpers (store-private): attachment key `self._driver.key(f"{session_id}:{attachment_id}")`,
     index key `self._driver.key(f"{session_id}:_index")`.
   - `save()`: `driver.set(att_key, json.dumps(attachment))` (driver applies `ex=ttl`
     atomically); `driver.rpush(index_key, attachment_id)`; **then `driver.expire(index_key)`** —
     this preserves the index-key TTL refresh the deleted `append_index` did
     (`storage/redis.py:104`); without it `_index` keys would outlive their attachments. The
     prune loop becomes `while driver.llen(index_key) > max_attachments: old_id =
     driver.lpop(index_key)` (driver decodes) + delete.
   - `delete()`: `driver.delete(att_key)` + `driver.lrem(index_key, 0, attachment_id)`.
   - `get()`: `raw = driver.get(att_key)`; `json.loads(raw)` if truthy (json accepts bytes —
     `decode_responses` stays `False`).
   - Behavioural change 5 applies here: retry scope narrows from `Exception` to `RedisError`;
     behavioural change 7: a non-`RedisError` ping failure now raises instead of reconnecting.
2. **`dynamodb.py`** — delete `DynamoDBAttachmentDriver` (lines 21–117). `DynamoDBAttachmentStore`
   keeps its `(session_id, table_name, ttl)` constructor and holds
   `DynamoDBDriver(table_name=table_name, partition_key="session_id",
   sort_key="attachment_id", ttl=ttl)`. JSON encoding and `_index` bookkeeping stay in the store:
   - put: `driver.put({"session_id": sid, "attachment_id": aid, "data": json.dumps(data)})`
     (driver attaches `expiry_time`).
   - get: `item = driver.get(sid, aid)`; `json.loads(item["data"])` if item else `None`.
   - delete: `driver.delete(sid, aid)`.
   - `save()`/`delete()` index logic (`"_index"` item, prune) is unchanged apart from those calls.
3. `AttachmentStorageManager._build_driver()` (`storage_manager.py:32`) is untouched — it
   imports the store classes, whose names, modules, and constructors are unchanged.

## Task 5: Migrate the response stores

**Files:** `deployment/aws/core/response_store/redis.py`, `valkey.py`, `dynamodb.py`

Class names, base class (`ResponseStore`), and constructor signatures are all kept —
`ResponseDBHandler` (`handler.py`) needs no change.

1. **`redis.py` / `valkey.py`** (exact twins) — replace the eager
   `redis.Redis.from_url(url, decode_responses=True)` at `__init__` with
   `RedisDriver(url=url, prefix=prefix, ttl=int(ttl), decode_responses=True)` (Valkey:
   `ValkeyDriver`). Drop `_key`, `self.client`, `self.prefix`, `self.ttl`:
   - `add_message`: `self._driver.set(self._driver.key(request_id), json.dumps(message))` —
     `SET ... EX` is now atomic (behavioural change 3); the separate `expire` call disappears.
   - `get_message`: `raw = self._driver.get(self._driver.key(request_id))` (decoded str);
     unchanged JSON handling and `get_and_delete` flow.
   - `delete_message`: `self._driver.delete(self._driver.key(request_id))`.
   - Net behaviour changes 1 and 6: lazy connect (a bad URL now fails at first operation after
     3 retries, not in `ResponseDBHandler.__init__`), ping/reconnect on every access, and
     thread-safe connect (shared across `ECSOutputConsumer` threads + the REST poll path).
2. **`dynamodb.py`** — replace the eager `boto3.resource(...).Table(...)` with
   `DynamoDBDriver(table_name=table_name, partition_key="request_id", region=region,
   ttl=int(ttl))`:
   - `add_message`: `self._driver.put(message)` — the driver's copy-then-attach `expiry_time`
     replaces the hand-rolled block (and preserves the no-caller-mutation guarantee).
   - `get_message`: `item = self._driver.get(request_id)`; `None` check and `item["body"]`
     extraction stay in the store.
   - `delete_message`: `self._driver.delete(request_id)`.
   - Gains `.load()` table verification on first use (behavioural change 1).

## Task 6: Migrate the thread stores

**Files:** `core/thread/store/redis.py`, `dynamodb.py`, `cosmosdb.py`, `firestore.py`

All four: delete the inline `_connect()`, the class-attribute client handles
(`_redis_client`, `_ddb_resource`/`_ddb_table`, `_table_service_client`/`_table_client`,
`_client`), and the `client`/`table`/`table_client`/`collection` properties. Config reading and
the missing-config `ValueError`s stay verbatim in each `__init__`. `ThreadStoreBuilder.build()`
(`core/thread/store/base.py:160`) and `core/thread/store/__init__.py` need no changes — verify.

1. **`redis.py`** — holds `RedisDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))`; keep
   `self._prefix = cfg.prefix` for key-suffix stripping in `list_threads`. This store uses the
   **generic surface** (its commands are all generic Redis):
   - Key helpers switch to `driver.key(...)`: `_meta_key` →
     `self._driver.key(f"{session_id}:meta")`, likewise `:updated_at`, `:messages`,
     `index:user:{user_id}`, `index:group:{group_id}`.
   - `create()`: `self._driver.set(meta_key, metadata.model_dump_json(), nx=True)` — the bool
     return drives the existing "already exists → `load_metadata`" branch; `driver.sadd(...)`
     for indexes; `_expire` loop unchanged in shape but calls `driver.expire(key)` per key
     (the multi-key refresh **must stay** — shared user/group index sets need TTL renewal).
   - `update_name`/`load_metadata`/`append_message`: `driver.get`/`driver.set`/`driver.rpush`;
     `driver.set` now also applies `ex=ttl` (behavioural change 8 — redundant-but-harmless with
     `_expire`). Raw-bytes handling unchanged (`decode_responses=False`):
     `Thread.model_validate_json(payload)` accepts bytes; keep `updated.decode()`.
   - `get_messages()`: `driver.lrange(key, offset, offset+limit-1)` + `driver.llen(key)`.
   - `list_threads()`: `driver.smembers(...)` now returns **decoded** `set[str]` — drop the
     `m.decode()` comprehensions; the no-filter branch becomes
     `driver.scan_keys("*:meta")` (returns decoded full key names) with the existing
     `rsplit(":meta", 1)[0][len(self._prefix):]` strip.
   - `clear()`: `driver.clear_prefix()`.
   - Net gains (behavioural change 8): ping/reconnect, `socket_connect_timeout=5`, atomic
     `SET ... EX`; retry scope narrows to `RedisError` (change 5).
2. **`dynamodb.py`** — holds `DynamoDBDriver(table_name=cfg.table_name,
   partition_key="session_id", sort_key="sk")` — **`ttl=0`**: the store keeps its own
   `_expiry()`/`expiry_time` logic (per-item conditional TTL attachment the generic `put` can't
   express). Every data operation switches `self.table.` → `self._driver.table.` (rule 3:
   conditional puts, update expressions, `begins_with` queries, filtered scans, `batch_writer`
   all stay verbatim). Behaviourally unchanged.
3. **`cosmosdb.py`** — holds `CosmosDBDriver(connection_string=cfg.connection_string,
   table_name=cfg.table_name)`; all operations switch `self.table_client.` →
   `self._driver.table_client.` (entities, OData filters, pagination stay). The
   `TableServiceClient` import leaves this module; `ResourceExistsError`/`ResourceNotFoundError`
   imports stay (used by data ops). Behaviourally unchanged — the driver's `_connect` is the
   verbatim clone (incl. `__health_check__` probe) it already had.
4. **`firestore.py`** — holds `FirestoreDriver(collection_name=cfg.collection_name,
   project_id=cfg.project_id, database_id=cfg.database_id)`; keep `self._ttl = cfg.ttl` (the
   store writes its own `expiry_time` datetime fields). All operations switch
   `self.collection` → `self._driver.collection` (the `messages` subcollection layout hangs off
   it unchanged). Behaviourally unchanged.

## Task 7: Consolidate config classes

**File:** `core/config.py`

Convert the redefined config classes to subclasses of the base connection configs (the pattern
`_ResponseStoreRedisConfig(_RedisConfig)` at `config.py:280` already uses). Preserve every field
name, type, and default **exactly** — YAML files and `AK_MULTIMODAL__*` / `AK_THREAD__*` env vars
must be unaffected:

| Class (current line) | Becomes | Overrides |
|---|---|---|
| `_MultimodalStorageRedisConfig` (178) | `(_RedisConfig)` | `prefix = "ak:attachments:"`; **`ttl`: keep default 604800 but override to keep the "Attachment TTL in seconds" description** |
| `_MultimodalStorageDynamoDBConfig` (184) | `(_DynamoDBConfig)` | `table_name = "ak-attachments"` (+ its description); `ttl`: override description ("Attachment TTL in seconds (0 disables)") |
| `_ThreadRedisConfig` (215) | `(_RedisConfig)` | `prefix = "ak:thread:"`, `ttl = 2592000` (thread-oriented description) |
| `_ThreadDynamoDBConfig` (221) | `(_DynamoDBConfig)` | `table_name = "ak-agent-threads"` (+ description with `sk` sort key), `ttl = 0` (+ description) |
| `_ThreadFirestoreConfig` (229) | `(_FirestoreConfig)` | `collection_name = "ak-agent-threads"` (+ description), `ttl = 0` (+ description) |
| `_ThreadCosmosDBConfig` (239) | **stays independent** | subclassing would add an unused inherited `ttl` knob (Cosmos thread store does no TTL); its `table_name` default (`"akagentthreads"`) also differs |

Description policy (from the spec): override descriptions that are subsystem-specific and surface
in generated config docs (the `ttl` ones above); accept the inherited `url` description for
multimodal Redis ("… Use rediss:// for SSL" is an improvement).

Sanity-assert after the edit (throwaway check, or as part of Task 8): instantiate each class and
compare `model_fields` names/defaults against the pre-change values — e.g.
`_MultimodalStorageRedisConfig().url == "redis://localhost:6379"`, `.ttl == 604800`,
`.prefix == "ak:attachments:"`; `_ThreadRedisConfig().ttl == 2592000`; etc.

## Task 8: Tests

Follow `ak-dev-testing-conventions` (invoke the skill before writing). Run with
`cd ak-py && uv run pytest`.

### New: `ak-py/tests/test_shared_drivers.py`

Driver-level unit tests, all with mocked client libraries and `time.sleep` patched out:

1. **Retry helper / connect** — `_RedisLikeDriver` and `DynamoDBDriver`: 3 failed attempts
   re-raise the last error (assert 3 calls, 2 sleeps); an exception outside the retry scope
   (`ValueError` from `from_url`) raises immediately with zero retries/sleeps.
2. **Ping/reconnect** — established client, failing ping (`RedisError`) → reconnect; healthy
   ping → no reconnect; ping raising `TypeError` → propagates, no reconnect (behavioural
   change 7). Concurrency: two threads observing the same failed client produce exactly **one**
   `from_url` call — simulate by having the second lock holder find `_client` already replaced
   (identity compare) and skip.
3. **Redis command semantics** — `set` passes `ex=ttl` only when `ttl > 0`; `set(nx=True)`
   returns the applied/not-applied bool; `expire` uses the configured TTL and is a **no-op when
   `ttl <= 0`** (never issues `EXPIRE key 0`); `key()` applies the prefix; `clear_prefix` scans
   `{prefix}*` and deletes; `smembers` / `scan_keys` / `lpop` / `hkeys` decode bytes.
4. **DynamoDB semantics** — `put` attaches `expiry_time` only when `ttl > 0` **and does not
   mutate the caller's dict**; `get` returns the raw item / `None`; `query_sort_keys` follows
   `LastEvaluatedKey` pagination; sort-key-less mode (`request_id`-style) works for
   `put`/`get`/`delete` and `query_sort_keys` raises without a sort key.

### New: `ak-py/tests/test_sessions_dynamodb.py`

`DynamoDBSessionStore` with a mocked driver (largest store-body change, no existing coverage):
round trip asserting `store()` wraps payloads in `boto3 Binary` and `load()` unwraps via
`.value`; missing-item case: `driver.get()` returning `None` is skipped by `load()` (the
`payload is None: continue` guard) instead of raising.

### New: `ak-py/tests/test_multimodal_redis_store.py`

`RedisAttachmentStore` with a mocked driver: `save()` calls `driver.expire(index_key)` after
`driver.rpush(index_key, ...)` — the TTL refresh that moved out of the deleted `append_index`
(no other coverage exists for it).

### Updated existing tests

| File | Change |
|---|---|
| `test_sessions_redis.py`, `test_sessions_valkey.py` | Point imports/monkeypatch targets at `agentkernel.core.util.driver.redis` / `.valkey` (`from_url` lives there now). Assertions unchanged. Add a case for the new `session.redis config block is required...` `ValueError` (behavioural change 4). |
| `test_response_store_valkey.py` | Update the `from_url` patch point; the client is now created on **first operation**, not `__init__` (behavioural change 1). `FakeValkeyClient.set` must accept `ex=`; rework the `expirations`-dict assertions to check the `ex` value on `set`, since `expire()` is no longer called (behavioural change 3). |
| `test_firestore_database_id.py` | `FirestoreDriver` takes constructor params — build it directly with `project_id`/`database_id` instead of mocking `AKConfig` (or mock `AKConfig` at the store level). |
| `test_thread_store_redis.py` | The fixture's class-attribute injection (`store._redis_client = MagicMock()` + `RedisThreadStore._redis_client = None` reset) disappears — inject a mocked `RedisDriver` on the store. Rework `store.client.expire` assertions to `driver.expire`; TTL assertions must also accept `ex=` on `set` (behavioural change 8). |
| `test_thread_store.py` (DynamoDB cases) | Replace `store._ddb_table = MagicMock()` + class-attribute reset with a mock on `store._driver` (whose `.table` the store now uses). Data-operation assertions unchanged. |

### Full-suite + leftover-reference sweep

- `cd ak-py && uv run pytest`
- `grep -rn "RedisAttachmentDriver\|DynamoDBAttachmentDriver\|append_index\|query_keys\|scan_and_clear_all\|delete_entity" ak-py/src ak-py/tests` — confirm no stale references to deleted classes/renamed methods (excluding the shared driver's own definitions).
- Lint/format per `ak-dev-code-quality` before committing.

## Task 9: Sync docs and skills

1. `.agents/skills/ak-dev-architecture`: add `core/util/driver/` to the directory map; fix the
   multimodal storage-backend table's "connection pooling" traits (`SKILL.md:152`); update any
   thread-store coverage the #348 skill sync added in the meantime.
2. `.agents/skills/ak-dev-new-multimodal-storage`: its backend-traits table mentions "connection
   pooling" — update; it doesn't name the deleted driver classes, so no further edits.
3. `.agents/skills/ak-dev-testing-conventions`: the test-file table (`SKILL.md:67`) references
   `FirestoreDriver` for `test_firestore_database_id.py` — reflect its move to
   `core/util/driver/` and the constructor-parameter interface; add the three new test files to
   the table.
4. Docs website (`docs/docs/`): the spec verified no page documents the driver classes,
   retry/reconnect behaviour, or response-store connect timing, and config descriptions are
   preserved by Task 7 — expected result: **no docs-site changes**. Confirm by running the
   `ak-dev-sync-docs-from-branch` flow before merge.

## Behavioural changes checklist (must all hold at the end)

From the spec, verify each is true in the final diff:

1. Response stores: lazy connect + retry + ping/reconnect; DynamoDB one gains `.load()`.
2. Session Redis `exists()` propagates `RedisError` (no silent `False`).
3. Response-store Redis/Valkey TTL applied atomically via `SET ... EX`.
4. Session Redis raises `ValueError` on missing `session.redis` block.
5. Multimodal + thread Redis retry scope narrows to `RedisError`; DDB/Cosmos/Firestore keep
   bare `Exception`.
6. `_connect()` thread-safe (lock + identity re-check) — one connect under concurrency.
7. Ping failure outside `_error_class` propagates (session: was swallow; multimodal: was
   reconnect-on-anything).
8. Redis thread store: ping/reconnect + `socket_connect_timeout=5` + atomic `SET ... EX`; its
   multi-key `_expire` refresh is retained.

**Non-changes to protect:** stored data layouts, key schemas, serialization, TTL semantics
(pre-refactor data reads back identically); no public export changes; store class
names/modules/constructors unchanged; all four factories untouched; optional-dependency laziness
preserved (`driver/__init__.py` imports nothing eagerly; each store module imports only its own
backend's driver module).

## Risks / watch-outs

- **`decode_responses` regressions**: session/attachment/thread stores need raw bytes
  (`BinarySerde`, `model_validate_json`), response stores need decoded strings. The driver
  decodes selectively in `hkeys`/`lpop`/`smembers`/`scan_keys` regardless — make sure
  `get`/`hget`/`lrange` stay raw.
- **Thread-store `list_threads`**: `smembers`/`scan_keys` now return decoded strings — leaving
  the old `.decode()` calls in would raise `AttributeError` at runtime; covered by
  `test_thread_store_redis.py` updates.
- **`expire` with `ttl=0`**: a raw `EXPIRE key 0` deletes the key — the driver-level no-op guard
  is load-bearing for the attachment index and thread keys; unit-tested explicitly.
- **DynamoDB thread store must pass `ttl=0`** to the shared driver — otherwise `driver.table` is
  fine but any accidental use of `driver.put` would double-attach `expiry_time`; the store's own
  `_expiry()` remains the single TTL authority.
- **Import-time optionality**: importing `agentkernel.core.util.driver.valkey` without the
  `valkey` extra must raise `ImportError` only when that module is imported — verify session/
  response Valkey selection paths still produce the friendly "install agentkernel[valkey]"
  message.
