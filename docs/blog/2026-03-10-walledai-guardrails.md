---
slug: /walledai-guardrails
title: "Walled AI Guardrails in Practice"
authors: [yaala]
tags: [agent-kernel, guardrails, walledai, pii, safety, privacy, production]
image: /img/card.png
---

# Walled AI Guardrails in Practice

Walled AI gives us a clean, practical safety + PII masking pipeline for agent input/output flows. It is easy to integrate, fast to test, and useful for production guardrail baselines.

But like every real provider integration, there are edge cases.

This post covers the capabilities that made Walled AI a good fit for Agent Kernel, the real-world edge cases we encountered, and the implementation choices we made to keep behavior safe and predictable.

<!-- truncate -->

## Why We Chose Walled AI

For Agent Kernel, we needed guardrails that could do two things quickly:

1. Block unsafe input before an LLM call.
2. Mask sensitive PII before the prompt reaches the model.

Walled AI gives both via:

- `Protect` for safety checks.
- `Redact` for masking sensitive values.

That made it a strong fit for a provider-level guardrail option in our framework.

## What Walled AI Does Well

Before discussing edge cases, it is important to highlight the strengths that made this integration practical:

- Fast safety checks that can block unsafe prompts before they hit an LLM.
- Built-in PII masking flow with reversible placeholders for controlled unmasking.
- Simple API surface (`Protect` + `Redact`) that is easy to operationalize.
- Good fit for runtime guardrail layering in agent systems.
- Optional local-model experimentation path for moderation workflows.

For many teams, this baseline is enough to ship a strong first guardrail layer quickly.

## How the Flow Works in Agent Kernel

At a high level:

1. Each incoming text request is checked with `Protect`.
2. If safe, the same text is sent to `Redact`.
3. Masked text is forwarded to the agent.
4. Placeholder mapping is stored in session cache.
5. On output, placeholders are restored before replying to the user.

We intentionally process requests individually and preserve non-text request objects (files/images/other) without suppressing them.

## Local Model Support (WalledGuard-Edge)

Walled AI also supports a local moderation path through `walledai/walledguard-edge` (Hugging Face), which is useful for:

- Offline experimentation.
- Cost/performance prototyping.
- Evaluating moderation behavior before wiring into hosted pipelines.

In Agent Kernel, this local path is treated as an optional complement to the default API-driven Walled AI guardrail integration.

This gives teams flexibility:

- Hosted path for managed production guardrails.
- Local path for controlled testing and evaluation.

Reference links:

- API access and product updates: [www.walled.ai](https://www.walled.ai/)
- Hugging Face model page: [walledai/walledguard-edge](https://huggingface.co/walledai/walledguard-edge)

## Issue 1: Very Short Inputs and `INPUT_SHORT`

A common real-world chat pattern is very short messages:

- "hi"
- "ok"
- "23"

For short inputs, redaction can return `INPUT_SHORT`. This is not an unsafe-content signal; it means the redaction operation is not applicable to that payload.

### What we do

- For `INPUT_SHORT`, we bypass redaction for that request and continue.
- For other redaction errors, we return a safe fallback response instead of crashing runtime execution.

This keeps the system resilient and avoids full-request failures due to provider-side redaction limitations.

## Issue 2: Placeholder Numbering Is Local Per Call (No Cross-Call Memory)

A subtle but important behavior:

- Call A: "my name is john" -> `my name is [Person_1]`
- Call B: "my brother is james" -> `my brother is [Person_1]`

Both calls can produce `[Person_1]` for different people because numbering is local to each redaction call.

That means teams must not assume placeholder IDs are globally stable across turns unless they add their own session strategy.

### Why this matters

If you naively merge mappings across turns, later turns can overwrite earlier values for the same placeholder key.

### What we do

- Maintain mapping at session level for output restoration.
- Design guardrail handling to avoid destructive behavior in mixed-content and multi-turn flows.
- Keep this behavior documented so teams do not over-assume provider memory semantics.

## Issue 3: Limited Field-Level PII Customization

A frequent product request is selective masking, for example:

- Mask only bank CVV.
- Keep account number visible (or partially visible).

With provider-level PII redaction, fine-grained "mask this exact entity but not that one" controls may be limited depending on SDK/API capabilities and policy surface.

### Practical implication

If you need domain-specific masking rules (for example, payment workflows, healthcare identifiers, or country-specific formats), you may need an additional policy layer before/after provider redaction.

## Issue 4: Tracing Context Can Be Lost If Reply Metadata Is Not Preserved

When unmasking output, if you construct a fresh response object and forget to preserve `prompt`, tracing tools lose input-output linkage.

### What we do

When returning unmasked `AgentReplyText`, preserve prompt context from the original reply to keep observability and downstream tooling intact.

## What We Improved in Agent Kernel

Based on integration feedback and code reviews, we implemented these hardening changes:

- Per-request text processing for safety + redaction.
- Pass-through for non-text request types.
- Graceful fallback response on non-`INPUT_SHORT` redaction failures.
- Prompt preservation on unmasked output replies.


## Recommendations for Teams Using Walled AI

If you are integrating Walled AI into your own framework/runtime:

1. Treat placeholders as call-scoped unless you explicitly design session behavior.
2. Handle short-input redaction outcomes (`INPUT_SHORT`) as expected edge cases.
3. Never suppress non-text content just because guardrail provider focuses on text.
4. Keep observability context (`prompt`, session IDs, trace metadata) intact.
5. Add a policy layer if you need highly selective PII masking logic.

## Final Take

Walled AI is a strong guardrail building block, especially for fast safety + PII integration.

Its biggest advantage is speed to value: you get practical safety and masking quickly, with a clean integration model.

The key is not assuming provider behavior equals application behavior.

Production-safe integrations come from the combination of provider checks, session-aware runtime logic, and explicit handling of edge cases like short inputs, placeholder collisions, and tracing continuity.

That combination is where reliability comes from.

## Related Resources

- [Walled AI Documentation](https://walled.ai/)
- [Walled AI Guardrails (Agent Kernel Docs)](../docs/advanced/guardrails-walledai)
- [Walled AI Example (Agent Kernel)](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/guardrail/walledai)
