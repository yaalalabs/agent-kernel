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

In the following example,  **user_id (string)** and **additional_context (dict)** will be passed PreHooks as two **AgentRequestAny** objects with names "user_id"and "additional_context". A complete example is provided [here](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/openai)

```json
{
  "agent": "assistant",
  "prompt": "What is 2 + 2?",
  "session_id": "user-123",
  "user_id" : "anne",
  "additional_context": { "ui_selections"=[], profile_name="custom"}
}
```

Please study the [Hooks documentation](../integrations/hooks.md) for the use of hooks to implement various use cases.

## Passing images and files

Agent Kernel supports sending images and files to agents in two ways: via JSON body with base64-encoded data, or as multipart form data for larger files. 

:::info Current Limitation
Currently, passing images and files only work with OpenAI SDK & Google ADK. Other implementations will be provided in future
:::


**NOTE:** Directly passing image is not recommended. It is advised to save images in Agent accessible storage and pass the URI. This can be done directly from the client side or via hooks. i.e. PreExecution Hooks can intercept the requests, detect images/files and store and modify the request to contain the URIs.

To prevent large files from being passed to LLMs, there is a `max_file_size` option in the REST API configuration which limits the attached file size.



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
    RESTAPI.run(handler=CustomRESTRequestHandler())
```


## Streaming

Support for streaming responses will be available soon


## Authentication

Agent Kernel REST API supports authentication through custom validators. You can implement authentication to secure your endpoints.

### Implementing Authentication

Create a custom auth validator by extending `AuthValidator`:

```python
from agentkernel.api import RESTAPI
from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from typing import Optional

class CustomAuthValidator(AuthValidator):
    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        """Validate authentication token and return result."""
        if token == "your-secret-token":
            return ValidationResult(is_valid=True, subject="api_user")
        return ValidationResult(is_valid=False, error_msg="Invalid token")

# Add authentication to REST API
RESTAPI.add_auth_handlers(auth_validators=[CustomAuthValidator()])
```

### Example Implementation

See [examples/aws-containerized/crewai-auth/app.py](../../examples/aws-containerized/crewai-auth/app.py) for a complete authentication example with custom token validation.

## Best Practices

- Use unique session IDs per conversation
- Handle errors gracefully
- Implement rate limiting in production
- Use HTTPS in production
- **Add authentication for production deployments**
- Monitor API performance
