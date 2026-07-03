# Conversation Thread Support

## Overview

Conversation Thread Support adds named, persistent conversation contexts (threads) to Agent Kernel. A thread holds a user's full message history across multiple chat requests, scoped to a user or group, and exposes that history via REST so any UI or client can integrate with it.

Agent Kernel currently manages conversation state through `Session`, which is ephemeral and scoped to a single request cycle. There is no built-in way to persist a full conversation across multiple requests under a shared identity, group conversations by user or project, or expose conversation history to a UI. Conversation Thread Support closes this gap, building on the existing `SessionStore` infrastructure and `RESTAPI` patterns.

Conversation Thread Support is **opt-in** — enabled only when a `thread` block is present in `config.yaml`. Agents without this block behave exactly as they do today. A thread is identified by the request's `session_id` — there is no separate `thread_id`. The thread for a given `session_id` is auto-created on that session's first chat request; every subsequent request carrying the same `session_id` appends to that same thread.

`user_id` is an optional field accepted on every chat request. It tags the thread on creation and enables user-scoped listing via `GET /threads?user_id=...` — no separate authentication is required to use it. No identity verification is applied in v1: any caller-supplied value is accepted, and ownership is not enforced. Once AK authentication is available, `user_id` will be derived from the token and enforced in `ConversationThreadManager` without any data model changes.

> **Platform scope:** Do not enable Conversation Thread Support for agents deployed on platforms with native thread management (Slack, Microsoft Teams). Those platforms own conversation history; enabling AK threads alongside them creates duplicate, divergent state.

> **Access model:** "v1" refers to the feature iteration, not a separate unprotected URL path. AK has a single set of routes (`/api/v1/*`). When authentication is enabled via `RESTAPI.add_auth_handlers()`, it wraps **all** routes globally — there is no bypass path. Until authentication is configured, any caller who knows a `session_id` can read or write its thread; deploy behind network-level access controls (VPC, API gateway) in the interim.

> **Deferred in v1:** No explicit `POST /threads` create endpoint (threads are created implicitly via `/chat`). No `DELETE /threads/{session_id}` (deferred until authentication is available).

---

## Architecture Overview

The Conversation Thread Support subsystem sits between the client and the existing Agent Kernel runtime. `ConversationThreadManager` is the universal attachment and thread handler — it is instantiated whenever `multimodal.enabled = true` OR a `thread` block is present in `config.yaml`. Thread lifecycle (create/load/append/history) is driven from `ChatService`, which already has `session_id` and `user_id` available on every request. `MultimodalPreHook` **remains** the attachment entry point in `Runtime._system_pre_hooks` — it is thread-aware simply by passing `session.id` (already available to it) straight through to `ConversationThreadManager.process_attachments`; no separate identifier needs to be threaded through the session's volatile cache, since `session_id` *is* the thread identifier. `ThreadRouter` is only mounted when thread config is present. An `AuthValidator` node is shown as a future integration point — it is not wired until AK authentication is implemented.

```mermaid
flowchart TD
    Client["Client\n(UI / API Consumer)"]

    subgraph API Layer
        REST["Thread REST Router\nFastAPI APIRouter"]
    end

    subgraph Service Layer
        TSM["ConversationThreadManager\n(service façade)"]
    end

    subgraph Storage Layer
        TS["ThreadStore\n(abstract)"]
        DDB["DynamoDBThreadStore"]
        FS["FirestoreThreadStore"]
        CDB["CosmosDBThreadStore"]
        REDIS["RedisThreadStore"]
        MEM["InMemoryThreadStore"]
    end

    AUTH["AuthValidator\n(future — not wired in v1)"]

    Client -->|"REST calls"| REST
    REST -.->|"future"| AUTH
    REST --> TSM
    TSM --> TS
    TS --> DDB
    TS --> FS
    TS --> CDB
    TS --> REDIS
    TS --> MEM
```

---

## Configuration

Conversation Thread Support is activated by adding a `thread` block to `config.yaml`. If the block is absent, no `ThreadRouter` or `ConversationThreadManager` is initialised. When thread support is enabled, `thread.blob` must also be present — AK raises a clear `ConfigurationError` at startup if it is missing.

The `thread.type` key selects the storage backend. Each backend has its own sub-key with provider-specific settings, mirroring the existing `session` configuration convention.

#### DynamoDB

```yaml
thread:
  type: dynamodb
  dynamodb:
    table_name: "ak-agent-threads"
    region: "us-east-1"        # optional — falls back to AWS_DEFAULT_REGION
  blob:
    type: s3
    s3:
      bucket: "ak-agent-attachments"
      region: "us-east-1"
      signed_url_ttl: 900      # optional — seconds; defaults to 900 (15 min)
```

#### Firestore

```yaml
thread:
  type: firestore
  firestore:
    collection_name: "ak-agent-threads"
    ttl: 2592000               # optional — seconds; omit for no TTL
  blob:
    type: gcs
    gcs:
      bucket: "ak-agent-attachments"
      signed_url_ttl: 900
```

#### CosmosDB

```yaml
thread:
  type: cosmosdb
  cosmosdb:
    container: "ak-agent-threads"
    partition_key: "user_id"   # optional — defaults to user_id
  blob:
    type: azure_blob
    azure_blob:
      container: "ak-agent-attachments"
      signed_url_ttl: 900
```

#### Redis

```yaml
thread:
  type: redis
  redis:
    prefix: "ak:thread:"
    url: "redis://localhost:6379"
    ttl: 2592000               # optional — seconds; omit for no TTL
  blob:
    type: memory
```

#### InMemory (local development / testing only)

```yaml
thread:
  type: memory
  blob:
    type: memory
```

---

## Key Components

| Component | Location | Responsibility |
|---|---|---|
| `Thread` | `core/thread/base.py` | Pydantic model representing a thread and its messages |
| `ThreadMessage` | `core/thread/base.py` | Pydantic model for a single message in a thread |
| `ThreadAttachment` | `core/thread/base.py` | Pydantic model for an attachment reference stored in a message |
| `ThreadStore` | `core/thread/store/base.py` | Abstract base defining the storage interface |
| `*ThreadStore` impls | `core/thread/store/*.py` | `dynamodb.py`, `firestore.py`, `cosmosdb.py`, `redis.py`, `in_memory.py` implementations |
| `ConversationThreadManager` | `core/thread/manager.py` | Service façade used by the API layer; owns attachment upload, description generation, and user scoping |
| `AttachmentBlobStore` | `core/multimodal/storage/blob.py` | Abstract base for cloud object storage (S3, GCS, Azure Blob) |
| `*AttachmentBlobStore` impls | `core/multimodal/storage/blob_*.py` | S3, GCS, Azure Blob, InMemory implementations |
| `ThreadRouter` | `api/thread/router.py` | FastAPI `APIRouter` wiring HTTP endpoints to `ConversationThreadManager` |
| `MultimodalPreHook` | `core/multimodal/hooks.py` | Existing system pre-hook, kept and made thread-aware; delegates to `ConversationThreadManager.process_attachments` using `session.id` |

---

## Data Model

### Entity Relationship

```mermaid
erDiagram
    THREAD {
        string session_id PK
        string user_id
        string group_id
        string name
        datetime created_at
        datetime updated_at
        json metadata
    }

    THREAD_MESSAGE {
        string message_id PK
        string session_id FK
        string role
        json content
        datetime timestamp
        json metadata
    }

    THREAD_ATTACHMENT {
        string attachment_id PK
        string message_id FK
        string session_id FK
        string name
        string mime_type
        string storage_key
        string storage_url
        string description
        datetime uploaded_at
    }

    THREAD ||--o{ THREAD_MESSAGE : contains
    THREAD_MESSAGE ||--o{ THREAD_ATTACHMENT : references
```

### Class Diagram

```mermaid
classDiagram
    class Thread {
        +str session_id
        +Optional[str] user_id
        +Optional[str] group_id
        +Optional[str] name
        +List[ThreadMessage] messages
        +datetime created_at
        +datetime updated_at
        +Dict metadata
    }

    class ThreadMessage {
        +str message_id
        +str role
        +Any content
        +List[ThreadAttachment] attachments
        +datetime timestamp
        +Dict metadata
    }

    class ThreadAttachment {
        +str attachment_id
        +str name
        +str mime_type
        +str storage_key
        +str storage_url
        +str description
        +datetime uploaded_at
    }

    class ThreadStore {
        <<abstract>>
        +create(thread: Thread) Thread
        +load(session_id: str) Thread
        +list_by_user(user_id: str, limit: int, offset: int) List[Thread]
        +list_by_group(group_id: str, limit: int, offset: int) List[Thread]
        +update(thread: Thread) Thread
    }

    class InMemoryThreadStore {
        -Dict _store
    }

    class DynamoDBThreadStore {
        -str table_name
    }

    class FirestoreThreadStore {
        -str collection
    }

    class CosmosDBThreadStore {
        -str container
    }

    class RedisThreadStore {
        -str key_prefix
        -int ttl
    }

    class ConversationThreadManager {
        -ThreadStore _store
        -AttachmentBlobStore _blob
        +get_or_create_thread(session_id, user_id, group_id, name) Thread
        +get_thread(session_id) Thread
        +list_threads(user_id, group_id, limit, offset) List[Thread]
        +append_message(session_id, message) Thread
        +upload_attachment(session_id, file, mime_type) ThreadAttachment
    }

    class AttachmentBlobStore {
        <<abstract>>
        +upload(key: str, data: bytes, mime_type: str) str
        +get_signed_url(key: str, ttl_seconds: int) str
        +delete(key: str) None
    }

    class S3AttachmentBlobStore {
        -str bucket
        -str region
    }

    class GCSAttachmentBlobStore {
        -str bucket
    }

    class AzureBlobAttachmentBlobStore {
        -str container
    }

    class InMemoryAttachmentBlobStore

    Thread "1" --> "0..*" ThreadMessage : contains
    ThreadMessage "1" --> "0..*" ThreadAttachment : references
    ThreadStore <|-- InMemoryThreadStore
    ThreadStore <|-- DynamoDBThreadStore
    ThreadStore <|-- FirestoreThreadStore
    ThreadStore <|-- CosmosDBThreadStore
    ThreadStore <|-- RedisThreadStore
    ConversationThreadManager --> ThreadStore : uses
    ConversationThreadManager --> AttachmentBlobStore : uses
    AttachmentBlobStore <|-- S3AttachmentBlobStore
    AttachmentBlobStore <|-- GCSAttachmentBlobStore
    AttachmentBlobStore <|-- AzureBlobAttachmentBlobStore
    AttachmentBlobStore <|-- InMemoryAttachmentBlobStore
```

---

## API Design

Conversation Thread Support integrates with the existing `/api/v1/chat` and `/api/v1/chat-multipart` endpoints. When thread config is enabled, a thread is automatically created for a `session_id` on that session's first request. No additional field is needed to continue a thread — reusing the same `session_id` continues the same thread, exactly as it already does for session state.

`user_id` is accepted as an optional field in the request body. It tags the thread on creation and enables user-scoped listing via `GET /threads?user_id=...` without requiring authentication. No identity verification is applied in v1 — the value is accepted as supplied by the caller. When authentication is available, `user_id` will be derived from the token and the request body field will be dropped.

### Modified Chat Endpoints (existing, extended)

`POST /api/v1/chat` and `POST /api/v1/chat-multipart` accept these new optional fields when Conversation Thread Support is enabled:

| Field | Type | Description |
|---|---|---|
| `user_id` | `string \| null` | Tags the thread with a user identity. Enables `GET /threads?user_id=...` filtering. Not verified in v1. |
| `thread_name` | `string \| null` | Display name — applied only when auto-creating a new thread (i.e. on a session's first request). If omitted, the thread is named from the first 80 characters of the prompt (trimmed to the last word boundary, suffixed with `…`). No LLM call is made for naming. |
| `group_id` | `string \| null` | Group or project scope — applied only when auto-creating a new thread. |

First turn — thread auto-created for this `session_id`:

```json
POST /api/v1/chat

{
  "prompt": "What is the refund policy?",
  "session_id": "ses_abc",
  "user_id": "usr_xyz",
  "thread_name": "Support conversation",
  "group_id": "project-42"
}
```

```json
200 OK
{
  "result": "The refund policy is...",
  "session_id": "ses_abc"
}
```

Subsequent turn — reuse the same `session_id` to continue the thread:

```json
POST /api/v1/chat

{
  "prompt": "What about international orders?",
  "session_id": "ses_abc"
}
```

### Thread Read Endpoints (new)

| Method | Path | Description |
|---|---|---|
| `GET` | `/threads` | List threads filtered by `user_id` or `group_id` query param |
| `GET` | `/threads/{session_id}` | Get a thread with full message history |
| `GET` | `/threads/{session_id}/attachments/{attachment_id}/url` | Refresh a signed URL for an attachment |

> `POST /threads` (explicit create) and `DELETE /threads/{session_id}` are not exposed in v1. Creation is implicit via `/chat`; deletion is deferred until authentication is in place.

Get thread — response:

```json
200 OK
{
  "session_id": "ses_abc",
  "user_id": "usr_xyz",
  "group_id": "project-42",
  "name": "Support conversation",
  "messages": [
    { "message_id": "msg_1", "role": "user", "content": "What is the refund policy?", "timestamp": "2026-06-28T10:00:00Z", "attachments": [] },
    { "message_id": "msg_2", "role": "assistant", "content": "The refund policy is...", "timestamp": "2026-06-28T10:00:05Z", "attachments": [] }
  ],
  "created_at": "2026-06-28T10:00:00Z",
  "updated_at": "2026-06-28T10:00:05Z"
}
```

---

## Workflows

### Thread Auto-Creation and Message Flow

```mermaid
flowchart TD
    A([Client sends POST /api/v1/chat\nwith session_id + optional user_id]) --> B{Thread exists\nfor this session_id?}
    B -->|No — first turn| C[ConversationThreadManager.get_or_create_thread\ncreates thread keyed by session_id, stores user_id]
    B -->|Yes — continuing| D[ConversationThreadManager.get_or_create_thread\nloads existing thread]
    C --> E[Agent generates response]
    D --> E
    E --> F[Append user + assistant messages to thread]
    F --> G([Return result\nsession_id is reused to continue the thread])

    style C fill:#fff3cd,stroke:#aaa
```

Because a thread's lifetime is identical to its session's lifetime, there is no scenario where a session is "new" but its thread already has history — a new `session_id` always means a brand-new, empty thread. Native per-framework session memory (see `ak-py/src/agentkernel/framework/*/`) is therefore always sufficient to reconstruct agent context; `Thread.messages` never needs to be re-injected into the agent's context.

### Ownership Check — Future State (Post-Authentication)

Not implemented in v1. Shown here so the implementation path is clear when authentication is added.

```mermaid
sequenceDiagram
    participant Client
    participant ThreadRouter
    participant AuthValidator
    participant ConversationThreadManager
    participant ThreadStore

    Client->>ThreadRouter: GET /threads/{session_id} + Bearer token
    ThreadRouter->>AuthValidator: validate(token, context)
    AuthValidator-->>ThreadRouter: ValidationResult(is_valid, subject=user_id)
    ThreadRouter->>ConversationThreadManager: get_thread(session_id, user_id)
    ConversationThreadManager->>ThreadStore: load(session_id)
    ThreadStore-->>ConversationThreadManager: Thread
    ConversationThreadManager->>ConversationThreadManager: assert thread.user_id == user_id
    ConversationThreadManager-->>ThreadRouter: Thread
    ThreadRouter-->>Client: 200 Thread JSON
```

### ThreadStore State Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created : ConversationThreadManager.get_or_create_thread()
    Created --> Active : First message appended
    Active --> Active : Messages appended / read
    Active --> Deleted : ConversationThreadManager.delete_thread()
    Deleted --> [*]
```

---

## Multimodal & Attachment Storage

`MultimodalPreHook` is **kept** as the single attachment entry point, registered in `Runtime._system_pre_hooks` exactly as it is today. `MultimodalPreHookFactory` now constructs it with a reference to the shared `ConversationThreadManager` instance (instantiated once at bootstrap whenever `multimodal.enabled = true` OR a `thread` block is present — see Task 4), instead of the hook building its own `AttachmentStorageManager` access path internally.

`MultimodalPreHook.on_run` already receives `session` as an argument, so it calls `await self._manager.process_attachments(session_id=session.id, requests=requests)` directly and returns its result — no separate identifier needs to be passed in via `ChatService` or stashed anywhere. The hook is a thin adapter; all description-generation, extraction, and storage logic lives in `ConversationThreadManager.process_attachments`, which operates in two modes based solely on whether thread config is present:

| Mode | Condition | Attachment storage | Thread record |
|---|---|---|---|
| **Session-only** | `multimodal.enabled = true`, no `thread` config | `AttachmentStorageManager(session_id)` — in-memory, Redis, or DynamoDB (existing backends) | None created |
| **Thread-enabled** | `thread` config present | `AttachmentBlobStore` — S3, GCS, or Azure Blob | `ThreadAttachment` appended to thread keyed by `session_id` |

In both modes: the LLM generates a brief description of the attachment, the binary is stripped from the request, and the description text is injected into the prompt before the agent runs. `AttachmentStorageManager` and its backends are kept unchanged — they continue to serve session-only mode. When thread config is disabled, `ConversationThreadManager.process_attachments` always operates in session-only mode — no regression to existing session-only behavior.

### Processing Flow

When a request with attachments arrives:

1. `Runtime.run` invokes `MultimodalPreHook.on_run`, which calls `ConversationThreadManager.process_attachments(session_id=session.id, requests=requests)`.
2. `process_attachments` receives the raw binary from the request.
3. **Session-only** (thread config absent): saves via `AttachmentStorageManager(session_id)`.  
   **Thread-enabled** (thread config present): uploads to cloud object storage under `threads/{session_id}/{message_id}/{attachment_id}/{filename}`, builds a `ThreadAttachment` record, and appends it to the thread.
4. Calls an LLM to generate a brief description of the attachment (both modes).
5. Returns a modified request list with binary stripped and description injected into the prompt text; `MultimodalPreHook` returns this list as-is.

### `AttachmentBlobStore` Abstraction

```mermaid
classDiagram
    class AttachmentBlobStore {
        <<abstract>>
        +upload(key: str, data: bytes, mime_type: str) str
        +get_signed_url(key: str, ttl_seconds: int) str
        +delete(key: str) None
    }
    class S3AttachmentBlobStore {
        -str bucket
        -str region
    }
    class GCSAttachmentBlobStore {
        -str bucket
    }
    class AzureBlobAttachmentBlobStore {
        -str container
    }
    class InMemoryAttachmentBlobStore {
        -Dict _blobs
    }
    AttachmentBlobStore <|-- S3AttachmentBlobStore
    AttachmentBlobStore <|-- GCSAttachmentBlobStore
    AttachmentBlobStore <|-- AzureBlobAttachmentBlobStore
    AttachmentBlobStore <|-- InMemoryAttachmentBlobStore
```

### Attachment Upload Flow

```mermaid
sequenceDiagram
    participant Client
    participant ChatService
    participant Session
    participant Runtime
    participant MultimodalPreHook
    participant ConversationThreadManager
    participant AttachmentBlobStore
    participant ThreadStore
    participant Agent

    Client->>ChatService: POST /api/v1/chat-multipart\n(multipart: text + file, session_id)
    ChatService->>ConversationThreadManager: get_or_create_thread(session_id, user_id, group_id, name)
    ConversationThreadManager-->>ChatService: Thread
    ChatService->>Runtime: run(agent, session, requests)
    Runtime->>MultimodalPreHook: on_run(session, agent, requests)
    MultimodalPreHook->>ConversationThreadManager: process_attachments(session_id=session.id, requests)
    ConversationThreadManager->>AttachmentBlobStore: upload(key, data, mime_type)
    AttachmentBlobStore-->>ConversationThreadManager: storage_key
    ConversationThreadManager->>AttachmentBlobStore: get_signed_url(storage_key, ttl)
    AttachmentBlobStore-->>ConversationThreadManager: storage_url
    ConversationThreadManager->>ConversationThreadManager: generate description via LLM
    ConversationThreadManager->>ConversationThreadManager: build ThreadAttachment\n(id, name, mime_type, storage_key, storage_url, description)
    ConversationThreadManager->>ThreadStore: append_message(ThreadMessage with attachments=[...])
    ThreadStore-->>ConversationThreadManager: updated Thread
    ConversationThreadManager-->>MultimodalPreHook: modified requests\n(binary stripped, description injected)
    MultimodalPreHook-->>Runtime: modified requests
    Runtime->>Agent: run(text + description)\nno raw binary passed to agent
    Agent-->>Runtime: response
    Runtime-->>ChatService: response
    ChatService->>ConversationThreadManager: append_message(assistant message)
    ConversationThreadManager->>ThreadStore: append_message(assistant message)
    ThreadStore-->>ConversationThreadManager: updated Thread
    ConversationThreadManager-->>ChatService: updated Thread
    ChatService-->>Client: 200 JSON\n(result + session_id, messages with attachment refs + storage_urls)
```

### UI Rendering of Thread History

Because `ThreadAttachment.storage_url` is a signed URL (or a stable public URL), the UI renders attachment thumbnails directly from the thread message payload without a separate API fetch. Signed URLs should be refreshed when they are close to expiry via `GET /threads/{session_id}/attachments/{att_id}/url`. This is only applicable in thread-enabled mode; session-only attachments are not UI-renderable (no URL is produced).

---

## Implementation Plan

### Task 1: Define `Thread`, `ThreadMessage`, `ThreadAttachment` Pydantic models

**File:** `ak-py/src/agentkernel/core/thread/base.py` (new)

1. Define `ThreadAttachment` with fields: `attachment_id`, `name`, `mime_type`, `storage_key`, `storage_url`, `description`, `uploaded_at`.
2. Define `ThreadMessage` with fields: `message_id`, `role`, `content: Any`, `attachments: List[ThreadAttachment]`, `timestamp`, `metadata: Dict`.
3. Define `Thread` with fields: `session_id`, `user_id: Optional[str]`, `group_id: Optional[str]`, `name: Optional[str]`, `messages: List[ThreadMessage]`, `created_at`, `updated_at`, `metadata: Dict`. `session_id` is the thread's primary key — no separate `thread_id` is generated.

---

### Task 2: Define `ThreadStore` abstract base and `InMemoryThreadStore`

**Files:** `ak-py/src/agentkernel/core/thread/store/base.py`, `store/in_memory.py` (new)

1. Define `ThreadStore` abstract base (in `store/base.py`) with methods: `create(thread) -> Thread`, `load(session_id) -> Thread`, `list_by_user(user_id, limit, offset) -> List[Thread]`, `list_by_group(group_id, limit, offset) -> List[Thread]`, `update(thread) -> Thread`.
2. Implement `InMemoryThreadStore` (in `store/in_memory.py`) backed by a `Dict[str, Thread]` keyed by `session_id`, for local development and tests.
3. Mirrors the existing `core/multimodal/storage/` package layout (`base.py`, `in_memory.py`, `redis.py`, `dynamodb.py`, ...) — a `store/` package under `thread/` rather than flat `store_*.py` files at the `thread/` top level.

---

### Task 3: Implement `ConversationThreadManager`

**File:** `ak-py/src/agentkernel/core/thread/manager.py` (new)

1. Implement `process_attachments(session_id, requests)` — the universal attachment handler, invoked by `MultimodalPreHook.on_run` (see Multimodal & Attachment Storage section; `session_id` is passed directly from `session.id`, which `MultimodalPreHook` already has):
   - Extracts `AgentRequestImage` and `AgentRequestFile` items from the request list.
   - Calls the LLM to generate a brief description of each attachment.
   - **Session-only mode** (thread config absent): saves via `AttachmentStorageManager(session_id)` — same behavior `MultimodalPreHook` already implements today.
   - **Thread-enabled mode** (thread config present): uploads to `_blob` under `threads/{session_id}/{message_id}/{attachment_id}/{filename}`, builds a `ThreadAttachment`, calls `append_message`. On blob upload success but store failure, delete the blob as a compensating action.
   - Returns the modified request list with binary stripped and descriptions injected into the prompt text.
2. Implement `get_or_create_thread(session_id, user_id, group_id, name)` — creates a new thread keyed by `session_id` if none exists, loads the existing thread otherwise. When `name` is `None`, auto-name from the first 80 characters of the first prompt in the request, trimmed to the last word boundary and suffixed with `…`. No LLM call is made for naming.
3. Implement `get_thread(session_id)` — raises `ThreadNotFoundError` if the thread does not exist.
4. Implement `list_threads(user_id, group_id, limit, offset)` — delegates to `_store.list_by_user` or `_store.list_by_group`; no ownership check applied in v1.
5. Implement `append_message(session_id, message)`.
6. Structure the class so enabling ownership enforcement post-auth (asserting `thread.user_id == caller_user_id`) is a single-file change with no data model migration.

---

### Task 4: Add `ThreadConfig` and wire bootstrap

**File:** `ak-py/src/agentkernel/core/config.py` (existing)

1. Add `ThreadConfig` Pydantic model (mirrors `SessionConfig`) that parses the `thread` block from `config.yaml`, including the `thread.blob` sub-key.
2. In the AK bootstrap, instantiate `ConversationThreadManager` when `multimodal.enabled = true` OR a `thread` block is present. `MultimodalPreHookFactory` stays registered in `Runtime._system_pre_hooks`; update it to construct `MultimodalPreHook` with the shared `ConversationThreadManager` instance instead of the hook building its own `AttachmentStorageManager` access path internally.
3. When thread config is present, also instantiate `ThreadStore` and `AttachmentBlobStore` and pass them to `ConversationThreadManager`. When only multimodal is enabled (no thread config), `ConversationThreadManager` is instantiated without `ThreadStore` or `AttachmentBlobStore` and operates in session-only mode.
4. Raise a clear `ConfigurationError` at startup if `thread` is enabled but `thread.blob` is missing.
5. Raise a clear `ConfigurationError` at startup on an unknown `thread.type` value.

---

### Task 5: Define `AttachmentBlobStore` abstract base and `InMemoryAttachmentBlobStore`

**File:** `ak-py/src/agentkernel/core/multimodal/storage/blob.py` (new)

1. Define `AttachmentBlobStore` abstract base with methods: `upload(key, data, mime_type) -> str`, `get_signed_url(key, ttl_seconds) -> str`, `delete(key) -> None`.
2. Implement `InMemoryAttachmentBlobStore` — stores bytes in a `Dict`; `get_signed_url` returns a `data:` URI. Used for tests and local development.
3. `AttachmentBlobStore` is a **separate** abstract base from the existing `AttachmentStore` (`core/multimodal/storage/base.py`) — deliberately not unified behind one interface:
   - **Data shape**: `AttachmentStore.save(attachment: dict, max_attachments: int)` takes a full metadata dict with base64 `data` embedded and enforces a count-based eviction policy. `AttachmentBlobStore.upload(key: str, data: bytes, mime_type: str)` takes raw bytes and a caller-built hierarchical key (`threads/{session_id}/{message_id}/{attachment_id}/{filename}`), with no eviction concept — durability/TTL is the cloud provider's job.
   - **Retrieval contract**: `AttachmentStore.get(id) -> dict` returns the actual bytes, because `analyze_attachments` re-reads session-only attachments back into the agent. `AttachmentBlobStore` has no byte-retrieval method at all — only `get_signed_url`, since thread attachments are rendered client-side from a URL, not pulled back into the agent.
   - Forcing one interface would mean either a near-empty base class both sides override entirely, or squashing one shape into the other, for two call sites that are never polymorphically swapped at runtime (`ConversationThreadManager.process_attachments` picks one or the other by mode, never both). Revisit only if a future caller needs to treat both backends interchangeably.

---

### Task 6: Implement `S3AttachmentBlobStore`

**File:** `ak-py/src/agentkernel/core/multimodal/storage/blob_s3.py` (new)

1. Implement `upload` using `boto3` `put_object`.
2. Implement `get_signed_url` using `generate_presigned_url` with configurable TTL (default 900 seconds).
3. Implement `delete` using `delete_object`.
4. Accept `bucket` and optional `region` from config.

---

### Task 7: Implement `GCSAttachmentBlobStore` and `AzureBlobAttachmentBlobStore`

**Files:** `ak-py/src/agentkernel/core/multimodal/storage/blob_gcs.py`, `blob_azure.py` (new)

1. GCS variant: `upload_from_string`, `generate_signed_url`, `delete_blob` via `google-cloud-storage`.
2. Azure Blob variant: `upload_blob`, SAS URL generation, `delete_blob` via `azure-storage-blob`.
3. Both accept provider-specific settings (bucket / container, TTL) from config.

---

### Task 8: Implement cloud `ThreadStore` backends

**Files:** `ak-py/src/agentkernel/core/thread/store/dynamodb.py`, `store/firestore.py`, `store/cosmosdb.py`, `store/redis.py` (new)

1. `DynamoDBThreadStore` — single table with `PK=session_id`; GSI on `user_id` and `group_id` for `list_by_user` / `list_by_group`.
2. `FirestoreThreadStore` — collection `threads`; Firestore query by `user_id` / `group_id` field with `limit` and `offset`.
3. `CosmosDBThreadStore` — container partitioned by `user_id`; cross-partition query for `list_by_group`.
4. `RedisThreadStore` — JSON hash per thread with optional TTL; secondary index sets for user and group listings.

---

### Task 9: Add thread fields to request models and integrate with `ChatService`

**File:** `ak-py/src/agentkernel/core/model.py` (existing)

1. Add `user_id: Optional[str] = None` to `BaseChatRequest` — makes `user_id` an explicit, documented field available across all request types.
2. Add `thread_name: Optional[str] = None` and `group_id: Optional[str] = None` to `BaseRunRequest` — these are no-ops when thread config is disabled. `session_id` already exists on the request and doubles as the thread identifier, so no new identifier field is added.

**File:** `ak-py/src/agentkernel/core/chat_service.py` (existing)

1. When thread config is enabled, call `ConversationThreadManager.get_or_create_thread(session_id, user_id, group_id, thread_name)` to resolve or create the thread for the current `session_id`, before calling `Runtime.run`. `MultimodalPreHook` already receives `session` in `on_run` and passes `session.id` straight to `ConversationThreadManager.process_attachments` — no additional plumbing is needed to communicate the identifier. When thread config is disabled, `ConversationThreadManager` operates in session-only mode exactly as it does today.
2. After the agent run, when thread config is enabled, call `ConversationThreadManager.append_message` for both the user message and the assistant response.
3. No new field is added to the chat response — the existing `session_id` field is the thread identifier, so clients need nothing extra to continue a thread.

---

### Task 10: Implement `ThreadRouter`

**File:** `ak-py/src/agentkernel/api/thread/router.py` (new)

1. Implement `GET /threads` with optional `user_id` and `group_id` query params; delegate to `ConversationThreadManager.list_threads`; no caller identity check applied in v1.
2. Implement `GET /threads/{session_id}` returning the full thread including message history and attachment references.
3. Implement `GET /threads/{session_id}/attachments/{attachment_id}/url` to refresh a signed URL.
4. Register via `RESTAPI.add()` — no changes to core `RESTAPI`.
5. Return `404 ThreadNotFound` for an unknown `session_id`; return `400` if both `user_id` and `group_id` are omitted on `GET /threads`.

---

### Task 11: Tests

**Files:** `ak-py/tests/thread/` (new)

1. **Unit:** `ConversationThreadManager` with mocked `ThreadStore` and `AttachmentBlobStore`; `user_id` stored on thread; `list_threads(user_id=...)` delegates to `list_by_user`; message serialisation round-trips.
2. **Integration:** each `ThreadStore` backend against a real provider (DynamoDB local, Firestore emulator, Azurite, Redis Docker).
3. **API:** FastAPI `TestClient` against `ThreadRouter`; 404 on unknown `session_id`; `GET /threads?user_id=xxx` returns matching threads; `GET /threads` without `user_id` or `group_id` returns 400.
4. **Multimodal:** multipart POST with an image → blob uploaded, `ThreadAttachment` stored with `storage_url`, raw binary absent from thread document; blob deleted on store failure (compensating action).
5. **Session-only mode:** multimodal request with no thread config → `ConversationThreadManager.process_attachments` saves to `AttachmentStorageManager(session_id)`, description injected into prompt, no thread record created, no blob store used.
6. **Config edge cases:** no `thread` key → `ThreadRouter` not registered, `/threads` paths return 404, `thread_name`/`group_id` fields in `/chat` silently ignored; `thread` present but `thread.blob` missing → startup error; unknown `thread.type` → startup error; chat with a new `session_id` → new thread auto-created; `GET /threads/{session_id}` for an unknown `session_id` → 404.

---

### Task 12: Documentation and examples

**Files:** `examples/`, `DEVELOPER_GUIDE.md`

1. Add a thread-aware example under `examples/` demonstrating a multi-turn conversation with `user_id` scoping and thread listing.
2. Update `DEVELOPER_GUIDE.md` with thread configuration, `user_id` usage (scoping without enforcement), and the explicit note that ownership is not enforced until AK authentication is available.

---

## Testing Strategy

Unit tests mock `ThreadStore` and `AttachmentBlobStore` to isolate `ConversationThreadManager` logic. Integration tests run each backend against a real provider using Docker or cloud emulators. API tests use FastAPI `TestClient` with `InMemoryThreadStore` and `InMemoryAttachmentBlobStore`.

Edge cases to cover:

- `config.yaml` has no `thread` key → `ThreadRouter` not registered; `/threads` paths return 404; `thread_name` and `group_id` fields in `/chat` are silently ignored.
- `thread` key present but `thread.blob` missing → startup `ConfigurationError`.
- Chat with a new `session_id` → new thread auto-created for that `session_id`.
- `GET /threads/{session_id}` for an unknown `session_id` → 404.
- `GET /threads?user_id=unknown` → empty list, not 404.
- Empty thread (no messages) → valid state, not an error.
- Very large thread (>1000 messages) → pagination via `limit`/`offset` on `list_by_user` / `list_by_group`.
- Message with attachment but no text content → valid; agent receives description only.
- Blob upload succeeds but store `append_message` fails → blob deleted as compensating action.
- Signed URL near or past expiry → refresh endpoint returns a new valid URL.
