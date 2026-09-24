# #606: Human-in-the-loop — durable pause, decision, and resume — Implementation Plan

The order [`spec.md`](spec.md) gets built in. Iterations map onto the five stacked PRs
[`design.md`](design.md) defines; each leaves `develop` working and testable on its own, and no
iteration needs a later one to be correct. Nothing in the shipped product pauses until Iteration 5.

| Iteration | PR | Leaves you with |
|---|---|---|
| 1–2 | 1 | The contract, purely additive. Nothing pauses. |
| 3–4 | 2 | The wiring, driven by a pausing test double. Still nothing real pauses. |
| 5–6 | 3 | OpenAI and LangGraph pause and resume. |
| 7–8 | 4 | Pydantic AI and ADK too. |
| 9 | 5 | AG-UI, the example, docs and skills. |
| 10 | 5 | Docs and skills sync. |

Two decisions must be settled **before Iteration 5**: whether an adapter appends or replaces when
its framework cannot hold two paused runs, and sign-off on `BaseChatRequest.prompt` becoming
optional (Iteration 3 lands that change).

---

## Iteration 1: The vocabulary

- **Goal:** the five new model types and `RunPaused` exist and round-trip; no behaviour changes.
- **Files:** `core/model.py`, `core/event.py`, `tests/test_hitl_models.py` (new),
  `tests/test_stream_events.py`.
- **Steps:**
  1. Add `PausedInterruption`, `ResumeDecision`, `ResumeSpec`, `AgentResumeRequestAny`,
     `AgentPausedReplyAny` per *spec.md § core/model.py*, including the `model_validator` that
     derives `content` and the `AK_CANCELLED_DECISION_MESSAGE` constant.
  2. Add `AgentResumeRequestAny` to the `AgentRequest` union (`model.py:125`). Leave the
     `AgentReply` union (`:126`) alone — that is the point of the subclass.
  3. Add `RunPaused` to the `StreamEvent` union and reword the `event.py:16-17` invariant.
  4. Update `test_stream_events.py` to the reworded invariant and add `RunPaused` to its matrix.
- **Verify:** `uv run pytest tests/test_hitl_models.py tests/test_stream_events.py` — and
  `uv run pytest` clean, since nothing else should move yet.

## Iteration 2: The record and the `Runner` surface

- **Goal:** a paused run can be stored, found and cleared; `Runner` advertises the capability.
- **Files:** `core/paused_run.py` (new), `core/util/picklable.py` (new), `core/base.py`,
  `tests/test_paused_run_state.py` (new).
- **Steps:**
  1. Move `Runner._not_picklable` into `core/util/picklable.py`; keep
     `Runner._ensure_framework_context_picklable`'s name, signature and error text so #526's tests
     are untouched.
  2. Add `PausedRun` and `PausedRunState` per *spec.md § core/paused_run.py* — `list`, `get`,
     `find_by_interruption`, `add` (assigns the id, checks picklability, warns once on
     `in_memory`), `clear`.
  3. Add `supports_pause` (default `False`), `resume()` and `resume_stream()` raising defaults to
     `Runner`.
- **Verify:** `uv run pytest tests/test_paused_run_state.py tests/test_base.py` — plus the
  session-store round-trip case, which is what proves the record is really durable.

## Iteration 3: The request and response surface

- **Goal:** a resume request can be sent and a paused reply comes back as `202` / `PAUSED`.
  Nothing dispatches on it yet.
- **Files:** `core/model.py`, `core/chat_service.py`, `tests/test_hitl_chat_service.py` (new),
  `tests/test_chat_service_core.py`.
- **Steps:**
  1. `BaseChatRequest.prompt` → `Optional[str] = None`; add `resume: Optional[ResumeSpec] = None`.
     **This is the public-model change — do not start before it is signed off.**
  2. `_validate`: prompt **or** resume on the built path, reusing the existing error message.
  3. `RequestBuilder`: `"resume"` into `known_fields`; append an `AgentResumeRequestAny` when the
     block is present.
  4. `ChatService._reject_ambiguous(req)` for `schedule` + `resume`, called as the **first**
     statement of all four entry points (`:390`, `:407`, `:428`, `:455`) — ahead of
     `_maybe_schedule`, or it never fires.
  5. `_success_status(req, reply=None)` and `ResponseBuilder.build_response`'s `status: "PAUSED"`
     keys.
- **Verify:** `uv run pytest tests/test_hitl_chat_service.py tests/test_chat_service_core.py
  tests/test_chat_service_schedule.py` — the last one guards that scheduling still behaves.

## Iteration 4: `Runtime` dispatch, diagnostics and the guardrail

- **Goal:** a pausing `DummyRunner` pauses and resumes end to end, including streaming.
- **Files:** `core/runtime.py`, `guardrail/guardrail.py`, `tests/test_runtime_resume.py` (new),
  `tests/test_runtime_resume_warnings.py` (new), `tests/test_hitl_stream.py` (new),
  `tests/test_hitl_guardrail.py` (new).
- **Steps:**
  1. `Runtime._extract_resume` and `_validate_resume` (the four failure modes, agent resolved from
     the record, `supports_pause` checked here).
  2. Dispatch in `run` (`:278-286`) and `stream` (`:328-341`), acting on the **post-hook** list.
  3. The three `WARNING`s per *spec.md § diagnostics*, on the `ak.runtime` logger (`:139`).
  4. Leftover-record cleanup, scoped to a resumed run whose reply is not an `AgentPausedReplyAny`.
  5. Paused-stream terminal sequence: `RunPaused` → `boundaries.drain()` → `done=True`, and the
     session **is** stored (unlike the `StreamHalt` branch at `:366`).
  6. Extend `BaseGuardrailUtil._extract_text_from_requests` to read `message` and string `payload`
     values off an `AgentResumeRequestAny`.
- **Verify:** `uv run pytest tests/test_runtime_resume.py tests/test_runtime_resume_warnings.py
  tests/test_hitl_stream.py tests/test_hitl_guardrail.py tests/test_runtime_stream_events.py` —
  plus the transport round-trip assertion that the pipeline needs no change.

## Iteration 5: OpenAI

- **Goal:** a real OpenAI agent pauses on a gated tool and resumes.
- **Files:** `framework/openai/openai.py`, `tests/test_openai_runner.py`.
- **Steps:**
  1. Detect `result.interruptions` **before** `.final_output` (`openai.py:211`); write the record
     with `result.to_state().to_json()`; build the reply.
  2. `resume()` / `resume_stream()`: `RunState.from_json`, apply `approve`/`reject`, re-run.
  3. The two rejections **above the `try`**: a `payload` on any decision, and a `prompt` alongside
     the resume.
  4. Settle append-or-replace for this adapter (OpenAI can hold two — the only one that can).
- **Verify:** `uv run pytest tests/test_openai_runner.py` — the per-adapter matrix, plus the
  two-concurrent-pauses case and the pinned accepted-behaviour stale-resume test.

## Iteration 6: LangGraph

- **Goal:** a graph calling `interrupt()` pauses and resumes; single- and multi-select work.
- **Files:** `framework/langgraph/langgraph.py`, `tests/test_langgraph_runner.py` (new if absent).
- **Steps:**
  1. Detect `"__interrupt__"` **before** `result["messages"][-1]` (`:427`) — the literal string,
     not `langgraph.constants.INTERRUPT`.
  2. Streaming detection after the stream drains, at the existing `aget_state` (`:481`).
  3. `resume()`: `Command(resume={id: value})` on the same `thread_id`.
  4. Prompt alongside a decision via `Command(update={"messages": [...]})` — AK's encoding, marked
     as such in the adapter docstring.
- **Verify:** `uv run pytest tests/test_langgraph_runner.py` — including that the status reaches
  the node intact and that a chosen value arrives as the node's `interrupt()` return.

## Iteration 7: Pydantic AI

- **Goal:** both its axes work — approvals and deferred calls.
- **Files:** `framework/pydanticai/pydanticai.py`, `tests/test_pydanticai_runner.py`.
- **Steps:**
  1. Detect `DeferredToolRequests` **before** `AgentReplyAny.from_output` (`:178`) — the bug that
     currently hands the user a dataclass repr at `:182`.
  2. Map `approvals` → `kind: "tool_call"`, `calls` → `kind: "input_required"`.
  3. `resume()`: `DeferredToolResults(approvals=..., calls=...)`, with the decision's
     `payload`/`message` supplied as the deferred call's **result**.
  4. Partial-resume rejection **above the `try`**, naming the missing ids.
- **Verify:** `uv run pytest tests/test_pydanticai_runner.py` — assert the value the human chose is
  what the **model receives** as the tool return, not merely that the run completed.

## Iteration 8: Google ADK

- **Goal:** long-running tools and confirmations pause and resume; the `App` change lands.
- **Files:** `framework/adk/adk.py`, `tests/test_adk_runner.py` (new if absent).
- **Steps:**
  1. Detect per event in `get_response` (`:204-230`): `long_running_tool_ids` ∩ `function_call.id`,
     or a `function_call` named `adk_request_confirmation`.
  2. Wrap the agent in an `App` with `ResumabilityConfig(is_resumable=True)`, preserving the
     `app_name` override so AK's session key is unchanged.
  3. `resume()`: `run_async(new_message=Content(parts=[Part(function_response=...)]))`, plus
     `invocation_id=` when resumable.
  4. **Establish by test**, not assumption: whether ADK streaming can pause and resume at 2.8.0,
     and whether a text part can ride beside the `function_response`. If either fails, yield a
     clear error and capture the repro for the docs.
- **Verify:** `uv run pytest tests/test_adk_runner.py` — plus the explicit assertion that ADK
  session state survives pickling.

## Iteration 9: AG-UI and the example

- **Goal:** a pause is answerable over AG-UI, and there is something runnable to look at.
- **Files:** `integration/agui/handler.py`, `integration/agui/run_input.py`,
  `tests/test_agui_resume.py` (new), `examples/api/hitl/` (new).
- **Steps:**
  1. `AGUIRequestHandler._events` grows the third terminal shape:
     `RunFinishedEvent(outcome=RunFinishedInterruptOutcome(...))`, with any state snapshot emitted
     **before** it.
  2. `AGUIRunInput` maps `RunAgentInput.resume` → `AgentResumeRequestAny` with **no `run_id`**;
     `ResumeEntry.status` maps without flattening.
  3. Runnable example: pause → decision → resume over REST.
- **Verify:** `uv run pytest tests/test_agui_resume.py` — including a two-runs-outstanding case
  resolved by interruption id, and decisions spanning both refused.

## Iteration 10: Sync docs and skills

Surfaces this change invalidates. Each is checked against the branch and either updated or
explicitly confirmed as needing nothing, then run through `ak-dev-sync-docs-from-branch` and
`ak-dev-sync-skills-from-branch` before merge.

**Skills — must change:**

| File | Line | Why |
|---|---|---|
| `.agents/skills/ak-dev-architecture/SKILL.md` | 257–260 | **Reply types** gains `AgentPausedReplyAny` |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 95–110 (Runner) | `supports_pause`, `resume()`, `resume_stream()` |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 234 | `ChatService` — `prompt` optional, the `resume` block, the second `202` |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 422–425, 463 | AG-UI — the third terminal shape |
| `.agents/skills/ak-dev-architecture/SKILL.md` | 482–483 | `ScheduleSpec` neighbourhood — `ResumeSpec` sits beside it; `schedule` + `resume` guard runs ahead of `_maybe_schedule` |
| `.agents/skills/ak-dev-new-framework-integration/SKILL.md` | 190, 426 | A new adapter declares `supports_pause` too; add it to the checklist |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | test-file table | Seven new test files |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md` | 42 | **Pre-existing error, fix while here:** says `StreamBoundaryTracker` is in `core/stream.py`; it is at `runtime.py:39` |

**Docs — must change:**

| File | Why |
|---|---|
| `docs/docs/api/rest-api.md` | the `resume` request block, `202` + `status: "PAUSED"`, optional `prompt` |
| `docs/docs/api/agui-server.md` | the interrupt terminal outcome and `RunAgentInput.resume` |
| `docs/docs/architecture/execution-flow.md` | the pause/resume path |
| `docs/docs/frameworks/*` | per adapter: **on OpenAI a stale resume is undetected** and "I need a value" must be a question, not a gated tool; ADK's sub-agent routing change and session growth; LangGraph's node re-runs from the top and AK overwrites a user checkpointer |
| a new HITL page under `docs/docs/advanced/` | "answer it soon or lose it", that clearing the non-volatile cache discards a pending pause, and that a durable pause needs a shared session backend |

**Release notes:** the ADK routing change is a behavioural change for existing multi-agent ADK apps
and belongs there, not only in the adapter docs.

**Confirmed as needing no update** (verify, do not assume): `ak-dev-code-quality`,
`ak-dev-new-messaging-integration` (`BaseChatRequest` usage at `:123` still valid — `prompt` is
widened, not removed), the queue-mode and deployment docs, and every `ak-dev-new-*` skill other than
the framework one.

- **Verify:** `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` both clean, and
  `cd ak-py && uv run pytest` green with `make lint-check-all`.
