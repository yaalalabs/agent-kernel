# Multimodal Example - autogen

Demonstrates Agent Kernel multimodal (image/file) support using HuggingFace autogen.

This example runs a autogen agent behind Agent Kernel REST API and supports sending
images/files in chat requests.

## Running the Example

```bash
export AK_MULTIMODAL__ENABLED=true
export OPENAI_API_KEY="your-openai-api-key"
uv run python app.py
```

## Running the Integration Test

```bash
export OPENAI_API_KEY="your-openai-api-key"
uv run pytest autogen_test.py -v -s
```
