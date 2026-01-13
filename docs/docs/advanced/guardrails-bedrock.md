---
sidebar_position: 3.2
---

# AWS Bedrock Guardrails

AWS Bedrock Guardrails provide native integration with Amazon Bedrock's guardrails service for comprehensive content safety and compliance.

## Overview

AWS Bedrock Guardrails enable:

- **Content Filtering**: Block harmful or inappropriate content across multiple categories
- **PII Detection and Redaction**: Identify and redact 30+ types of sensitive information
- **Topic-based Blocking**: Control conversations based on denied topics
- **Word Filters**: Block profanity and custom word lists
- **Contextual Grounding**: Ensure responses are grounded in provided context (RAGAS)

## Installation

Install Agent Kernel with AWS support:

```bash
pip install agentkernel[aws]
```

This installs the required `boto3` library for AWS integration.

## Setup

### 1. Create a Bedrock Guardrail

Create a guardrail in AWS Bedrock using the AWS Console, CLI, or SDK.

**Using AWS Console:**
1. Navigate to Amazon Bedrock → Guardrails
2. Click "Create guardrail"
3. Configure content filters, denied topics, word filters, and PII filters
4. Note the Guardrail ID and create a version

**Using AWS CLI:**

```bash
aws bedrock create-guardrail \
    --name "MyAgentGuardrail" \
    --description "Guardrail for agent interactions" \
    --content-policy-config '{
        "filtersConfig": [
            {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "VIOLENCE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "SEXUAL", "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "MISCONDUCT", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
            {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"}
        ]
    }' \
    --sensitive-information-policy-config '{
        "piiEntitiesConfig": [
            {"type": "EMAIL", "action": "BLOCK"},
            {"type": "PHONE", "action": "BLOCK"},
            {"type": "SSN", "action": "BLOCK"},
            {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK"}
        ]
    }'
```

### 2. Configure AWS Credentials

Ensure your AWS credentials are configured:

```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1  # or your preferred region
```

Or use AWS CLI configuration:
```bash
aws configure
```

### 3. Update Agent Kernel Configuration

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
    version: "1"
```

**Configuration Options:**
- `enabled`: Enable/disable guardrails
- `type`: Set to `bedrock` for AWS Bedrock Guardrails
- `id`: Your Bedrock guardrail identifier (from AWS)
- `version`: Guardrail version number or "DRAFT"

## Available Guardrail Policies

### Content Filters

Block harmful content across six categories with configurable strength levels:

| Filter Type | Description | Strength Levels |
|-------------|-------------|-----------------|
| **HATE** | Hateful, demeaning, or derogatory content | NONE, LOW, MEDIUM, HIGH |
| **INSULTS** | Insulting, mocking, or offensive language | NONE, LOW, MEDIUM, HIGH |
| **SEXUAL** | Sexual content or references | NONE, LOW, MEDIUM, HIGH |
| **VIOLENCE** | Violent or graphic content | NONE, LOW, MEDIUM, HIGH |
| **MISCONDUCT** | Criminal activity or unethical behavior | NONE, LOW, MEDIUM, HIGH |
| **PROMPT_ATTACK** | Prompt injection or jailbreak attempts | NONE, LOW, MEDIUM, HIGH |

Configure separately for input and output with different strengths.

### Denied Topics

Define custom topics to block from conversations:
- Topic name and definition
- Example phrases that represent the topic
- Separate input/output blocking configuration

Example topics: Financial advice, Medical diagnosis, Legal counsel, etc.

### Word Filters

**Profanity Filter:**
- Managed list of profane words and phrases
- Block automatically without custom configuration

**Custom Words:**
- Define your own blocklist of words or phrases
- Case-insensitive matching

### Sensitive Information (PII) Filters

Detect and redact 30+ types of personally identifiable information:

| PII Type | Action Options |
|----------|----------------|
| EMAIL | BLOCK, ANONYMIZE |
| PHONE | BLOCK, ANONYMIZE |
| NAME | BLOCK, ANONYMIZE |
| SSN | BLOCK, ANONYMIZE |
| CREDIT_DEBIT_CARD_NUMBER | BLOCK, ANONYMIZE |
| ADDRESS | BLOCK, ANONYMIZE |
| USERNAME | BLOCK, ANONYMIZE |
| PASSWORD | BLOCK, ANONYMIZE |
| DRIVER_ID | BLOCK, ANONYMIZE |
| IP_ADDRESS | BLOCK, ANONYMIZE |
| MAC_ADDRESS | BLOCK, ANONYMIZE |
| US_PASSPORT_NUMBER | BLOCK, ANONYMIZE |
| US_BANK_ACCOUNT_NUMBER | BLOCK, ANONYMIZE |
| And 17+ more... | |

- **BLOCK**: Reject content containing PII
- **ANONYMIZE**: Redact/mask PII in content

### Contextual Grounding

Ensure responses are grounded in source information:
- Detect hallucinations
- Verify factual accuracy against provided context
- Configure grounding thresholds

## IAM Permissions

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

## How It Works

### Input Guardrails

1. User sends a request to the agent
2. Agent Kernel extracts text from the request
3. Text is sent to Bedrock `ApplyGuardrail` API with `source=INPUT`
4. If guardrail is triggered: Return safe error message
5. If validation passes: Continue to agent processing

### Output Guardrails

1. Agent generates a response
2. Agent Kernel extracts text from the response
3. Text is sent to Bedrock `ApplyGuardrail` API with `source=OUTPUT`
4. If guardrail is triggered: Replace response with safe message
5. If validation passes: Return original response to user

## Examples

### Example 1: Block Harmful Content

**Input**: "How can I hack into someone's account?"

**Guardrail Triggered**: MISCONDUCT or PROMPT_ATTACK filter

**Response**: 
```
I apologize, but I'm unable to process this request as it may violate 
content safety guidelines (MISCONDUCT). Please rephrase your question 
or try a different topic.
```

### Example 2: PII Detection

**Input**: "My email is john.doe@example.com and SSN is 123-45-6789"

**Guardrail Triggered**: PII filter (EMAIL, SSN)

**Response**: 
```
I apologize, but I'm unable to process this request as it may violate 
content safety guidelines. Please rephrase your question or try a 
different topic.
```

### Example 3: Safe Request

**Input**: "What is the capital of France?"

**Guardrail**: Passes all validations

**Response**: "The capital of France is Paris."

## Configuration Examples

### Basic Configuration

```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: abc123guardrailid
    version: "1"
```

### Separate Input/Output Guardrails

Use different guardrails for input and output:

```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: input-guardrail-id
    version: "2"
  output:
    enabled: true
    type: bedrock
    id: output-guardrail-id
    version: "1"
```

### Using DRAFT Version

During development, use DRAFT version:

```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: abc123guardrailid
    version: "DRAFT"
```

**Note**: DRAFT versions have higher latency than versioned guardrails.

## Best Practices

1. **Use Versioned Guardrails in Production**: Create versions for better performance
2. **Start with HIGH Strength**: Begin with strict filters, then adjust based on false positives
3. **Test Thoroughly**: Test with edge cases before production deployment
4. **Monitor Metrics**: Track latency, costs, and intervention rates
5. **Separate Configs**: Use different guardrails for input vs. output
6. **Regional Deployment**: Deploy guardrails in the same region as your application
7. **IAM Least Privilege**: Grant only required Bedrock permissions

## Troubleshooting

### Guardrails Not Triggering

1. Verify guardrail ID and version in `config.yaml`
2. Check guardrail exists in correct AWS region
3. Verify IAM permissions include `bedrock:ApplyGuardrail`
4. Check logs for error messages
5. Test guardrail directly using AWS CLI:
   ```bash
   aws bedrock-runtime apply-guardrail \
       --guardrail-identifier your-id \
       --guardrail-version 1 \
       --source INPUT \
       --content '[{"text":{"text":"test input"}}]'
   ```

### Import Errors

Ensure `boto3` is installed:
```bash
pip install agentkernel[aws]
```

### Authentication Errors

Check AWS credentials:
```bash
aws sts get-caller-identity
```

### Permission Denied

Verify IAM policy includes required actions:
- `bedrock:ApplyGuardrail`
- `bedrock:GetGuardrail`

## Performance & Cost

### Latency

- **Typical Latency**: 100-300ms per validation
- **DRAFT Version**: Higher latency than versioned guardrails
- **Regional Impact**: Same-region deployment reduces latency

### Cost

AWS Bedrock Guardrails pricing (as of 2026):
- Charged per text unit (1000 characters)
- Varies by region
- See [AWS Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/) for current rates

### Optimization

- Use versioned guardrails (not DRAFT) in production
- Deploy in same region as your application
- Consider caching for repeated validations
- Monitor usage with CloudWatch

## Related Resources

- [AWS Bedrock Guardrails Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS Bedrock API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock.html)
- [Boto3 Bedrock Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime.html)
- [OpenAI Guardrails](/docs/advanced/guardrails-openai) - Alternative provider
- [Guardrails Overview](/docs/advanced/guardrails)
- [Configuration Guide](/docs/core-concepts/configuration)
- [Working Example](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/guardrail/bedrock)

## Support

- **Issues**: [GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yaalalabs/agent-kernel/discussions)
- **Examples**: [Repository Examples](https://github.com/yaalalabs/agent-kernel/tree/main/examples)
