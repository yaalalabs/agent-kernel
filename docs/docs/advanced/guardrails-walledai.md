---
sidebar_position: 4
---

# Walled AI Guardrails

Walled AI guardrails provide safety validation and PII redaction for Agent Kernel interactions. This integration validates user inputs, masks sensitive values before agent execution, and restores placeholders in output responses.

## What Walled AI Guardrails Provide

- Input safety validation using Walled AI Protect
- Input PII redaction using Walled AI Redact
- Output unmasking using session-stored placeholder mappings
- Provider-level integration without JSON guardrail rule files

## Prerequisites

Install Agent Kernel with Walled AI extras:

```bash
pip install agentkernel[walledai]
```

Set required environment variables:

```bash
export WALLED_API_KEY=your-walledai-api-key
export AK_DEBUG=true
```

## Configuration

Configure Walled AI in your `config.yaml`:

```yaml
guardrail:
  input:
    enabled: true
    type: walledai
    pii: true
  output:
    enabled: true
    type: walledai
    pii: true
```

Equivalent environment-variable configuration:

```bash
export AK_GUARDRAIL__INPUT__ENABLED=true
export AK_GUARDRAIL__INPUT__TYPE=walledai
export AK_GUARDRAIL__INPUT__PII=true
export AK_GUARDRAIL__OUTPUT__ENABLED=true
export AK_GUARDRAIL__OUTPUT__TYPE=walledai
export AK_GUARDRAIL__OUTPUT__PII=true

# Optional: disable WalledAI PII redaction/unmasking while keeping safety checks
# export AK_GUARDRAIL__INPUT__PII=false
# export AK_GUARDRAIL__OUTPUT__PII=false
```

## How It Works

### Input Guardrails

1. Iterate incoming request objects
2. For each text request, validate text with Walled AI Protect (safety)
3. For each text request, redact sensitive entities with Walled AI Redact
4. Preserve non-text requests unchanged (for example file/image inputs)
5. Store placeholder mapping in session cache
6. Forward masked text requests to the agent

If safety validation fails, Agent Kernel returns a safe refusal response.

### Output Guardrails

1. Extract outgoing agent text
2. Load stored placeholder mapping from session state
3. Replace placeholders with original values
4. Return unmasked response

## Session Mapping Behavior

Walled AI redaction placeholders are persisted in session cache to support follow-up turns and restart-tolerant flows when durable session storage is enabled.

Recommended controls for production:

- Minimize retained mapping scope
- Apply retention/TTL policies
- Restrict storage access
- Encrypt data at rest

## Optional: Local WalledGuard-Edge Moderation

If you want to run local moderation experiments, you can use `walledai/walledguard-edge` from Hugging Face.

According to Walled AI's announcement, WalledGuard-Edge is a 0.6B open-source model (Apache-2.0) positioned as stronger than LlamaGuard3 (1B) across multilingual and multiple jailbreak categories.

- API access and product updates: [www.walled.ai](https://www.walled.ai/)


### Manual setup

For local inference steps and the latest runnable example code, follow the model card:

- Hugging Face model page: [walledai/walledguard-edge](https://huggingface.co/walledai/walledguard-edge)

Typical local dependencies include `torch` and `transformers`.

This local flow is optional and separate from the default Agent Kernel Walled AI API integration.

## Example

Input:

```text
my name is john
```

Masked request sent to agent:

```text
my name is [Person_1]
```

When the reply contains `[Person_1]`, output guardrail restores it to `john` before returning response.

## Troubleshooting

### Guardrails not triggering

1. Ensure input/output guardrails are enabled in config
2. Verify `type: walledai` for both input and output
3. Confirm `WALLED_API_KEY` is set in the runtime environment
4. Enable debug logs with `AK_DEBUG=true`

### Missing API key or provider errors

Verify the shell environment used to start the runtime includes:

```bash
export WALLED_API_KEY=your-walledai-api-key
```

### Unexpected masked placeholders in response

- Ensure output guardrails are enabled
- Ensure session ID is stable across turns
- Verify session storage mode and persistence expectations

## Related Resources

- [Walled AI Documentation](https://walled.ai/)
- [Guardrails Overview](./guardrails)
- [Configuration Guide](../core-concepts/configuration)
- [Working Example](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/guardrail/walledai)
