# Multimodal Example with Conversation Threads — OpenAI SDK

Demonstrates Agent Kernel's Conversation Thread Support combined with multimodal (image/file) support, using the
native OpenAI Agent SDK.

The app mounts `AgentThreadRequestHandler` (see `app.py`), which is what enables threads; the `thread` block
in `config.yaml` selects the store backend, and `multimodal.enabled: true` turns on attachment support. Every
chat request must carry a bearer token (all chat routes here are the thread handler's, and a thread belongs to
the caller), a thread is auto-created per `session_id`, and uploaded attachments are saved to the multimodal
`AttachmentStore` with only an `attachment_id` reference kept on the thread message: the thread never stores
the raw bytes. The full conversation history, including attachment references, is readable over REST.

Who is calling comes from the `identity` block in `config.yaml`: the `static` provider maps two credentials to
the principals `alice` and `bob`. The credential values are resolved from the environment (`ALICE_TOKEN`,
`BOB_TOKEN`) when the app starts, never written in the file. Swap the provider for `oidc`, `cognito`, `entra`
or `firebase` to validate real tokens; see [`examples/api/thread-openai`](../../thread-openai/README.md).

## Running the Example

```bash
export OPENAI_API_KEY="your-openai-api-key"
export ALICE_TOKEN=alice-token BOB_TOKEN=bob-token
uv run python app.py
```

Chat with an image, as alice:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer alice-token" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What animal is this?",
    "session_id": "ses-1",
    "images": [{"name": "elephant", "mime_type": "image/webp", "image_data": "<base64>"}]
  }'
```

`image_data` also accepts a URL, in which case the bytes are never copied into the attachment store —
the address is recorded instead and the agent framework's adapter resolves it. `mime_type` is optional
for this form:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer alice-token" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What animal is this?",
    "session_id": "ses-2",
    "images": [{"name": "animal.jpg", "image_data": "https://example.com/animal.jpg"}]
  }'
```

Read the thread (the caller's own; `bob-token` would get a 403): the user message carries an attachment
reference (`attachment_id`), not the image bytes:

```bash
curl http://localhost:8000/api/v1/threads/ses-1 -H "Authorization: Bearer alice-token"
```

## Running the Integration Test

```bash
export OPENAI_API_KEY="your-openai-api-key"
uv run pytest -v -s
```
