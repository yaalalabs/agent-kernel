# Agent Kernel running LangGraph Agents with AWS Bedrock Guardrails configured

This package contains a demo of Agent Kernel running agents built with LangGraph
with [AWS Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html) configured.
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

### 1. Create a Bedrock Guardrail

Create a guardrail in AWS Bedrock using the AWS Console, CLI, or SDK. You'll need:

- **Guardrail ID**: The unique identifier for your guardrail
- **Guardrail Version**: The version number or "DRAFT"

You can configure various policies in Bedrock Guardrails:

- **Content Filters**: Block harmful content (hate, insults, sexual, violence, misconduct, prompt attacks)
- **Denied Topics**: Define topics to block
- **Word Filters**: Block specific words or phrases (profanity, custom words)
- **PII Filters**: Detect and redact sensitive information (SSN, email, phone, etc.)
- **Contextual Grounding**: Ensure responses are grounded in provided context

Example using AWS CLI to create a guardrail:

```bash
aws bedrock create-guardrail \
    --name "MyAgentGuardrail" \
    --description "Guardrail for agent interactions" \
    --content-policy-config '{
        "filtersConfig": [
            {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "VIOLENCE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "SEXUAL", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "MISCONDUCT", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"}
        ]
    }' \
    --sensitive-information-policy-config '{
        "piiEntitiesConfig": [
            {"type": "EMAIL", "action": "BLOCK"},
            {"type": "PHONE", "action": "BLOCK"},
            {"type": "SSN", "action": "BLOCK"}
        ]
    }'
```

### 2. Update Your Agent Kernel Configuration

Add guardrail configuration to your `config.yaml`:

```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"  # or "DRAFT"
  output:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"  # or "DRAFT"
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

AWS Bedrock Guardrails support various built-in policy types:

### Content Filters
- **HATE**: Hateful content including demeaning or derogatory language
- **INSULTS**: Insulting, mocking, or offensive language
- **SEXUAL**: Sexual content or references
- **VIOLENCE**: Violent or graphic content
- **MISCONDUCT**: Criminal activity or unethical behavior
- **PROMPT_ATTACK**: Prompt injection or jailbreak attempts

Each filter can be configured with different strength levels: NONE, LOW, MEDIUM, HIGH

### Denied Topics
Define custom topics that should be blocked from conversations. Each topic includes:
- Topic name and definition
- Example phrases that represent the topic
- Separate configuration for input and output blocking

### Word Filters
- **Profanity Filter**: Block profane language (managed list)
- **Custom Words**: Block specific words or phrases you define

### Sensitive Information (PII) Filters
Detect and redact personally identifiable information:
- **EMAIL**: Email addresses
- **PHONE**: Phone numbers
- **NAME**: Person names
- **SSN**: Social Security Numbers
- **CREDIT_DEBIT_CARD_NUMBER**: Credit/debit card numbers
- **ADDRESS**: Physical addresses
- **USERNAME**: Usernames
- **PASSWORD**: Passwords
- **DRIVER_ID**: Driver's license numbers
- And many more...

Actions: BLOCK (reject content) or ANONYMIZE (redact/mask)

### Contextual Grounding
Ensure responses are grounded in source information and don't contain hallucinations.

## Environment Variables

Make sure to configure your AWS credentials:

```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1  # or your preferred region
```

Alternatively, use AWS CLI configuration or IAM roles for EC2/ECS.

## Examples

### Example 1: Block Inappropriate Content

**Input**: "How can I hack into someone's account?"

**Guardrail Triggered**: MISCONDUCT or PROMPT_ATTACK content filter

**Response**: "I apologize, but I'm unable to process this request as it may violate content safety guidelines. Please rephrase your question or try a different topic."

### Example 2: PII Detection

**Input**: "My email is john.doe@example.com and my phone is 555-1234"

**Guardrail Triggered**: PII filter (EMAIL, PHONE)

**Response**: "I apologize, but I'm unable to process this request as it may violate content safety guidelines. Please rephrase your question or try a different topic."

### Example 3: Safe Request

**Input**: "What is the capital of France?"

**Guardrail**: Passes validation

**Response**: "The capital of France is Paris."

## Testing

The guardrails are covered by unit tests in `demo_test.py`.

Run tests with:

```bash
uv run pytest -s
```

## Additional Resources

- [AWS Bedrock Guardrails Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS Bedrock Guardrails API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock.html)
- [AWS Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [Boto3 Bedrock Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime.html)

## Troubleshooting

### Guardrails not triggering

1. Verify guardrail ID and version are correct in `config.yaml`
2. Check that the guardrail exists in your AWS account and region
3. Ensure AWS credentials are properly configured
4. Verify IAM permissions include `bedrock:ApplyGuardrail`
5. Check logs for warning/error messages

### Import errors

Make sure `boto3` dependency is installed via `agentkernel`:

```bash
pip install agentkernel[aws]
```

### AWS Permissions

Your IAM role/user needs the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:ApplyGuardrail",
        "bedrock:GetGuardrail"
      ],
      "Resource": "arn:aws:bedrock:*:*:guardrail/*"
    }
  ]
}
```

### Performance considerations

Bedrock Guardrails add latency as they make API calls to AWS. Consider:

- Using guardrails selectively (only input or only output)
- Adjusting filter strengths to balance safety vs. user experience
- Monitoring API usage and costs
- Using guardrail versions instead of DRAFT for production (better performance)
