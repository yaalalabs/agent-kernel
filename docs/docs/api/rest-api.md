---
sidebar_position: 1
---

# REST API

Agent Kernel provides a built-in REST API server for agent interaction.

## Starting the API Server

```python
from agentkernel.api import RESTAPI

if __name__ == "__main__":
    RESTAPI.run()
```

Or from CLI:

```bash
python my_agent.py
```

## Endpoints

### POST /api/v1/chat

Execute an agent with a message.

**Request:**

```json
{
  "agent": "assistant",
  "prompt": "What is 2 + 2?",
  "session_id": "user-123"
}
```

**Response:**

```json
{
  "result": "2 + 2 equals 4.",
  "session_id": "user-123"
}
```

#### Structured replies

`result` is a **string** unless the reply carries a format label. An agent configured for structured
output returns its content as a JSON string, which is what every example on this page shows:

```json
{
  "result": "{\"city\": \"Colombo\", \"temp_c\": 31}",
  "session_id": "user-123"
}
```

When a reply **is** labelled, by the [A2UI capability](../advanced/a2ui.md) or by an application
post-hook that sets `media_type`, `result` carries the object itself and the format travels beside
it:

```json
{
  "result": {"city": "Colombo", "temp_c": 31},
  "media_type": "application/a2ui+json",
  "session_id": "user-123"
}
```

So `result` is `string | object | array`, and `media_type` is the discriminator: **present means the
object form, absent means the string**. A client that has not opted into a labelled format never
sees the object form, because no framework adapter sets a media type.

#### Pausing for a human

An agent can stop mid-run to ask a person something: a gated tool awaiting approval, or a question
needing an answer. The request then answers **HTTP 202** with a top-level discriminator, so a client
branches on the outcome without parsing `result`:

```json
{
  "status": "PAUSED",
  "run_id": "9f2c…",
  "agent": "support",
  "interruptions": [
    { "id": "call_abc123", "kind": "tool_call", "tool_name": "issue_refund",
      "arguments": "{\"order_id\": \"ORD-1001\"}" }
  ],
  "session_id": "user-123"
}
```

`202` now means two things, a deferred request and a paused one, and the `status` key is what
separates them: a scheduled acknowledgement carries `"SCHEDULED"`, a pause carries `"PAUSED"`.

Answer it by sending `resume` **instead of** a prompt; `prompt` is optional and a decision can stand
alone:

```json
{
  "agent": "support",
  "session_id": "user-123",
  "resume": { "decisions": [ { "id": "call_abc123", "status": "approved" } ] }
}
```

A decision takes `status` (`approved` | `denied` | `cancelled`), an optional `message` carrying the
human's own words, and an optional `payload` for a structured answer. `run_id` on the `resume` block
is optional: the run is resolved from the interruption ids when it is absent.

A request carrying **both** `schedule` and `resume` is rejected with a 400: a decision deferred to a
later occurrence is no longer a decision.

See [Human in the Loop](../advanced/human-in-the-loop.md) for what each framework can carry back,
and for the session-store setting this depends on.

### GET /api/v1/agents

List all available agents.

**Response:**

```json
{
  "agents": ["assistant", "math", "code"]
}
```

### GET /health

Health check endpoint.

**Response:**

```json
{
  "status": "ok"
}
```

### Conversation Thread Endpoints

When [conversation threads](../advanced/threads.md) are enabled by mounting `AgentThreadRequestHandler` (which serves the standard chat routes with thread recording), it also serves two read-only routes:

**`GET /api/v1/threads`** lists the caller's threads, filterable by `group_id`, cursor-paginated (`limit`, `cursor`):

```json
{
  "threads": [{"session_id": "user-123", "name": "Trip planning", "user_id": "anne", "...": "..."}],
  "next_cursor": null
}
```

**`GET /api/v1/threads/{session_id}`** returns a single thread with its paginated message history (`limit`, `cursor`). A message's `content` is text and carries no other key; one recording a [paused run](../advanced/human-in-the-loop.md) or the decision answering it carries the object itself plus a `media_type` naming its format (see [Message Content](../advanced/threads.md#message-content)).

A message's `content` is text, exactly as before, unless the reply was labelled (see [A2UI](../advanced/a2ui.md)), in which case it is the payload object with `media_type` beside it, the same shape `result` has on a live reply. The key is absent on every unlabelled message:

```json
{
  "messages": [
    {"role": "user", "content": "Show me the refund form"},
    {"role": "assistant", "content": {"version": "v1.0", "createSurface": {"...": "..."}}, "media_type": "application/a2ui+json"},
    {"role": "assistant", "content": "Anything else?"}
  ],
  "next_cursor": null
}
```

Every thread route, the chat routes included, serves authenticated callers only: `AgentThreadRequestHandler` refuses to construct without an `identity` block (`AKConfigError`), the identity provider that block names turns the request's Bearer token into the caller's principal, and a request nothing authenticated is a `401 Authentication required`. A thread belongs to the principal that first used it, so another principal's request for it is a 403. A body carrying `user_id` is a 400: the acting user comes from the credential, not from the client. See [Identity and access](../advanced/identity-and-access.md).

## Error Handling

**400 Bad Request:**

```json
{
  "error": "Missing required field: agent"
}
```

**500 Internal Server Error:**

```json
{
  "error": "Agent execution failed",
  "session_id": "session-x"
}
```

## Passing additional context

You can pass additional properties in the request body. These will be automatically passed to the PreHooks with the key name, to be handled by the your code. These will not be passed to the Agents as input.

In the following example, **locale (string)** and **additional_context (dict)** will be passed to PreHooks as two **AgentRequestAny** objects with names "locale" and "additional_context". A complete example is provided [here](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/openai)

```json
{
  "agent": "assistant",
  "prompt": "What is 2 + 2?",
  "session_id": "user-123",
  "locale": "en-GB",
  "additional_context": { "ui_selections": [], "profile_name": "custom" }
}
```

`user_id` is the one extra key a body may not carry: who the request acts as comes from the credential (see [Authentication](#authentication)), and a body with a `user_id` is a 400.

Please study the [Hooks documentation](/docs/integrations/hooks) for the use of hooks to implement various use cases.

## Passing images and files

Agent Kernel supports sending images and files to agents in two ways: via JSON body with base64-encoded data, or as multipart form data for larger files. 

:::info Current Limitation
Currently, passing images and files only work with OpenAI SDK & Google ADK. Other implementations will be provided in future
:::


**NOTE:** Directly passing image is not recommended. It is advised to save images in Agent accessible storage and pass the URI. This can be done directly from the client side or via hooks. i.e. PreExecution Hooks can intercept the requests, detect images/files and store and modify the request to contain the URIs.

To prevent large files from being passed to LLMs, there is a `max_file_size` option in the REST API configuration (`api.max_file_size`, default 10 MB) which limits the attached file size.



### Supported file types

- **Images**: JPEG, PNG, GIF, WebP, and other image formats
- **Documents**: PDF, TXT, CSV, DOC, DOCX, and other document formats

Supported file formats will differ for different frameworks. Please refer to the relevant documentation.
 - [OpenAI Agents](https://platform.openai.com/docs/assistants/tools/file-search#supported-files)

The MIME type is automatically detected from uploads in multipart mode, or should be explicitly specified in the JSON body for base64-encoded data. Or it can be in the base64 string itself at the start of the string ( **E.g. "data:application/pdf;base64,........."**).

### Option 1: JSON Body (Base64 Encoded)

For smaller files and images, you can include them directly in the JSON request body as base64-encoded strings or direct URLs to publicly accessible files. Base64 strings works well for files under a few MB. The encoding increases the size at least by 33%.

**Request with images:**

```json
{
  "agent": "assistant",
  "prompt": "Can you describe this image?",
  "session_id": "user-123",
  "images": [
    {
      "name": "photo.jpg",
      "mime_type": "image/jpeg",
      "image_data": "base64_encoded_image_data_here"
    }
  ]
}
```

**Request with files:**

```json
{
  "agent": "assistant",
  "prompt": "What is the deadline mentioned in this document?",
  "session_id": "user-123",
  "files": [
    {
      "name": "document.pdf",
      "mime_type": "application/pdf",
      "file_data": "base64_encoded_pdf_data_here"
    }
  ]
}
```

**Request with both images and files:**

```json
{
  "agent": "assistant",
  "prompt": "Analyze this document and image",
  "session_id": "user-123",
  "files": [
    {
      "name": "report.pdf",
      "mime_type": "application/pdf",
      "file_data": "base64_encoded_pdf_data_here"
    }
  ],
  "images": [
    {
      "name": "chart.png",
      "mime_type": "image/png",
      "image_data": "base64_encoded_image_data_here"
    }
  ]
}
```

### Option 2: Multipart Form Data

For larger files, use the `/api/v1/chat-multipart` endpoint with `multipart/form-data`. This approach is more efficient for files larger than a few MB and avoids base64 encoding overhead.

**Endpoint:** `POST /api/v1/chat-multipart`

**Request parameters:**
- `prompt` (required): Text prompt for the agent
- `agent` (optional): Agent name
- `session_id` (optional): Session identifier
- `files` (optional): One or more file uploads (PDF, CSV, TXT, etc.)
- `images` (optional): One or more image uploads (JPEG, PNG, etc.)

**Example using curl:**

```bash
curl -X POST http://localhost:8000/api/v1/chat-multipart \
  -F "prompt=What is the deadline in this document?" \
  -F "agent=assistant" \
  -F "session_id=user-123" \
  -F "files=@document.pdf" \
  -F "images=@photo.jpg"
```

**Example using Python requests:**

```python
import requests

with open("document.pdf", "rb") as pdf_file, open("photo.jpg", "rb") as image_file:
    files = {
        "files": ("document.pdf", pdf_file, "application/pdf"),
        "images": ("photo.jpg", image_file, "image/jpeg")
    }
    data = {
        "prompt": "Analyze this document and image",
        "agent": "assistant",
        "session_id": "user-123"
    }
    
    response = requests.post(
        "http://localhost:8000/api/v1/chat-multipart",
        data=data,
        files=files
    )
    print(response.json())
```

**Response** (same for both methods):

```json
{
  "result": "The deadline mentioned in the document is December 12, 2025.",
  "session_id": "user-123"
}
```

A detailed example with tests are provided [here](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/openai)

### Choosing the right method

- **Use JSON body** for:
  - Small files (< 1-2 MB)
  - When you already have base64-encoded data
  - Simple API integration scenarios

- **Use multipart form data** for:
  - Large files (> 1-2 MB)
  - Multiple file uploads
  - Better performance and lower memory usage
  - Direct file uploads from forms or file systems

## Custom Routes

Agent Kernel REST API allows the users to add custom routes to the existing REST server by two ways. This is a support functionality that would avoid users from maintaining a separate REST server for other application work, and exposes an endpoint with a configurable prefix `/custom` by default.

### Option 1

Add a route directly

```python
from agentkernel.api import RESTAPI
from fastapi import APIRouter

# Optional custom route to add your own endpoints
router = APIRouter()


@router.post("/deposit")
async def run(req: dict):
    amount = req.get("amount")
    return {"result": f"Deposited ${amount} over the counter"}


RESTAPI.add(router=router)
# End of optional code block for REST API mode

if __name__ == "__main__":
    RESTAPI.run()
```

### Option 2

Add the default Agent REST API handler

```python
class CustomRESTRequestHandler(AgentRESTRequestHandler):

    def __init__(self):
        super().__init__()


    def get_router(self) -> APIRouter:
        router = super().get_router()

        @router.get("/custom")
        def custom():
            return custom_request_handler()

        return router

if __name__ == "__main__":
    RESTAPI.run([CustomRESTRequestHandler()])
```


## Streaming

Set `execution.mode: rest_sync` and `execution.message_type: delta` in `config.yaml` (or `AK_EXECUTION__MODE=rest_sync` and `AK_EXECUTION__MESSAGE_TYPE=delta`) to enable streaming. With this combination, `POST /api/v1/chat` and `POST /api/v1/chat-multipart` return a `text/event-stream` (SSE) response instead of JSON; no other code changes are required. Other combinations don't stream on the REST chat route: `rest_sync` and `rest_async` with `complete` answer with JSON, and `async` rejects it with a 400 that points to `/ws`.

On the queue pipeline with a broker transport (`sqs`, `kafka`, `nats`):

- Only `POST /api/v1/chat` streams. `/api/v1/chat-multipart` is not registered, because of broker message-size limits.
- SSE needs a shared response store that can hold chunks (Redis or Valkey). Otherwise startup fails with an error naming both fixes: such a store, or `async` with `message_type: delta`.

`execution.mode: stream` was removed and now fails when the configuration loads; use `rest_sync` with `message_type: delta` for SSE.

**Request:** Same JSON/multipart payload as the non-streaming endpoints.

**Response:** A stream of `data:` events, each a JSON-encoded `StreamChunk` (serialized with `exclude_none=True`, so absent fields are absent keys rather than `null`):

```
data: {"event": {"type": "message_start", "message_id": "a1b2", "role": "assistant"}, "done": false, "session_id": "user-123"}

data: {"delta": "Hello", "event": {"type": "text_delta", "message_id": "a1b2", "content": "Hello"}, "done": false, "session_id": "user-123"}

data: {"delta": " world!", "event": {"type": "text_delta", "message_id": "a1b2", "content": " world!"}, "done": false, "session_id": "user-123"}

data: {"event": {"type": "message_end", "message_id": "a1b2"}, "done": false, "session_id": "user-123"}

data: {"done": true, "session_id": "user-123"}

```

`event` carries the full typed stream event the runner emitted: a discriminated union of message boundaries (`message_start`/`message_end`), text (`text_delta`), tool calls (`tool_call_start`/`tool_call_args`/`tool_call_end`/`tool_call_result`), steps (`step_start`/`step_end`), and reasoning (`reasoning_start`/`reasoning_delta`/`reasoning_end`). `delta` is populated **only** when `event.type` is `text_delta`, and always equals `event.content`; every other frame omits `delta` entirely, so accumulate the full response by concatenating `delta` where present rather than by frame position. The final chunk has `"done": true` and carries neither `delta` nor `event`. If an unrecoverable error occurs mid-stream, the final chunk contains `"error"` instead.

**Client example (Python):**

```python
import httpx

with httpx.stream("POST", "http://localhost:8000/api/v1/chat", json={
    "agent": "assistant",
    "prompt": "What is 2 + 2?",
    "session_id": "user-123",
}) as response:
    for line in response.iter_lines():
        if line.startswith("data:"):
            print(line.removeprefix("data:").strip())
```

**Framework support:** OpenAI Agents SDK, Google ADK, LangGraph, Pydantic AI, Microsoft Agent Framework, and the Claude Agent SDK support token streaming. CrewAI and smolagents declare `supports_streaming = False` and raise `NotImplementedError` when `execution.message_type: delta` is used; keep `message_type: complete` (the default) for those frameworks instead.

For WebSocket-based streaming on AWS Lambda (serverless), see the [AWS Serverless deployment guide](/docs/deployment/aws-serverless#websocket-configuration) and the [streaming-openai example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/streaming-openai).


## Authentication

Authentication is configuration, not code. An `identity` block names the identity provider, and the dependency `RESTAPI` installs on every router turns each request's `Authorization: Bearer <credential>` header into the caller's `Principal` before any route runs. A messaging webhook's routes are the exception: the platform's own signature or token is their check, so they are mounted without it. The agent, its hooks and its tools then read who is calling through `session.get_principal()` and `ToolContext.get().principal`.

```yaml
identity:
  provider:
    type: static   # static | oidc | cognito | entra | firebase, or a dotted path to your own IdentityProvider
    static:
      principals:
        ALICE_TOKEN:   # names a secret resolved through the secret capability; the value is never in the file
          subject: alice
          groups: [ops]
```

The `static` provider suits demos and tests. Real deployments validate tokens against an issuer: `oidc` serves any OpenID Connect issuer (Auth0, Keycloak and Okta are configurations of it), and `cognito`, `entra` and `firebase` derive the issuer from the user pool, tenant or project. Those four need the `auth` extra (`uv add "agentkernel[auth]"`). Auth0, for example:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<tenant>.<region>.auth0.com/   # or the custom domain; trailing slash included, as Auth0 issues it
    audience: <the API identifier of your Auth0 API>
    claims:
      groups: https://<your namespace>/roles       # the namespaced claim an Auth0 Action sets; omit if you set none
```

### What the routes do with the principal

- **No `identity` block**: every request is the anonymous principal and an `Authorization` header is ignored, a malformed or non-bearer one included.
- **With a block**: a request without a credential is anonymous; a credential that is present must validate, or the response is a 401 (`Unauthorized`, or `Invalid authorization header` for a malformed header). The provider's reason goes to the logs only.
- The chat and streaming routes accept an anonymous caller, and the agent runs as the anonymous principal. The thread, schedule and AG-UI routes serve authenticated callers only: their handlers refuse to construct without an `identity` block, and an anonymous request to them is a `401 Authentication required`.
- A body or envelope carrying `user_id` is a 400: the acting user comes from the credential, never from the client.

Groups, roles (through a `role_mapper`), the principal on every other surface and the deployment adapters are covered in [Identity and access](../advanced/identity-and-access.md).

### Example Implementation

See [examples/aws-serverless/openai-auth](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/openai-auth) for the `static` provider on an API Gateway authorizer, with an Auth0 configuration documented beside it, and [examples/aws-containerized/crewai-auth](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/crewai-auth) for the same on ECS.

## Best Practices

- Use unique session IDs per conversation
- Handle errors gracefully
- Implement rate limiting in production
- Use HTTPS in production
- **Configure an identity provider for production deployments**
- Monitor API performance
