# Agent Kernel running LangGraph Agents with OpenAI Guardrails configured

This package contains a demo of Agent Kernel running agents built with LangGraph
with [OpenAI Guardrails](https://pypi.org/project/openai-guardrails/) configured.
Users can interact with agents via the Agent Kernel CLI.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s 

## Guardrail Configuration

### 1. Create a Guardrails Configuration File

Create a JSON file with your guardrail rules. Visit [guardrails.openai.com](https://guardrails.openai.com/) for an
interactive configuration builder.

Example `guardrails_config.json`:

```json
{
  "input": [
    {
      "type": "Moderation",
      "enabled": true,
      "action": "block",
      "thresholds": {
        "harassment": 0.7,
        "hate": 0.7,
        "self-harm": 0.7,
        "sexual": 0.7,
        "violence": 0.7
      }
    },
    {
      "type": "Contains PII",
      "enabled": true,
      "action": "block",
      "entities": [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD"
      ]
    },
    {
      "type": "Jailbreak",
      "enabled": true,
      "action": "block"
    }
  ],
  "output": [
    {
      "type": "Moderation",
      "enabled": true,
      "action": "block",
      "thresholds": {
        "harassment": 0.7,
        "hate": 0.7,
        "self-harm": 0.7,
        "sexual": 0.7,
        "violence": 0.7
      }
    },
    {
      "type": "NSFW Text",
      "enabled": true,
      "action": "block"
    }
  ]
}
```

### 2. Update Your Agent Kernel Configuration

Add guardrail configuration to your `config.yaml`:

```yaml
guardrail:
  input:
    enabled: true
    type: openai
    config_path: /path/to/guardrails_config.json
  output:
    enabled: true
    type: openai
    config_path: /path/to/guardrails_config.json
```

## How It Works

### Input Guardrails (PreHook)

Input guardrails run **before** requests are sent to the agent:

1. Extract text from incoming requests
2. Validate against configured guardrails
3. If validation passes: Continue to agent
4. If guardrail triggers: Return error message without calling agent

### Output Guardrails (PostHook)

Output guardrails run **after** the agent generates a response:

1. Extract text from agent's reply
2. Validate against configured guardrails
3. If validation passes: Return original response
4. If guardrail triggers: Replace response with error message

## Available Guardrail Types

The OpenAI Guardrails library supports various built-in guardrails:

- **Moderation**: Content moderation using OpenAI's moderation API
- **URL Filter**: URL filtering with domain allowlist/blocklist
- **Contains PII**: Detects personally identifiable information
- **Hallucination Detection**: Detects hallucinated content using vector stores
- **Jailbreak**: Detects jailbreak attempts
- **NSFW Text**: Detects workplace-inappropriate content
- **Off Topic Prompts**: Ensures responses stay within scope
- **Custom Prompt Check**: Custom LLM-based guardrails

## Environment Variables

Make sure to set your OpenAI API key:

```bash
export OPENAI_API_KEY=your-api-key-here
```

The guardrails library uses OpenAI's APIs for validation, so API key is required.

## Examples

### Example 1: Block Inappropriate Content

**Input**: "How can I hack into someone's account?"

**Guardrail Triggered**: Jailbreak detection

**Response**: "Sorry, I cannot process this request. Guardrail triggered: Jailbreak attempt detected"

### Example 2: PII Detection

**Input**: "My email is john.doe@example.com and my phone is 555-1234"

**Guardrail Triggered**: Contains PII

**Response**: "Sorry, I cannot process this request. Guardrail triggered: PII detected"

### Example 3: Safe Request

**Input**: "What is the capital of France?"

**Guardrail**: Passes validation

**Response**: "The capital of France is Paris."

## Testing

The guardrails are covered by unit tests in `tests/test_guardrail.py`.

Run tests with:

```bash
pytest tests/test_guardrail.py -v
```

## Additional Resources

- [OpenAI Guardrails Documentation](https://openai.github.io/openai-guardrails-python/)
- [Interactive Configuration Builder](https://guardrails.openai.com/)
- [OpenAI Guardrails GitHub](https://github.com/openai/openai-guardrails-python)

## Troubleshooting

### Guardrails not triggering

1. Verify config file path is correct in `config.yaml`
2. Check that config file exists and is valid JSON
3. Ensure OpenAI API key is set
4. Check logs for warning/error messages

### Import errors

Make sure `openai-guardrails` dependency is installed via `agentkernel`:

```bash
pip install agentkernel[openai]
```

### Performance considerations

Guardrails add latency as they make additional API calls to OpenAI. Consider:

- Using guardrails selectively (only input or only output)
- Adjusting thresholds to balance safety vs. user experience
- Monitoring API usage and costs
