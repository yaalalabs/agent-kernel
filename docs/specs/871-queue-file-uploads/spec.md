# #871: File uploads on real queues: implementation spec

This spec says how to build [design.md](design.md). The requirements and the decisions behind them live there. Here we name the code that changes.

In short: the pipeline `RequestHandler` gets two new methods. One checks whether a request's files can cross the queue. The other saves the files and swaps them for IDs, using the existing `AttachmentStorageManager.offload`. The DynamoDB attachment store learns its size limit. Three Terraform modules stop hiding the upload route in queue mode. No new classes, no new config, no runner change.

Code references are at `develop` @ `d0453388`. All Python paths are under `ak-py/src/agentkernel/`.

## Design

### What already exists (reused, not rebuilt)

| Need | Existing code |
|---|---|
| Save files and swap them for IDs | `AttachmentStorageManager.offload` (`core/multimodal/storage/storage_manager.py:154-231`) |
| Turn a chat body into agent inputs | `RequestBuilder.from_base_request_async` (`core/chat_service.py:57-80`) |
| A queue field for a prebuilt input list | `BaseRunRequest.requests` (`core/model.py:727`), read by the runner (`pipeline/agent_runner.py:79`) |
| Tell base64 bytes from links and plain-text `data:` URIs | `AttachmentSource.extract` (`core/multimodal/source.py:48-66`) |
| Is the store readable from another process? | `AttachmentStorageManager.store_is_shared` (`core/multimodal/storage/storage_manager.py:112`) |
| Turn an ID back into a file on the runner | `MultimodalPreHook` (`core/multimodal/hooks.py:170-174`) |
| The same edge rewrite, thread mode | `ThreadRequestHandler._record_user_message` (`integration/thread/thread_chat.py:329-355`) |

### `RequestHandler` changes (`pipeline/request_handler.py`)

Two new methods. Both do nothing on the `in_memory` transport, so that path stays exactly as it is.

```python
class RequestHandler(RestHandler):
    def __init__(self):
        ...  # existing
        self._warn_if_store_is_unshared()   # new: startup warning (decision 6)

    def get_router(self) -> APIRouter:
        ...  # the multipart route is now added on every transport (drop the in_memory guard)

    def _reject_unqueueable_attachments(self, body: BaseRunRequest) -> None:
        """Refuse files that can't cross a broker, before any side effect. No I/O."""

    async def _offload_attachments(self, body: BaseRunRequest) -> None:
        """Save file bytes to the attachment store and rewrite the body to carry IDs only."""
```

#### `_reject_unqueueable_attachments(body)`

Runs only when the transport is not `in_memory` and the body has `files` or `images`. It raises `HTTPException(400, detail={"error": <msg>, "session_id": ...})`, the error shape the chat route already uses (`pipeline/request_handler.py:414`). The checks, in order:

1. **Plain-text `data:` URI** (decision 5). For each `FileData.file_data` / `ImageData.image_data`, a value that starts with `data:` and whose header (before the first comma) does not end in `;base64`. Message: `"File <name> is a plain-text data: URI; on a queue transport send it as base64 or as a link"`.
   - The check matches `AttachmentSource._resolve` (`core/multimodal/source.py:102-106`), but works on the raw field, so it needs no `RequestBuilder` call.
2. **File bytes present?** A value is file bytes when it is not a link (`http://`, `https://`, `s3://`) and not a plain-text `data:` URI. If no value is file bytes, return. Links travel as they do today.
3. **Multimodal off** (decision 1). Message: `"This request carries file bytes, but multimodal support is disabled. On a queue transport files are saved to the attachment store first: set multimodal.enabled: true with storage_type redis or dynamodb."`
4. **Store not shared** (decision 6). `not AttachmentStorageManager.store_is_shared()`. Message: `"multimodal.storage_type '<type>' keeps files in the process that saved them, but on the '<transport>' transport the agent runs in another one. Use redis or dynamodb to send files."`
   - `store_is_shared()` raises `AKConfigError` for an unknown `storage_type`. That propagates (500) as it does today on the first attachment. It is a broken config, not a request error.
5. **Over `api.max_file_size`.** The decoded size of each base64 value (after stripping a `data:...;base64,` header) is estimated as `len(payload) * 3 // 4 - payload.count("=", -2)`, so nothing is decoded. Message: the one `_read_upload` already uses (`pipeline/request_handler.py:548-549`).
   - The multipart route already checks this while reading. The check here covers the JSON route.

#### `_offload_attachments(body)`

Runs only when the transport is not `in_memory`, `multimodal.enabled` is true, `body.files or body.images` is set, and `body.schedule is None`. With multimodal off, the check has already refused any file bytes, so only links are left, and they travel as they are.

- A `schedule` block is skipped because `ScheduleManager.create_from_request` keeps only the prompt (`schedule/manager.py:95-111`). Saving files it will never read would only leave clutter behind.

Steps:

1. `requests = await RequestBuilder.from_base_request_async(body)`. This keeps every existing check (missing `mime_type`) and copies extra fields into the input list.
2. `requests, _ = await asyncio.to_thread(AttachmentStorageManager.offload, body.session_id, requests, attachments_disabled_error=..., session_cache_error=...)`. Both error texts are the decision 1 and decision 6 messages above. They can't fire after step 4 passed, but `offload` requires them.
3. `body.requests = requests; body.files = None; body.images = None`. This is the same rewrite the thread handler does (`integration/thread/thread_chat.py:353-355`).
4. A `ValueError` from steps 1–2 becomes `HTTPException(400, {"error": str(e), "session_id": ...})`. That covers a missing `mime_type`, and the DynamoDB size error below.

#### Where they are called

```python
async def run_chat(self, body, request):
    ...                                      # existing validation
    self._reject_unprocessable(body)
    self._reject_unroutable(body)
    self._reject_unqueueable_attachments(body)   # new
    await self._offload_attachments(body)        # new
    if self._config.execution.is_sse:
        return await self._run_chat_stream(body)
    return await self.enqueue_and_wait(body, request)
```

- Both reply paths (SSE and wait) enqueue the rewritten body.
- `run_multipart_chat` already ends in `self.run_chat(body, request)` (`pipeline/request_handler.py:544`), so the form route needs no extra call.
- `get_router` drops the `if self._transport_type == "in_memory"` guard (`pipeline/request_handler.py:378-382`) and its comment.

#### `_warn_if_store_is_unshared()`

- In `__init__`, when `multimodal.enabled`, the transport is not `in_memory`, and `store_is_shared()` is false: log one `warning` with the decision 6 message.
- An `AKConfigError` from `store_is_shared()` is caught and logged as a warning too. Startup must not start failing for a config that serves text today.

### `ThreadRequestHandler` change (`integration/thread/thread_chat.py`)

- In `run_chat` (`integration/thread/thread_chat.py:307-327`), call `self._reject_unqueueable_attachments(body)` right after `self._reject_unroutable(body)`, before `_record_user_message`. A refused request then leaves no thread behind.
- No other change. `_record_user_message` already sets `body.requests` and clears `files`/`images`, so the inherited `_offload_attachments` finds nothing to do.

### `DynamoDBAttachmentStore` change (`core/multimodal/storage/dynamodb.py`)

- New class constant `MAX_ITEM_BYTES = 400 * 1024`, DynamoDB's item size cap.
- `_put` measures the item before writing: the UTF-8 length of `json.dumps(data)`, plus the key values, plus a fixed 64-byte margin for attribute names and the TTL attribute. Over the cap, it raises `ValueError`: `"Attachment <name> is <n> KB stored, over DynamoDB's 400 KB item limit. Use multimodal.storage_type: redis for large files."`
  - `_put` gets the file name from `data.get("name")` when `data` is an attachment dict. The `_index` item has no name and is never near the cap.

### Consumer changes

- **REST pipeline edge (`RequestHandler`)**: the new check and save steps, plus the route guard removed.
- **Thread pipeline edge (`ThreadRequestHandler`)**: one added check call.
- **Agent runner, `MultimodalPreHook`, `ChatService`**: unchanged. Verified: the runner passes `body.requests` through (`pipeline/agent_runner.py:79`, `:126`, `:376`) and `_prepare_sync` uses it as is (`core/chat_service.py:684`).
- **Chat-app adapters, AG-UI, thread manager**: unchanged in code. They now get the clearer DynamoDB size error when they save a file over the cap (see Behavioural changes).
- **Direct-mode handlers (`api/handler.py`) and the plain `RestHandler`**: unchanged. ECS queue mode keeps the plain `RestHandler` until #870 lands.

### Terraform changes

| Module | File | Change |
|---|---|---|
| AWS ECS | `ak-deployment/ak-aws/containerized/state.tf:45-49` | Condition `(!var.queue_mode && !local.is_websocket_mode)` becomes `!local.is_websocket_mode`. Update the comment above it. **Lands only after #870.** |
| GCP containerized | `ak-deployment/ak-gcp/containerized/state.tf:100-107` | `var.queue_mode ? {} : {multipart}` always adds the multipart route. Update the comment. |
| GCP serverless | `ak-deployment/ak-gcp/serverless/state.tf:98-104` | Same as GCP containerized. |
| Azure | `ak-deployment/ak-azure/containerized/apim.tf:136-138` | None. The route is already exposed. |

The modules are vendored and released to the registry by CI, so their version pins are not edited by hand.

### Config changes

None. Reused as they are:

- `multimodal.enabled`, `multimodal.storage_type` (`core/config.py:420-435`).
- `multimodal.redis` (`_MultimodalStorageRedisConfig`, a `_RedisConfig`) and `multimodal.dynamodb` (`_MultimodalStorageDynamoDBConfig`, a `_DynamoDBConfig`) (`core/config.py:410-417`), including their `ttl`, the cleanup (decision 3).
- `api.max_file_size` (`core/config.py:120`).

Existing YAML files and `AK_*` environment variables keep their meaning.

### Behavioural changes

All intentional. Each applies only to broker transports unless it says otherwise.

1. `POST /api/v1/chat-multipart` is served on every transport. It returned 404 on brokers before.
2. JSON and multipart requests with base64 files are saved to the store, and the queue message carries IDs. Before, the bytes rode the queue and the runner's `MultimodalPreHook` saved them. With multimodal on, the agent sees the same description and ID either way.
3. Base64 files with multimodal off now get 400 (decision 1). Before, small ones worked and large ones failed at the broker.
4. Base64 files with an unshared store get 400 (decision 6). Before, small ones worked, because the runner saved them in its own process.
5. Plain-text `data:` URIs get 400 (decision 5).
6. JSON-route files over `api.max_file_size` get 400. Before, nothing checked them on the JSON route.
7. Startup logs a warning for multimodal on with an unshared store (decision 6).
8. **All transports, all callers:** a DynamoDB attachment over 400 KB raises `ValueError` with a clear message, instead of botocore's `ClientError` (`ValidationException`). Every caller of `save_attachment` sees this: chat-app adapters, AG-UI, the thread manager, and `MultimodalPreHook` on the runner. On the REST edge it becomes a 400.
9. Threads: requests refused by changes 3–5 leave no thread record, because the check runs before `_record_user_message`.

**Non-changes:**

- The `in_memory` transport path: same routes, same message shape, same runner behavior.
- The queue message format: `BaseRunRequest` fields are unchanged; only `requests` is now used by one more producer.
- `ChatRunRequest` still refuses a client-sent `requests` field (`core/model.py:743`). The edge sets it after parsing, as the thread handler does.
- What the agent sees for an attachment.
- The public exports and signatures of `AttachmentStorageManager`, `RequestBuilder`, and `ThreadRecorder`.
- Data written before the change is read back the same way. Nothing in the stores changes format.

## Error handling

| Failure | Where | What the client gets |
|---|---|---|
| Plain-text `data:` URI, multimodal off, unshared store, file over `max_file_size` | `_reject_unqueueable_attachments` | 400 `{"error", "session_id"}`, nothing saved or queued |
| Missing `mime_type` | `RequestBuilder` in `_offload_attachments` | 400, nothing queued (some files may already be saved; they expire with the store's TTL) |
| File over DynamoDB's 400 KB | `DynamoDBAttachmentStore._put` → `ValueError` | 400, nothing queued. Files saved earlier in the same request expire with the TTL. |
| Store unreachable (Redis down, DynamoDB throttled) | `offload` → driver exception | 500 from the existing FastAPI handler, nothing queued |
| Unknown `storage_type` | `store_is_shared` → `AKConfigError` | 500 on a file request, as today. A warning at startup, not a crash |
| Missing `redis`/`aws` extra | `require_extra` in `_build_driver` | The existing install-the-extra error |

- A file saved but never queued (a later failure in the same request) is not deleted. It expires with the store's TTL, the same as every other attachment (decision 3).
- **Thread safety:** `offload` runs in a worker thread through `asyncio.to_thread`. It builds a fresh `AttachmentStorageManager` per call, and each store builds its own driver, so the work shares no state with the event loop. This is the same pattern `_enqueue_request` already uses.
- **Per-request cost:** only requests with base64 files pay it, one store write per file plus one index write (`dynamodb.py:63-90`). Text-only requests do no new work: the new code checks `body.files or body.images` before anything else.

## Testing

### New tests

`tests/test_pipeline_request_handler.py`, new class `TestBrokerUploads`. Each test points the handler at a broker by monkeypatching `QueueTransportFactory.resolve_type` to return `"kafka"`, as `test_multipart_route_absent_on_broker_transports` already does (`tests/test_pipeline_request_handler.py:443-447`). The tests keep the in-memory transport and workers. Multimodal is on with `storage_type: in_memory`, and `AttachmentStorageManager.store_is_shared` is patched to return `True`, since edge and runner share the test process.

- **Size-capped transport:** a wrapper over `InMemoryTransport` whose input-queue `send` raises if the serialized message is over 64 KB. A 200 KB upload then:
  - returns 200 (`rest_sync`) through both `/api/v1/chat` (base64) and `/api/v1/chat-multipart`;
  - is sent as a message under 64 KB, with `requests` holding `AgentRequestAttachmentRef` entries and no `files`/`images`;
  - is described by `MultimodalPreHook` on the runner (patch `_described` to a fixed string, so no model call is made).
- The same round trip with `execution.mode: rest_sync` and `message_type: delta` (SSE), over the stream workers.
- A link (`https://...`) file travels untouched in `requests`. `offload` keeps a url-only record for it, as it does for chat apps and AG-UI.
- A request with `schedule` set and a file: no store write.
- Rejections, each asserting a 400 and an empty input queue:
  - multimodal off;
  - `store_is_shared` false;
  - a plain-text `data:` URI;
  - a JSON file over `api.max_file_size` (set `AK_API__MAX_FILE_SIZE` small).
- A text-only chat with an unshared store returns 200, and the handler's startup logged the warning (`caplog`).
- **Replaced:** `test_multipart_route_absent_on_broker_transports` becomes `test_multipart_route_served_on_broker_transports`.

`tests/test_thread_pipeline_recording.py`: one test. On a broker with multimodal off, a file request gets 400 and no thread is created.

`tests/test_multimodal_dynamodb_store.py` (new file): patch `agentkernel.core.multimodal.storage.dynamodb.DynamoDBDriver` with a fake that records `put` calls.

- An item under 400 KB is written.
- An item over 400 KB raises `ValueError` naming the file and `redis`, and nothing is written.

### Unchanged tests that must stay green

- `tests/test_pipeline_request_handler.py::TestMultipart` (the `in_memory` round trip).
- `tests/test_attachment_offload.py`, `tests/test_agui_queue_handler.py`, `tests/test_integration_producer.py`, `tests/test_thread_pipeline_recording.py`.

### Command

```bash
cd ak-py && uv run pytest tests/test_pipeline_request_handler.py tests/test_thread_pipeline_recording.py tests/test_multimodal_dynamodb_store.py tests/test_attachment_offload.py -q
```

Then the full suite with `uv run pytest -q`, `make lint-check-all` from the repo root (the CI lint check), and `terraform validate` in each changed module.

## External facts

Checked on 2026-11-18. They feed the deployment READMEs (decision 4).

- AWS API Gateway HTTP API: a 10 MB payload cap that can't be raised ([AWS docs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)). The multipart overhead counts too, so a file just under 10 MB is refused at the gateway with a 413.
- GCP API Gateway: a 32 MB request size limit ([GCP docs](https://docs.cloud.google.com/api-gateway/docs/quotas)). This is above the 10 MB default.
- Azure API Management: **not confirmed.** Microsoft's Q&A threads report different limits by tier and policy, and the official limits page was not found. The Azure README tells users to check their APIM tier's limits.
