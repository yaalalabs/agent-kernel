# Multimodal Example — OpenAI SDK

Demonstrates Agent Kernel's foundational multimodal (image/file) support using the native OpenAI Agent SDK.

Agent Kernel seamlessly enables vision and document processing out-of-the-box by directly extending the underlying OpenAI toolset.

## Running the Example

```bash
# Enable multimodal and run
export AK_MULTIMODAL__ENABLED=true
export OPENAI_API_KEY="your-openai-api-key"
uv run python app.py
```

## Running the Integration Test

```bash
export OPENAI_API_KEY="your-openai-api-key"
uv run pytest openai_test.py -v -s
```


