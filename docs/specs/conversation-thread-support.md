# Conversation Thread Support

## Overview

- **What it is**: named, persistent conversation contexts ("threads") for Agent Kernel.
  - A thread holds a user's full message history across multiple chat requests.
  - Scoped to a user or group.
  - History is exposed via REST so any UI or client can integrate with it.

- **Why it's needed**: Agent Kernel currently manages conversation state through `Session`, which is ephemeral and scoped to a single request cycle.
  - No built-in way to persist a full conversation across multiple requests under a shared identity.
  - No built-in way to group conversations by user or project.
  - No built-in way to expose conversation history to a UI.
  - Conversation Thread Support closes this gap, building on the existing `SessionStore` infrastructure and `RESTAPI` patterns.

- **Enablement and identification**:
  - **Opt-in** — enabled only when a `thread` block is present in `config.yaml`; agents without this block behave exactly as they do today.
  - A thread is identified by the request's `session_id` — there is no separate `thread_id`.
  - The thread for a given `session_id` is auto-created on that session's first chat request.
  - Every subsequent request carrying the same `session_id` appends to that same thread.

- **`user_id` requirement**: required on every chat request once Conversation Thread Support is enabled.
  - A request missing it is rejected.
  - It tags the thread on creation and enables user-scoped listing via `GET /threads?user_id=...` — no `Authoriser` is required to use it.
  - **Without an `Authoriser` configured**: no identity verification is applied — any caller-supplied `user_id` is accepted, and ownership is not enforced.
  - **With an `Authoriser` configured** (see Authorisation Flow below): `user_id` is instead resolved from the Bearer token and enforced in `ConversationThreadManager`.
  - When thread support is disabled, `user_id` is not required and has no effect.

- **Attachment support**:
  - Still decided by `multimodal.enabled`, not by the `thread` block itself — enabling `thread` does not automatically turn on attachments.
  - However, `thread` will not support attachments on its own: thread-enabled attachment storage reuses the same byte-encoding approach as the existing `AttachmentStore`.
  - `multimodal` must also be defined in `config.yaml` whenever `thread` is defined.
  - A `thread` block with no `multimodal` block raises a `ConfigurationError` at startup.

> **Platform scope:** Do not enable Conversation Thread Support for agents deployed on platforms with native thread management (Slack, Microsoft Teams). Those platforms own conversation history; enabling AK threads alongside them creates duplicate, divergent state.

> **Access model:** AK has a single set of routes (`/api/v1/*`). Authorization is optional and pluggable — an end user can supply their own `Authoriser` (a base class provided by Agent Kernel) to protect thread routes; see the Authorisation Flow diagram below. Until an `Authoriser` is configured, any caller who knows a `session_id` can read or write its thread; deploy behind network-level access controls (VPC, API gateway) in the interim.

> **Deferred in v1:** No explicit `POST /threads` create endpoint (threads are created implicitly via `/chat`). No `DELETE /threads/{session_id}`.

---

## Architecture Overview

- The Conversation Thread Support subsystem sits between the client and the existing Agent Kernel runtime.

- **`ConversationThreadManager`**:
  - Instantiated whenever `multimodal.enabled = true` OR a `thread` block is present in `config.yaml`.
  - Only handles attachments when `multimodal.enabled = true` — the `thread` block by itself only turns on text history.

- **Thread lifecycle** (create/load/append/history) is driven from `ChatService`, which already has `session_id` and `user_id` available on every request.

- **`MultimodalPreHook`**:
  - **Remains** the sole attachment entry point in `Runtime._system_pre_hooks`, gated by `multimodal.enabled` exactly as today.
  - Is thread-aware simply by passing `session.id` straight through to `ConversationThreadManager.process_attachments`, since `session_id` *is* the thread identifier.

- **Attachment storage**: stored as bytes directly inside `ThreadStore` — the same encoding approach `AttachmentStore` already uses — so no separate blob store is involved.

- **`ThreadRouter`**:
  - Only mounted when thread config is present.
  - Optionally protected by a pluggable `Authoriser` supplied by the end user.

```mermaid
flowchart TD
    Client["Client\n(UI / API Consumer)"]

    subgraph Existing["Existing Agent Kernel runtime — unchanged"]
        RESTAPI["RESTAPI\n/api/v1/chat, /chat-multipart"]
        ChatService["ChatService"]
        SessionStore["Session / SessionStore"]
        Runtime["Runtime"]
        MMHook["MultimodalPreHook\n(_system_pre_hooks)"]
        Agent["Agent"]
    end

    subgraph New["Conversation Thread Support — new"]
        ThreadRouter["ThreadRouter\nGET /threads*"]
        TSM["ConversationThreadManager"]
        TS["ThreadStore\n(DynamoDB / Firestore / CosmosDB / Redis / InMemory)\nstores attachments as bytes"]
        AUTH["Authoriser\n(pluggable — user-supplied subclass)"]
    end

    Client -->|"POST chat / chat-multipart"| RESTAPI --> ChatService
    ChatService --> SessionStore
    ChatService -->|"get_or_create_thread\nappend_message"| TSM
    ChatService --> Runtime --> MMHook
    Runtime --> Agent
    MMHook -->|"process_attachments\n(session.id) — only if multimodal.enabled"| TSM
    TSM --> TS

    Client -->|"GET /threads*\nBearer token"| ThreadRouter --> TSM
    ThreadRouter -->|"authorise(token)\nif configured"| AUTH
```

---

## Configuration

- **Activation**: Conversation Thread Support is activated by adding a `thread` block to `config.yaml`.
  - **If absent**: no `ThreadRouter` or `ConversationThreadManager` is initialised, and `user_id` stays optional with no effect.
  - **Once present**: `user_id` becomes required on every chat request.

- **Dependency on `multimodal`**: `thread` has a hard dependency on `multimodal` being defined.
  - AK raises a `ConfigurationError` at startup if a `thread` block is present without a `multimodal` block.
  - Reason: thread-enabled attachment storage reuses the same byte-encoding approach as `AttachmentStore`; there is no separate blob store to configure.

- **Storage backend selection**:
  - The `thread.type` key selects the storage backend.
  - Each backend has its own sub-key with provider-specific settings, mirroring the existing `session` configuration convention.

#### DynamoDB

```yaml
thread:
  type: dynamodb
  dynamodb:
    table_name: "ak-agent-threads"
    region: "us-east-1"        # optional — falls back to AWS_DEFAULT_REGION
```

#### Firestore

```yaml
thread:
  type: firestore
  firestore:
    collection_name: "ak-agent-threads"
    ttl: 2592000               # optional — seconds; omit for no TTL
```

#### CosmosDB

```yaml
thread:
  type: cosmosdb
  cosmosdb:
    container: "ak-agent-threads"
    partition_key: "user_id"   # optional — defaults to user_id
```

#### Redis

```yaml
thread:
  type: redis
  redis:
    prefix: "ak:thread:"
    url: "redis://localhost:6379"
    ttl: 2592000               # optional — seconds; omit for no TTL
```

#### InMemory (local development / testing only)

```yaml
thread:
  type: memory
```

---

## Workflows

### Attachment Flow

```mermaid
sequenceDiagram
    participant Client
    participant ChatService
    participant Runtime
    participant MultimodalPreHook
    participant ConversationThreadManager
    participant ThreadStore
    participant Agent

    Client->>ChatService: POST /api/v1/chat-multipart\n(multipart: text + file, session_id)
    ChatService->>ConversationThreadManager: get_or_create_thread(session_id, user_id, group_id, name)
    ConversationThreadManager-->>ChatService: Thread
    ChatService->>Runtime: run(agent, session, requests)
    Runtime->>MultimodalPreHook: on_run(session, agent, requests)
    MultimodalPreHook->>ConversationThreadManager: process_attachments(session_id=session.id, requests)
    ConversationThreadManager->>ConversationThreadManager: encode attachment to bytes\n(same approach as AttachmentStorageManager)
    ConversationThreadManager->>ConversationThreadManager: generate description via LLM
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
    ChatService-->>Client: 200 JSON\n(result + session_id)
```

### Authorisation Flow

- **`Authoriser`**: a pluggable base class provided by Agent Kernel.
  - Assumes the end user already has an authentication provider — Agent Kernel does not verify identity itself.
  - The end user supplies a subclass that:
    - Receives only the Bearer token.
    - Implements whatever custom logic is needed to validate it against their own provider and resolve a subject (`user_id`).
  - **If no `Authoriser` is configured**: `ThreadRouter` routes remain open, as described under **Access model** above.

```mermaid
sequenceDiagram
    participant Client
    participant ThreadRouter
    participant Authoriser
    participant ConversationThreadManager
    participant ThreadStore

    Client->>ThreadRouter: GET /threads/{session_id}\nAuthorization: Bearer <token>
    ThreadRouter->>Authoriser: authorise(token)
    Note over Authoriser: User-defined logic against\nthe caller's own auth provider
    Authoriser-->>ThreadRouter: subject (user_id) or rejected
    ThreadRouter->>ConversationThreadManager: get_thread(session_id, user_id)
    ConversationThreadManager->>ThreadStore: load(session_id)
    ThreadStore-->>ConversationThreadManager: Thread
    ConversationThreadManager->>ConversationThreadManager: assert thread.user_id == user_id
    ConversationThreadManager-->>ThreadRouter: Thread
    ThreadRouter-->>Client: 200 Thread JSON
```

