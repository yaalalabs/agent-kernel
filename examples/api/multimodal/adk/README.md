# Multimodal Example — Google ADK

Demonstrates Agent Kernel's multimodal (image/file) support using a Google Agent Development Kit (ADK) agent.

Agent Kernel seamlessly binds to ADK, automatically injecting system tools like `analyze_attachments` to enable vision and document processing without any manual tool configurations.

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
uv run pytest adk_test.py -v -s
```


