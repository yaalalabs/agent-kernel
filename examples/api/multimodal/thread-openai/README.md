# Multimodal Example with Conversation Threads — OpenAI SDK

Demonstrates Agent Kernel's Conversation Thread Support combined with multimodal (image/file) support, using the
native OpenAI Agent SDK.

The app mounts `AgentThreadRequestHandler` (see `app.py`), which is what enables threads; the `thread` block
in `config.yaml` selects the store backend, and `multimodal.enabled: true` turns on attachment support. Every
chat request must carry a `user_id` (all chat routes here are the thread handler's), a thread is auto-created
per `session_id`, and uploaded attachments are saved to the multimodal `AttachmentStore` with only an
`attachment_id` reference kept on the thread message — the thread never stores the raw bytes. The full
conversation history, including attachment references, is readable over REST.

Thread read endpoints are protected by the pluggable `Authoriser` (`DemoAuthoriser` maps `alice-token` → `alice`
and `bob-token` → `bob`; a real subclass would validate the Bearer token against your own authentication provider).

## Running the Example

```bash
export OPENAI_API_KEY="your-openai-api-key"
uv run python app.py
```

Chat with an image (`user_id` is required because thread support is enabled):

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What animal is this?",
    "session_id": "ses-1",
    "user_id": "alice",
    "images": [{"name": "elephant", "mime_type": "image/webp", "image_data": "<base64>"}]
  }'
```

`image_data` also accepts a URL, in which case the bytes are never copied into the attachment store —
the address is recorded instead and the agent framework's adapter resolves it. `mime_type` is optional
for this form:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What animal is this?",
    "session_id": "ses-2",
    "user_id": "alice",
    "images": [{"name": "animal.jpg", "image_data": "https://example.com/animal.jpg"}]
  }'
```

Read the thread — the user message carries an attachment reference (`attachment_id`), not the image bytes:

```bash
curl http://localhost:8000/api/v1/threads/ses-1 -H "Authorization: Bearer alice-token"
```

## Running the Integration Test

```bash
export OPENAI_API_KEY="your-openai-api-key"
uv run pytest -v -s
```
