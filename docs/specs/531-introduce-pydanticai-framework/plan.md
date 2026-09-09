# #531: Evaluate and Integrate Pydantic AI as an Agentic Platform — Implementation Plan

Orders the build of [spec.md](spec.md) into six iterations. The change is **purely additive** — no
existing adapter, core module, or test is modified — so the existing test suite stays green at every
iteration boundary; each new iteration only adds coverage or surfaces. Steps reference spec.md
section names rather than restating them.

## Sequencing at a glance

| Iteration | Delivers | Depends on | Leaves working |
|---|---|---|---|
| 1. Packaging + adapter | `framework/pydanticai/`, extra, alias | — | An agent runs end-to-end in the default (trace-disabled) config |
| 2. Tracing | 4 factory-file edits + 2 runner files | 1 | Trace-enabled config (`langfuse` / `openllmetry`) runs |
| 3. Tests | 2 new test files | 1, 2 | Full suite green incl. new coverage |
| 4. Example | `examples/cli/pydanticai/` | 1 | Runnable CLI demo |
| 5. Docs | framework page, sidebar, overview, READMEs | 1 | Docs site + READMEs reflect the adapter |
| 6. Sync skills & docs | `.agents/skills/*`, user skills | 1–5 | Repo guidance matches implementation |

Iteration 1 is the critical path; 2–5 depend only on it and could be parallelised. Iteration 1
carries the one genuine research gap (`attach_tool()`) that **must** be resolved before merge — see
Risks.

---

## Iteration 1: Packaging + framework adapter

- **Goal:** `PydanticAIModule([...])` constructs, runs, streams, and binds tools end-to-end in the
  default config; `import agentkernel.pydanticai` is clean.
- **Files:** `ak-py/pyproject.toml`; `ak-py/src/agentkernel/framework/pydanticai/__init__.py`,
  `.../framework/pydanticai/pydanticai.py`; `ak-py/src/agentkernel/pydanticai.py` (alias).
- **Steps:**
  1. Add the `pydanticai` optional-dependency group first (spec "Packaging") — the adapter's
     module-level `from pydantic_ai import ...` won't import without it, so nothing else in this
     iteration is testable until the extra installs.
  2. Implement `PydanticAISession`, `_process_requests()`, `PydanticAIToolBuilder`,
     `PydanticAIRunner.run()`/`stream()`, `PydanticAIAgent`, `PydanticAIModule` per the matching
     spec "Design" subsections. Wire `__init__.py` and the public alias per spec "Package layout".
  3. **Resolve the `attach_tool()` open item** (spec "`PydanticAIAgent` wrapper") against the
     installed `pydantic-ai==2.13.0` source — confirm the post-construction tool-registration call,
     do not ship the placeholder. This is a merge gate (Risks).
  4. The `Trace.get().pydanticai()` branch in `PydanticAIModule` is reached only when
     `trace.enabled` (default `False`), so this iteration is fully functional before Iteration 2;
     do not stub tracing here.
- **Verify:** install the extra into the ak-py venv (e.g. `uv pip install -e '.[pydanticai]'`), then
  `python -c "import agentkernel.pydanticai"`; run a minimal `PydanticAIModule` script (one agent, a
  bound tool, one `run()` and one streamed run) against a real provider key if available — otherwise
  Iteration 3's unit tests are the proof. Existing suite still green (`cd ak-py && uv run pytest`).

## Iteration 2: Tracing

- **Goal:** Trace-enabled config instantiates and runs for both backends.
- **Files:** `trace/base.py`, `trace/trace.py`, `trace/langfuse/langfuse.py`,
  `trace/openllmetry/openllmetry.py` (the four factory-method edits), plus new
  `trace/langfuse/pydanticai.py` and `trace/openllmetry/pydanticai.py`.
- **Steps:**
  1. Land all four factory-method edits **in one commit** (spec "Consumer changes → Tracing"): the
     abstract `pydanticai()` on `BaseTrace` makes `Trace`, `LangFuse`, and `OpenLLMetry`
     un-instantiable until each implements it, so they cannot be split across commits.
  2. Write the two runner files per spec "Tracing — asymmetric wiring across the two backends":
     Langfuse runner (`Agent.instrument_all()` + `OpenInferenceSpanProcessor` + span wrap);
     OpenLLMetry runner (`Agent.instrument_all()` + `TraceloopContext` wrap, self-instrumenting
     unlike its siblings).
- **Verify:** `python -c "from agentkernel.trace.langfuse.pydanticai import LangFusePydanticAIRunner; from agentkernel.trace.openllmetry.pydanticai import OpenLLMetryPydanticAIRunner"`;
  run the Iteration 1 smoke script twice with `trace.enabled=true` and `trace.type` set to
  `langfuse`, then `openllmetry`, confirming no instantiation failure and spans emit.

## Iteration 3: Tests

- **Goal:** Full suite green, including the new adapter coverage.
- **Files:** `ak-py/tests/test_pydanticai_runner.py`, `ak-py/tests/test_tool_pydanticai.py`.
- **Steps (all from spec "Testing"):**
  1. Runner tests — mock `agent.agent.run` (instance method; **not** a module-level `Runner`, unlike
     `test_openai_runner.py`) with `mock_run_result.output` (not `.final_output`): error-handling
     parity, structured-output parity.
  2. `BinarySerde` round-trip of a `PydanticAISession` holding real serialized message history.
  3. Multimodal-wiring test (design.md's explicit requirement): with `multimodal.enabled` patched
     `True`, assert `override_system_prompt()` and `attach_tool()` both fire during
     `PydanticAIAgent.__init__`.
  4. Tool-builder tests — assert `isinstance(tool, Tool)` and read `tool.function_schema.json_schema`
     (not `FunctionTool` / `params_json_schema`).
- **Verify:** `cd ak-py && uv run pytest tests/test_pydanticai_runner.py tests/test_tool_pydanticai.py`,
  then full `uv run pytest` + `make lint-check-all`.

## Iteration 4: Example

- **Goal:** A runnable, tested CLI demo.
- **Files:** `examples/cli/pydanticai/{pyproject.toml,demo.py,demo_test.py,README.md}`.
- **Steps (spec "Examples and docs"):** mirror `examples/cli/openai/`; use delegation-via-tool in
  place of `handoffs=[...]`; every agent passes explicit `name=` **and** `description=` so the demo
  models the non-empty-description guidance rather than the pitfall it documents.
- **Verify:** `cd examples/cli/pydanticai && ./build.sh && uv run pytest`; a live `uv run demo.py` if
  a provider key is present.

## Iteration 5: Docs

- **Goal:** Docs site and READMEs show the adapter as a first-class framework.
- **Files:** `docs/docs/frameworks/pydantic-ai.md` (new), `docs/sidebars.js`,
  `docs/docs/frameworks/overview.md`, `ak-py/README.md`.
- **Steps (spec "Examples and docs"):**
  1. New framework page mirroring `openai.md`, with the three called-out deviations
     (delegation not `handoffs=`; streaming `output_type` truncation caveat; the `description=`
     note).
  2. `sidebars.js`: insert `'frameworks/pydantic-ai'` between `smolagents` and `multi-framework`.
  3. `overview.md`: add a Pydantic AI entry to all four enumerations (`:13-17`, `:28-32`, `:39`,
     `:51-89`) with its real capability row (native streaming; `output_type`; multi-provider).
  4. `ak-py/README.md`: add Pydantic AI to the framework list (`:11`) and `"pydanticai"` to the
     session-key list (`:1327-1330`). Root `README.md:39,100` optional; leave the pre-existing
     "Smol Agents (soon)" staleness alone.
- **Verify:** `docs` site builds; `grep -rn "pydantic" docs/docs/frameworks/overview.md docs/sidebars.js`
  shows the new entries; framework page renders.

## Iteration 6: Sync skills and docs

- **Goal:** Repo developer/user guidance matches the shipped adapter.
- **Files (verified this pass — expected touch points):**
  - `.agents/skills/ak-dev-architecture/SKILL.md`: adapter list (`:21`), Runner-examples list
    (`:56`), structured-output framework list (`:117`), directory tree (`:289-294`).
  - `.agents/skills/ak-dev-new-framework-integration/SKILL.md`: the "beyond OpenAI, CrewAI,
    LangGraph, Google ADK, Smolagents" existing-framework list (`:5-6`), test-pattern examples
    (`:311`).
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md`: add `test_pydanticai_runner.py` /
    `test_tool_pydanticai.py` to the test-file table.
  - `.agents/skills/ak-dev-new-tracing-provider/SKILL.md`: the framework-method enumeration
    ("all five framework methods … implement all six", `:175`) becomes six methods.
  - User skills `ak-py/src/agentkernel/skills/{ak-init,ak-build,ak-test}/SKILL.md`: verify whether
    their framework-choice enumerations need a Pydantic AI entry (the sync flow resolves this).
  - `.claude/skills/` mirror: rely on the `chore(auto): sync skills/docs` automation, or copy the
    changed dev skills in the same PR to keep the diff self-contained.
- **Steps:** run `ak-dev-sync-skills-from-branch` and `ak-dev-sync-docs-from-branch` to make these
  edits systematically; the list above is the expected surface set to confirm against.
- **Verify:** `grep -rn "Smolagents\|smolagents" .agents/skills` — every five-framework enumeration
  now also names Pydantic AI; both sync flows report clean.

---

## Definition of done

- [ ] `import agentkernel.pydanticai` works with the extra installed; without it, selecting the
      adapter raises an actionable `ImportError` (spec "Error handling") — base install unaffected.
- [ ] `PydanticAIModule` runs, streams, binds tools, and persists/restores history across two
      `Runtime.run()` calls in one session (jsonable serialization, spec "PydanticAISession").
- [ ] `attach_tool()`'s post-construction mechanism confirmed against `pydantic-ai==2.13.0` and
      exercised by the multimodal-wiring test — **no placeholder merged**.
- [ ] Trace-enabled config instantiates and runs for both `langfuse` and `openllmetry`; all three
      concrete `BaseTrace` subclasses implement `pydanticai()`.
- [ ] Full `ak-py` suite green (minus credential-gated e2e per AGENTS.md); `make lint-check-all`
      passes.
- [ ] CLI example builds, its `demo_test.py` passes, and it demonstrates delegation-via-tool with
      explicit `name=`/`description=`.
- [ ] Framework page, sidebar, `overview.md`, and `ak-py/README.md` lists updated; no existing
      adapter/example/page changed except additive enumeration entries.
- [ ] Dev + user skills updated (or confirmed clean) via the sync flows.
- [ ] Commits/PR follow `ak-dev-code-quality`; PR targets `develop`.

## Risks and notes

- **`attach_tool()` is the one unverified mechanism** (spec "PydanticAIAgent wrapper", Behavioural
  notes #6). It gates multimodal support and must be confirmed against the installed source in
  Iteration 1 — treat a still-placeholder `attach_tool()` as a blocking merge failure, and let the
  Iteration 3 multimodal test catch a silent regression.
- **Tracing's four factory files are atomic.** The abstract method on `BaseTrace` breaks
  instantiation of `Trace`/`LangFuse`/`OpenLLMetry` until all three implement it — never split
  Iteration 2 across commits that leave the tree un-importable.
- **OpenLLMetry runner self-instruments** (`Agent.instrument_all()` in `__init__`), unlike every
  sibling OpenLLMetry runner — deliberate, because Traceloop's bundled coverage of Pydantic AI is
  unconfirmed (spec "Tracing"). Do not "simplify" it to match the siblings.
- **Version churn.** `pydantic-ai~=2.13.0` is pinned patch-only against a fast-moving library; the
  ceiling advances deliberately as later versions are vetted (spec "Packaging"), not automatically —
  a follow-up bump is expected maintenance, not a defect.
- **Purely additive.** No existing adapter, core abstraction, `AKConfig` field, or test changes;
  the only edits to existing files are the four trace factory methods, the docs enumerations, and
  the README lists — all additive. Keep the diff reviewable on that basis.
