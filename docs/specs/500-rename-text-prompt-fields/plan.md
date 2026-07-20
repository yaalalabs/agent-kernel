# AK-166: Rename text/prompt Fields in Agent Request/Reply Models — Implementation Plan

Breaks the rename in [design.md](design.md) into ordered iterations. No spec.md exists for this
change — it is a mechanical rename with no behavioural component, and design.md already enumerates
every file; plan steps reference design.md sections directly.

**Prerequisite — design.md decisions (resolved on AK-166).** The five questions in design.md
"Resolved decisions" were signed off on the AK-166 ticket before this branch landed:
`AgentReplyAny.content` keeps its name, clean break (no compatibility aliases), reply `prompt`
stays optional (`= ""`), versioned doc snapshots excluded. The backward-compatibility decision
(clean break vs. aliases) — which determines what Iteration 1 does to `core/model.py` — carries
that explicit maintainer sign-off.

**Why the source sweep is one iteration:** `AgentReplyText` inherits from `AgentRequestText`, so
renaming `text → prompt` on the request immediately collides with the reply's existing `prompt`
field and breaks every `AgentReplyText(text=..., prompt=...)` construction. The request rename and
the reply `response` field cannot land separately with the branch importable — models and all
source consumers move together.

## Iteration 1: Models + source consumers

- **Goal:** All of `ak-py/src` uses `prompt` (input) / `response` (output); package imports clean.
  Test suite is red until Iteration 2 — expected for an atomic rename.
- **Files:** `core/model.py`, `core/service.py`, `core/chat_service.py`, `core/multimodal/hooks.py`,
  `framework/{openai,adk,langgraph,crewai,smolagents}`, `trace/langfuse/langgraph.py`,
  `guardrail/{guardrail,walledai,bedrock,openai}.py`, 7 integration chat handlers,
  docstrings in `core/{hooks,runtime,service}.py`.
- **Steps:**
  1. `core/model.py`: rename `AgentRequestText.text → prompt`; add optional `prompt: str = ""` to
     `AgentRequestImage`; add `AgentReplyText.response` (`__str__` returns it); reparent
     `AgentReplyImage` onto `AgentRequestImage` and replace its `text` output field with
     `response` (image + `prompt` fields now inherited, no longer redeclared); update docstrings
     (design.md "Request model" / "Reply models").
  2. Update every `AgentRequestText(text=...)` construction and `req.text` read
     (design.md "Request model" site list).
  3. Update every `AgentReplyText/AgentReplyImage` construction and output-field read, including
     `walledai.py` `model_copy(update={"text": ...}) → {"response": ...}`
     (design.md "Reply consumers" site list).
  4. Update source docstrings listed in design.md "Documentation & skills".
- **Verify:** `grep -rn "\.text\b\|text=" ak-py/src/agentkernel` returns only the non-goal
  occurrences (external SDK payload keys, `ThreadMessage.content`, httpx `response.text` —
  design.md "Non-goals"); `python -c "import agentkernel"` succeeds.

## Iteration 2: Tests

- **Goal:** Full suite green.
- **Files:** the 15 files in design.md "Tests": `test_runtime.py`,
  `test_module.py`, `test_tool.py`, `test_tool_adk.py`, `test_api_http.py`, the 5 runner tests,
  `test_guardrail.py`, `test_guardrail_walledai.py`, `test_thread_chat_service.py`,
  `test_thread_multimodal_hook.py`, `test_thread_manager.py`.
- **Steps:**
  1. Update constructions, isinstance checks, and attribute assertions: request `text → prompt`,
     reply output `text → response`. `reply.content` assertions unchanged.
- **Verify:** `cd ak-py && pytest tests/` — green apart from the known e2e tests that need
  credentials (per AGENTS.md); `make lint-check-all` passes.

## Iteration 3: Docs and examples

- **Goal:** All active docs and examples show the new field names.
- **Files:** design.md "Documentation & skills" verified doc list — `docs/docs/core-concepts/{runner,runtime}.md`,
  `docs/docs/architecture/memory-management.md`, `docs/docs/integrations/hooks.md`,
  `docs/blog/2025-12-18-hooks-and-smart-memory.md`; examples: `examples/api/hooks/*`,
  `examples/api/openai/app.py`, `examples/api/openai_structured/*`, `examples/cli/openai_structured/*`,
  `examples/memory/key-value-cache/hooks.py`.
- **Steps:**
  1. Mechanical rename in each file; `docs/versioned_docs/version-*` untouched (design.md non-goal).
- **Verify:** `grep -rn "AgentRequestText(text=\|agent_reply\.text\|reply\.text\|result\.text" docs/docs docs/blog examples/` returns nothing.

## Iteration 4: Sync skills

- **Goal:** Dev and user skills match the implementation.
- **Files:** `.agents/skills/{ak-dev-architecture,ak-dev-testing-conventions,ak-dev-new-framework-integration,ak-dev-new-guardrail-provider,ak-dev-new-messaging-integration,ak-dev-new-tracing-provider}/SKILL.md`;
  `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`.
- **Steps:**
  1. Rename field references in the six dev skills and the user skill.
  2. `ak-dev-new-tracing-provider/SKILL.md:135` — deliberate edit, not mechanical:
     `len(result.text) if hasattr(result, 'text') else 0` → the `'text'` string literal in
     `hasattr` must become `'response'` or the expression silently returns 0.
  3. `ak-build/SKILL.md` needs no update (only describes `AgentReplyAny.content`, which keeps its
     name) — verified, per design.md.
  4. `.claude/skills/` mirror: rely on the `chore(auto): sync skills/docs` automation, or copy the
     changed dev skills in the same PR if the diff must be self-contained.
  5. Confirm coverage with the `ak-dev-sync-skills-from-branch` / `ak-dev-sync-docs-from-branch`
     flows before merge.
- **Verify:** `grep -rn "req\.text\|reply\.text\|result\.text\|AgentRequestText(text=\|AgentReplyText(text=" .agents/skills ak-py/src/agentkernel/skills` returns nothing.
