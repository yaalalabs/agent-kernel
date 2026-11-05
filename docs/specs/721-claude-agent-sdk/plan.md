# #721: Claude Agent SDK integration — Implementation Plan

Build order for the [implementation spec](spec.md), based on the requirements in [design.md](design.md). The branch already contains much of this work; the iterations also serve as a review checklist. Do not mark the integration production-ready until the live checks in Iteration 5 pass.

## Iteration 1: Register a native Claude agent

- **Goal:** A named AK agent runs once through the Claude SDK with native options and a text reply.
- **Files:** `ak-py/pyproject.toml`, `ak-py/src/agentkernel/framework/claude/{__init__,claude}.py`, `ak-py/src/agentkernel/claude.py`.
- **Steps:**
  1. Add the optional `claude` extra and public import path (spec §Package and public API).
  2. Add `ClaudeAgentSpec`, `ClaudeAgent`, and `ClaudeModule`; keep `ClaudeAgentOptions` native and allow native `options.agents` (spec §Main agent and native subagents).
  3. Add `ClaudeRunner.run()` with a per-run `ClaudeSDKClient`, request conversion, output mapping, and native option validation (spec §Runner, options, input, and output).
- **Verify:** `test_claude_runner.py` cases for module registration, options, text and structured replies, rejected input, and SDK errors.

## Iteration 2: Persist sessions and map streams

- **Goal:** A second turn resumes the right native conversation, including after AK session serialization; real SDK events stream through AK.
- **Files:** `ak-py/src/agentkernel/framework/claude/claude.py`, `ak-py/tests/test_claude_runner.py`.
- **Steps:**
  1. Add `ClaudeSession` under the `claude` key implementing the SDK transcript methods itself (spec §Session and SDK transcript bridge).
  2. Assign a native session ID for the first turn, resume from saved ID and transcript later, and bind the agent to the result's session ID.
  3. Add `_ClaudeStreamMapper` and `ClaudeRunner.stream()` with early-close cleanup (spec §Runner, options, input, and output).
- **Verify:** Conversation, serialization, agent-isolation, subagent-transcript, streaming, error-result, and early-close tests in `test_claude_runner.py`.

## Iteration 3: Bind tools, context, and human approval

- **Goal:** AK tools work through the SDK's in-process MCP server, can read per-run context, and can pause safely for one human decision.
- **Files:** `ak-py/src/agentkernel/framework/claude/claude.py`, `ak-py/src/agentkernel/framework/claude/__init__.py`, `ak-py/tests/{test_tool_claude,test_claude_runner,test_claude_hitl_live}.py`.
- **Steps:**
  1. Add `ClaudeToolBuilder`, the reserved `ak` server, and ordinary tool approvals (spec §Bound tools and per-run context).
  2. Add `ToolContext.framework_context` (filled by the Claude runner) and per-run context write-back for completed runs and streams.
  3. Add `needs_approval`, the merged `PreToolUse` decision hook, one-use handler guard, paused records, `resume()`, and `resume_stream()` (spec §Human approval and resume).
- **Verify:** Tool schema and handler tests, framework-context tests, pause/resume and stale-transcript tests. The live test remains opt-in pending credentials.

## Iteration 4: Trace each run

- **Goal:** The configured AK tracer wraps each ordinary run in an outer span, as for the other frameworks, without claiming CLI-internal model visibility. Resumes and streams are untraced for every framework and are out of scope.
- **Files:** `ak-py/src/agentkernel/trace/{langfuse,logfire,openllmetry,cloudwatch}/claude.py`, `ak-py/src/agentkernel/framework/claude/{claude,__init__}.py`, `ak-py/tests/test_claude_traced_runner.py`.
- **Steps:**
  1. Wrap `run()` in each tracer (spec §Tracing, configuration, and consumer changes).
- **Verify:** `test_claude_traced_runner.py` checks the span is open around `run()` and records the reply; formatting and import checks pass.

## Iteration 5: Tests and live validation

- **Goal:** Mocked behavior passes locally and credentialed checks establish that the real CLI resumes and delegates as expected.
- **Files:** `ak-py/tests/{test_claude_runner,test_tool_claude,test_claude_traced_runner,test_claude_hitl_live}.py`, relevant `examples/{cli,api}/claude*` test files.
- **Steps:**
  1. Run the focused unit tests and `make lint-check-all`; correct concrete failures.
  2. With credentials, run the CLI/API examples and the opt-in HITL smoke test.
  3. Verify a two-turn conversation, native subagent delegation, and a follow-up after AK session reload on the intended session backend. Measure transcript size against that backend's limits before a production claim (design §Open questions).
- **Verify:** Record the commands and outcomes in the PR. If credentials or backend access are unavailable, record those checks as pending rather than passed.

## Iteration 6: Sync docs and skills

- **Goal:** Contributor and user guidance matches the final implementation and its verified limits.
- **Files:** `docs/docs/frameworks/{claude-agent-sdk,multi-framework}.md`, `docs/docs/{core-concepts/runner,advanced/human-in-the-loop,examples/overview}.md`, `examples/{cli,api}/claude*/README.md`, `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md`, `.agents/skills/{ak-dev-architecture,ak-dev-new-framework-integration,ak-dev-testing-conventions}/SKILL.md` where their Claude guidance changes.
- **Steps:**
  1. Document the native `ClaudeAgentOptions`/`AgentDefinition` split, permission settings, session transcript behavior, context and tracing limits, and live-validation status (spec §Tracing, configuration, and consumer changes).
  2. Confirm the docs site's framework inventories still include Claude; update only entries affected by this branch. Do not edit `docs/versioned_docs/`.
  3. Use the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` checks before merge; keep bundled skills focused on downstream users and dev skills focused on contributors.
- **Verify:** Links and examples resolve, changed Markdown is reviewable, and the docs/skills descriptions match the tested behavior.
