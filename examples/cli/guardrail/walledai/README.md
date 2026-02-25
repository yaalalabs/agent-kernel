
# Agent Kernel running LangGraph Agents with Walled AI Guardrails

This package contains a demo of Agent Kernel running agents built with LangGraph and [Walled AI Guardrails](https://walled.ai/) configured. Users can interact with agents via the Agent Kernel CLI.

## Installation

Install dependencies:

    ./build.sh

Install local dependencies in development mode:

    ./build.sh local

## Usage

Run the demo:

    python demo.py

## Guardrail Configuration

Walled AI guardrails are configured via environment variable:

```bash
export WALLED_API_KEY=your-walledai-api-key
```

No JSON config file is required. All PII redaction and safety checks are handled by the Walled AI API.

## How It Works

### Input Guardrails (PreHook)

Input guardrails run **before** requests are sent to the agent:

1. Extract text from incoming requests
2. Call Walled AI to check safety and redact PII
3. Store PII mapping in session
4. If unsafe or PII detected, return masked/error response
5. If validation passes, continue to agent

### Output Guardrails (PostHook)

Output guardrails run **after** the agent generates a response:

1. Extract text from agent's reply
2. Use session mapping to unmask PII placeholders
3. Return unmasked response to user

## Example Scenarios

### Example 1: Block Unsafe Content

**Input**: "How can I hack into someone's account?"

**Guardrail Triggered**: Safety check (unsafe content)

**Response**: "I cannot fulfill this request as it violates safety guidelines."

### Example 2: PII Redaction

**Input**: "My email is john.doe@example.com and my phone is 555-1234"

**Guardrail Triggered**: PII redaction

**Response**: "My email is <PII_EMAIL_ADDRESS> and my phone is <PII_PHONE_NUMBER>"

### Example 3: Safe Request

**Input**: "What is the capital of France?"

**Guardrail**: Passes validation

**Response**: "The capital of France is Paris."


## Troubleshooting

1. Verify config file path is correct in `config.yaml`
2. Check that config file exists and is valid JSON
3. Ensure WalledAI API key is set
4. Check logs for warning/error messages

## Testing

Guardrails are covered by unit tests in `tests/test_guardrail.py`.

Run tests with:

```bash
pytest tests/test_guardrail.py -v
```


## Additional Resources

- [Walled AI Documentation](https://walled.ai/)
- [Agent Kernel Documentation](../../../../docs/README.md)

