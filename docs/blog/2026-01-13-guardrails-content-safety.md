---
slug: /guardrails-content-safety
title: "Safe AI at Scale: Introducing Guardrails for Agent Kernel"
authors: [yaala]
tags: [agent-kernel, guardrails, content-safety, openai-guardrails, aws-bedrock, security, compliance, pii, moderation]
image: /img/card.png
---

# Safe AI at Scale: Introducing Guardrails for Agent Kernel

Deploying AI agents in production comes with critical business risks: brand damage from inappropriate responses, regulatory penalties from data leaks, and customer trust erosion from security breaches. Today, we're announcing **Guardrails** for Agent Kernel - enterprise-grade content safety that protects your business while accelerating your AI initiatives.

<!-- truncate -->

## The Business Case for AI Guardrails

**Your AI agents are powerful. But are they safe for your business?**

Every unguarded AI interaction is a potential liability:

### 💰 **Financial Risk**
- **Data breach penalties**: GDPR fines up to €20M or 4% of global revenue
- **HIPAA violations**: Up to $1.5M per year for healthcare data exposure
- **PCI DSS non-compliance**: Fines, increased processing fees, and contract termination
- **Legal costs**: Class-action lawsuits from PII leakage

### 🎯 **Brand & Reputation Risk**
- **Inappropriate content**: One viral screenshot of your AI saying something offensive can tank customer trust
- **Off-brand responses**: Inconsistent messaging damages brand equity
- **Customer service failures**: Frustrated users share negative experiences publicly
- **Competitive disadvantage**: Customers choose competitors with safer AI

### ⚖️ **Compliance & Regulatory Risk**
- **Industry regulations**: Healthcare (HIPAA), finance (PCI DSS), insurance (state regulations)
- **Privacy laws**: GDPR, CCPA, PIPEDA, and emerging global privacy frameworks
- **Sector-specific**: Legal advice restrictions, financial guidance disclaimers
- **Audit failures**: Non-compliant AI systems block certifications and partnerships

## The Solution: Guardrails That Work for Business

Agent Kernel's guardrails deliver **measurable business value**:

✅ **Reduce legal exposure** - Automatic PII detection prevents data leaks before they happen  
✅ **Accelerate compliance** - Pre-built policies for HIPAA, PCI DSS, and GDPR requirements  
✅ **Protect brand reputation** - Block harmful content before customers see it  
✅ **Enable faster deployment** - Pre-configured safety layers reduce time-to-market  
✅ **Lower operational costs** - Automated content filtering reduces manual review overhead  

## Two Enterprise-Grade Options

Choose the right guardrail provider for your business needs:

### 🛡️ **OpenAI Guardrails** - Fast Time-to-Value
Perfect for startups and mid-market companies needing rapid deployment:
- Quick setup with API key authentication
- Flexible policies you can adjust without vendor dependencies
- Works across any cloud or on-premise infrastructure
- Cost-effective for variable workloads

**Best for:** SaaS companies, cross-cloud deployments, rapid MVP launches

### 🔒 **AWS Bedrock Guardrails** - Enterprise Control
Ideal for large enterprises with AWS infrastructure:
- 30+ PII types including medical records and financial data
- Native AWS integration with IAM, CloudWatch, and audit trails
- Granular control through AWS Console
- Enterprise SLAs and support

**Best for:** Healthcare, financial services, regulated industries, AWS-native stacks

## Real Business Impact

### 💼 Customer Support: Protect Your Customers
**Challenge:** Support chatbot could leak customer phone numbers or credit card details  
**Solution:** Output guardrails detect and block PII before reaching users  
**Result:** Zero data breach incidents, maintained customer trust, avoided GDPR fines

### 🏥 Healthcare: HIPAA Compliance Made Simple
**Challenge:** Patient assistant must never leak protected health information  
**Solution:** AWS Bedrock guardrails with comprehensive PHI detection  
**Result:** Passed HIPAA audit, enabled telemedicine expansion, protected patient privacy

### 🏦 Financial Services: Regulatory Peace of Mind
**Challenge:** Banking assistant can't provide unauthorized financial advice  
**Solution:** Topic filters block investment and legal guidance  
**Result:** Met compliance requirements, accelerated product launch, avoided regulatory scrutiny

---

## For Developers: Technical Deep Dive

**👨‍💻 The following sections are for technical teams implementing guardrails.**

If you're a developer, architect, or DevOps engineer, read on for implementation details, code examples, and integration patterns. Business stakeholders have all the information they need above to understand the value proposition.

---

## Why Guardrails Matter (Technical Perspective)

AI agents are incredibly powerful, but without proper safeguards, they can:

- **Generate harmful or inappropriate content** that damages your brand
- **Leak sensitive information (PII)** like credit cards, SSNs, or health records
- **Fall victim to jailbreak attempts** that bypass safety instructions
- **Produce off-topic responses** that confuse or frustrate users
- **Violate compliance requirements** in regulated industries

Guardrails act as protective layers around your agents, validating content before it reaches your agent (input guardrails) and before responses reach your users (output guardrails). Think of them as security checkpoints that ensure every interaction meets your safety and policy requirements.

## Technical Implementation: Two Powerful Options

Agent Kernel supports two industry-leading guardrail providers, each with unique technical strengths:

### 🛡️ OpenAI Guardrails

OpenAI's guardrails provide sophisticated content moderation with customizable policies:

- **Content Filtering**: Block violent, sexual, hateful, or self-harm content
- **Prompt Injection Detection**: Identify jailbreak attempts and prompt manipulation
- **PII Detection**: Catch sensitive data like emails, phone numbers, SSNs
- **Custom Keywords**: Create domain-specific blocklists
- **Flexible Scoring**: Fine-tune sensitivity thresholds per policy

**Perfect for:**
- Customer-facing chatbots requiring brand safety
- Applications handling user-generated content
- Teams already using OpenAI infrastructure
- Rapid prototyping with quick policy setup

**Quick Setup:**

```bash
pip install agentkernel[openai]
```

```yaml
guardrail:
  input:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: guardrails_input.json
  output:
    enabled: true
    type: openai
    config_path: guardrails_output.json
```

### 🔒 AWS Bedrock Guardrails

Amazon Bedrock provides enterprise-grade content filtering integrated with AWS services:

- **Content Filters**: Violence, sexual content, hate speech, insults, and more
- **30+ PII Types**: Comprehensive detection including passports, medical records, financial data
- **Topic Filters**: Block entire conversation topics (investments, legal advice, etc.)
- **Word Filters**: Profanity and custom word blocking
- **Contextual Grounding**: Ensure responses stay grounded in provided context (coming soon)
- **AWS Integration**: Native IAM roles, CloudWatch logging, compliance controls

**Perfect for:**
- Enterprise deployments requiring AWS compliance
- Applications processing sensitive data
- Teams leveraging AWS infrastructure
- Scenarios needing detailed PII detection (healthcare, finance, legal)

**Quick Setup:**

```bash
pip install agentkernel[aws]
```

```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"
  output:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"
```

## How It Works: Input and Output Protection

Guardrails integrate seamlessly into Agent Kernel's execution pipeline through our hooks system:

### Input Guardrails: Validate Before Processing

Input guardrails intercept user requests **before** they reach your agent:

```python
from agentkernel.guardrail import InputGuardrailFactory
from agentkernel.core import PreHook

class SafetyCheckHook(PreHook):
    def __init__(self):
        self.guardrail = InputGuardrailFactory.get(
            provider="openai",
            config_path="guardrails_config.yaml"
        )
    
    async def on_run(self, session, agent, requests):
        # Validate input - blocks harmful content automatically
        return await self.guardrail.on_run(session, agent, requests)
```

If a violation is detected, the guardrail blocks the request and returns a safe error message - your agent never sees the harmful input.

### Output Guardrails: Validate Before Delivery

Output guardrails validate agent responses **after** generation but **before** reaching users:

```python
from agentkernel.guardrail import OutputGuardrailFactory
from agentkernel.core import PostHook

class OutputSafetyHook(PostHook):
    def __init__(self):
        self.guardrail = OutputGuardrailFactory.get(
            provider="bedrock",
            guardrail_id="abc123xyz",
            guardrail_version="1"
        )
    
    async def on_run(self, session, agent, requests, reply):
        # Validate output - blocks unsafe responses
        return await self.guardrail.on_run(session, agent, requests, reply)
```

If the response contains PII, inappropriate content, or violates policies, the guardrail intercepts it and returns a filtered or replacement message.

## The Power of Pluggable Architecture

Here's where Agent Kernel truly shines: **our clean, pluggable architecture makes guardrails extensible**.

Both OpenAI and AWS Bedrock guardrails are implemented using the same base interface. This means:

### 🎯 Easy Provider Switching

Switch providers with a single configuration change - no code changes needed:

```yaml
# Switch from OpenAI to Bedrock
guardrail:
  input:
    enabled: true
    type: bedrock  # was: openai
    id: your-guardrail-id
    version: "1"
  output:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"
```

### 🔌 Community Contributions Welcome

Want to add support for a new guardrail provider? Our architecture makes it straightforward:

1. Create a new provider module (e.g., `custom_guardrail.py`)
2. Extend `InputGuardrail` class for input validation and `OutputGuardrail` class for output validation
3. Implement your provider-specific validation logic in the `on_run()` method
4. Register your provider in `InputGuardrailFactory` and `OutputGuardrailFactory`

Example structure:

```python
from agentkernel.guardrail import InputGuardrail, OutputGuardrail
from agentkernel.core.base import Agent, Session
from agentkernel.core.model import AgentReply, AgentRequest

class MyProviderInputGuardrail(InputGuardrail):
    async def on_run(self, session: Session, agent: Agent, 
                     requests: list[AgentRequest]) -> list[AgentRequest] | AgentReply:
        # Your validation logic here
        return requests  # or return AgentReply to block

class MyProviderOutputGuardrail(OutputGuardrail):
    async def on_run(self, session: Session, requests: list[AgentRequest],
                     agent: Agent, agent_reply: AgentReply) -> AgentReply:
        # Your validation logic here
        return agent_reply
```

**The community can add new guardrail options easily** - whether it's commercial providers, open-source tools, or custom in-house solutions. The clean separation between guardrail logic and Agent Kernel's execution framework means contributions are simple and maintainable.

### 📦 Framework-Agnostic

Because guardrails are implemented as hooks, they work across **all** supported frameworks:
- OpenAI Agents SDK ✅
- LangGraph ✅
- CrewAI ✅
- Google ADK ✅

Write your guardrail configuration once, use it everywhere.

## Choosing the Right Provider

Both providers offer robust content safety, but they excel in different scenarios:

| Feature | OpenAI Guardrails | AWS Bedrock |
|---------|------------------|-------------|
| **Prompt Injection Detection** | ✅ Advanced | ⚠️ Basic |
| **PII Types** | 12+ common types | 30+ comprehensive |
| **Custom Policies** | ✅ Flexible YAML | ✅ AWS Console |
| **Deployment** | Any cloud/on-prem | AWS only |
| **Setup Complexity** | Simple API key | AWS IAM + Guardrail ID |
| **Cost Model** | Per API call | Per text unit |
| **Best For** | Rapid prototyping, cross-cloud | Enterprise AWS, healthcare/finance |

**Pro Tip:** Many teams start with OpenAI Guardrails for development and switch to Bedrock for production AWS deployments. Agent Kernel's pluggable design makes this migration seamless.

## Coming Soon: Exciting Additions

We're not stopping here. The guardrails roadmap includes:

### 🧱 Walled.ai Integration

[Walled.ai](https://walled.ai) provides specialized prompt injection and jailbreak detection. We're working on native support to give you even more options for protecting against adversarial inputs.

### 🎭 PII Masking Feature

Beyond detection, we're building **automatic PII masking** that will:
- Detect sensitive data in real-time
- Replace PII with synthetic equivalents or redaction markers
- Preserve context while removing identifiable information
- Support custom masking rules per data type

This will be especially valuable for:
- Call center agents processing customer data
- Healthcare applications handling PHI
- Financial services managing payment information
- Any application needing GDPR/CCPA compliance

Stay tuned for announcements as these features roll out!

## Real-World Use Cases

### Customer Support Bot

```yaml
# Protect customer conversations
guardrail:
  input:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: guardrails_input.json
  output:
    enabled: true
    type: bedrock
    id: pii-filter-guardrail
    version: "1"
```

**Result:** Block abusive customer inputs, prevent agent from leaking PII in responses

### Healthcare Assistant

```yaml
# HIPAA-compliant patient interactions
guardrail:
  input:
    enabled: true
    type: bedrock
    id: hipaa-input-guardrail
    version: "2"
  output:
    enabled: true
    type: bedrock
    id: hipaa-output-guardrail
    version: "2"
```

**Result:** Comprehensive PHI detection, compliance audit trails, AWS security controls

### Enterprise Knowledge Base

```yaml
# Prevent data leakage in company chatbot
guardrail:
  output:
    enabled: true
    type: openai
    config_path: guardrails_output.json
```

**Result:** Block accidental disclosure of proprietary information, filter sensitive company data

## Get Started with Guardrails Today

### 1. Choose Your Provider

**OpenAI Guardrails:**
```bash
pip install agentkernel[openai-guardrails]
export OPENAI_API_KEY=your-key
```

**AWS Bedrock:**
```bash
pip install agentkernel[bedrock]
aws configure  # Set up AWS credentials
```

### 2. Configure Your Policies

Create `config.yaml` with your guardrail settings:

```yaml
guardrail:
  input:
    enabled: true
    type: openai  # or bedrock
    model: gpt-4o-mini  # for OpenAI
    config_path: guardrails_input.json
    # For Bedrock, use: id: your-id and version: "1" instead
  output:
    enabled: true
    type: openai
    config_path: guardrails_output.json
```

### 3. Deploy with Confidence

Your agents now have enterprise-grade content safety:
- Automatic input validation
- Output filtering and PII detection
- Compliance-ready audit trails
- Framework-agnostic protection

## Documentation and Examples

We've created comprehensive guides to get you started:

- **[Guardrails Overview](/docs/advanced/guardrails)** - Architecture and concepts
- **[OpenAI Guardrails Guide](/docs/advanced/guardrails-openai)** - Complete setup and configuration
- **[AWS Bedrock Guide](/docs/advanced/guardrails-bedrock)** - IAM setup, policies, and best practices
- **[Working Examples](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/guardrail)** - Copy-paste ready code

## Join the Community

Guardrails are just the beginning. With Agent Kernel's pluggable architecture, we're building an ecosystem where the community can contribute new providers, safety mechanisms, and integrations.

**Want to contribute?**
- Add support for new guardrail providers
- Share your custom safety hooks
- Improve documentation and examples
- Request features and vote on priorities

**Connect with us:**
- **GitHub:** [yaalalabs/agent-kernel](https://github.com/yaalalabs/agent-kernel)
- **Discord:** [Join our community](https://discord.gg/snrPzb46uu)
- **Issues:** [Report bugs or suggest features](https://github.com/yaalalabs/agent-kernel/issues)
- **Discussions:** [Ask questions and share ideas](https://github.com/yaalalabs/agent-kernel/discussions)

## The Future is Safe AI

As AI agents become more powerful and widespread, content safety isn't optional - it's essential. Agent Kernel's guardrails give you:

✅ **Multi-provider flexibility** - Choose the best tool for each use case  
✅ **Pluggable architecture** - Easy to extend and contribute  
✅ **Framework-agnostic** - Works with any agent framework  
✅ **Production-ready** - Enterprise-grade safety and compliance  
✅ **Community-driven** - Built for extensibility and collaboration  

Deploy your agents with confidence, knowing they're protected by best-in-class content safety guardrails.

Ready to build safer AI? [Get started with guardrails today →](/docs/advanced/guardrails)

---

**Built with ❤️ by [Yaala Labs](https://www.yaalalabs.com/)**

*Have questions about guardrails? Join our [Discord community](https://discord.gg/snrPzb46uu) or open an [issue on GitHub](https://github.com/yaalalabs/agent-kernel/issues).*
