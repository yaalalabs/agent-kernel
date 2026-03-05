# Agent Kernel running LangGraph Agents with Walled AI Guardrails configured

This package contains a demo of Agent Kernel running agents built with LangGraph
with [Walled AI](https://walled.ai/) guardrails configured.
Users can interact with agents via the Agent Kernel CLI.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using:

    python demo.py

To run tests:

    pytest demo_test.py -v

## Guardrail Configuration

### 1. Update Agent Kernel Configuration

Set guardrail type to `walledai` in `config.yaml`:

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

### 2. Set Environment Variables

```bash
export WALLED_API_KEY=your-walledai-api-key
export OPENAI_API_KEY=your-openai-api-key
export AK_DEBUG=true
```

- `WALLED_API_KEY` is used by Walled AI safety and redaction clients.
- `OPENAI_API_KEY` is required by the LangGraph demo model (`ChatOpenAI`).
- `AK_DEBUG=true` enables Walled AI guardrail debug logging.
- `pii` controls PII masking/unmasking for Walled AI (`true` by default).

## How It Works

### Input Guardrails (PreHook)

Input guardrails run **before** requests are sent to the agent:

1. Extract text from incoming requests
2. Call Walled AI Protect API for safety validation
3. Call Walled AI Redact API to mask sensitive values
4. Persist placeholder-to-original mapping in session non-volatile cache
5. Forward masked text to the agent

If safety validation fails, the request is blocked with:

"I cannot fulfill this request as it violates safety guidelines."

### Output Guardrails (PostHook)

Output guardrails run **after** the agent generates a response:

1. Extract text from the agent reply
2. Load stored mapping from session state
3. Replace placeholders with original values
4. Return the unmasked response

## Examples

### Example 1: Block Unsafe Content

**Input**: "How can I hack into someone's account?"

**Guardrail Triggered**: Safety check

**Response**: "I cannot fulfill this request as it violates safety guidelines."

### Example 2: PII Redaction and Unmasking

**Input**: "my name is john"

**Redacted Request to Agent**: "my name is [Person_1]"

**Reply Unmasking**: placeholders in the reply are converted back using session mapping.

### Example 3: Safe Request

**Input**: "What is the capital of France?"

**Guardrail**: Passes safety/redaction checks

**Response**: Normal agent response

## Testing

This example includes integration and guardrail tests in `demo_test.py`.

Run tests with:

```bash
pytest demo_test.py -v
```

## Optional: Local WalledGuard-Edge

If you want to test local moderation behavior manually, you can run `walledai/walledguard-edge` directly from Hugging Face.

According to Walled AI's announcement, WalledGuard-Edge is a 0.6B open-source model (Apache-2.0) and is positioned to outperform LlamaGuard3 (1B) on multilingual and jailbreak scenarios.

- API access and product updates: [www.walled.ai](https://www.walled.ai/)
- Hugging Face model page (includes latest usage example): [walledai/walledguard-edge](https://huggingface.co/walledai/walledguard-edge)

Typical local dependencies include `torch` and `transformers`.

This local model usage is optional and separate from the default Walled AI API path used in this demo.

## Troubleshooting

### Guardrails not triggering

1. Ensure `guardrail.input.type` and `guardrail.output.type` are set to `walledai`
2. Ensure `WALLED_API_KEY` is set in your shell
3. If PII masking is expected, verify `guardrail.input.pii: true`
4. If output restoration is expected, verify `guardrail.output.pii: true`
5. Verify network access to Walled AI APIs
6. Set `AK_DEBUG=true` and review CLI logs

### Missing API key errors

Set required environment variables before running:

```bash
export WALLED_API_KEY=your-walledai-api-key
export OPENAI_API_KEY=your-openai-api-key
```

## Additional Resources

- [Walled AI Documentation](https://walled.ai/)
- [Agent Kernel Documentation](https://github.com/yaalalabs/agent-kernel/blob/develop/ak-py/README.md)

