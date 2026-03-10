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

## Limitations

Walled AI is strong for baseline safety and PII redaction, but there are provider-level limitations teams should understand before production rollout.

### 1. No Cross-Call Placeholder Memory

Walled AI does not keep a session memory of placeholders across redaction calls.

Example:

- Call A: "my name is john" -> `my name is [Person_1]`
- Call B: "my brother is james" -> `my brother is [Person_1]`

The same label can appear again for a different value in later calls. Teams should treat placeholder IDs as call-scoped unless they add an application-side session strategy.

### 2. Limited PII Masking Configuration Controls

Fine-grained field-level controls can be limited for some domain requirements.

Example requirement:

- Mask only CVV.
- Keep account number visible (or partially visible).

If you need this type of selective policy, you may need an extra policy layer before or after provider redaction.

### 3. Text-Centric Guardrail Surface

The primary safety/redaction operations are text-focused. Mixed-content pipelines (text + image/file/other) still need runtime logic to preserve and route non-text objects correctly.

## Issues in Existing Features

These are practical issues observed while integrating current features in Agent Kernel.

### 1. Short Inputs and `INPUT_SHORT`

Very short messages like "hi", "ok", or "23" can return `INPUT_SHORT` during redaction.

- This is not a safety violation.
- It means redaction was not applicable for that payload.

Agent Kernel handles this by bypassing redaction for that request and continuing.

### 2. Redaction Failure Handling

If redaction fails for reasons other than `INPUT_SHORT`, allowing the exception to bubble can fail the full request path.

Agent Kernel now returns a safe fallback response for this path to keep runtime behavior resilient.

### 3. Tracing Context Loss on Output Rewrite

If unmasking creates a new reply object without preserving metadata, tracing tools can lose input-output linkage.

Agent Kernel preserves `prompt` when returning unmasked `AgentReplyText` to maintain observability context.

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
