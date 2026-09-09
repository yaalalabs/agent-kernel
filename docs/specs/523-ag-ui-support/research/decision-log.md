# Decision log and intended delivery shape

Decisions taken while researching #523, recorded so they are not re-litigated or lost between the
design and the spec. Everything here was settled in review discussion on **2026-08-14** unless
noted otherwise.

**Status of this file.** It is a decision log, not a plan and not requirements. `ak-dev-review-pr`
does not extract requirements from `research/`, so nothing here is binding on an implementation.
When Stage 3 arrives, `plan.md` is the canonical home for the delivery shape below — treat §2 as
its input, and delete or shorten §2 here rather than maintaining two copies.

> **Superseded in places by `design.md`.** This file records what was settled on 2026-08-14; design
> review since then reversed several entries. **`design.md` is authoritative wherever the two
> disagree** — the list below exists so nothing here is read as still-current:
>
> - **D3** — reversed. The package is an **integration at `integration/agui/`**, mounted via
>   `RESTAPI.run(handlers=[...])`, not a config-gated router at `api/agui/`. This follows from queue
>   mode leaving scope, which was D3's whole premise.
> - **D6** — reversed. AG-UI defines **its own pluggable authoriser**, thread-shaped, falling back to
>   `AuthValidator`. An integration owning its authoriser keeps it a dependency leaf.
> - **D7** — reversed. `execution.mode: stream` is **not** required process-wide; AG-UI's routes are
>   its own and never consult the mode.
> - **D12** — reversed. A **single static HTML example ships**. The objection was to a JavaScript
>   build in a Python repo, not to the demo.
> - **D2, D14** — superseded. Queue mode is **out of scope** for #523 entirely, so it is neither
>   last in the delivery order nor `in_memory`-only.
> - **D10's open URL question** — answered. URL sources are refused while `multimodal.enabled: true`
>   and passed through when it is `false`; the underlying pre-hook bug is confirmed and filed
>   separately.
> - **§2** — superseded. Delivery is **seven PRs**, and CrewAI/smolagents streaming is a separate
>   issue rather than PR 4.
> - **§3** — several questions are now closed in `design.md` (back-compatibility policy, the fidelity
>   matrix, the discovery route, the version pin). Read §3 as history, not as an open list.
>
> Decisions **not** superseded, still current: D1, D4, D5, D8, D9, D11, D13, and the unratified
> recommendations in §1, all of which `design.md` adopted.

---

## 1. Settled decisions

| # | Decision | Why |
|---|---|---|
| D1 | **A2UI is out of scope**; it gets its own issue, filed after #523's design is approved. | A2UI is a payload, not a transport, and has no technical dependency on AG-UI. It also reaches all six adapters while AG-UI reaches four, so bundling would hold the cheaper, broader capability behind the expensive one. |
| D2 | **Delivery order:** direct mode → widen the streaming contract → adapters → queue mode. | Keeps each PR reviewable, and lands the contract change before queue mode so the per-chunk queue path is never revisited twice. |
| D3 | **Package lives at `api/agui/`**, config-gated in `RESTAPI.build_app` beside A2A and MCP — **not** passed as a handler to `RESTAPI.run()`. | A config-gated router coexists with the queue pipeline; an explicit `handlers=` argument switches the whole process out of queue mode. Revised from an earlier `integration/agui/` recommendation, which assumed handler-mounting. |
| D4 | **`Runner.supports_streaming` capability declaration** added to core. Discovery lists only streaming-capable agents; calling a non-capable one refuses explanatorily. | Follows the `SandboxCapabilities` "declare it honestly" pattern, and doubles as the source of truth for the per-adapter fidelity matrix later. |
| D5 | **Identity comes from the bearer token**, via a pluggable validator — never from the request envelope. | AG-UI carries a conversation identifier but no user identity; trusting the body would let any caller resume another user's conversation by guessing an id. |
| D6 | Recommended mechanism for D5 is **`auth.AuthValidator` → `ValidationResult.subject`**, not `integration/thread/Authoriser`. | Identical semantics (token → user id), but `auth/` is a package `api/agui/` can depend on cleanly; the thread authoriser would invert the dependency direction. Note: the validator must be called *inside* the route, because router-level `Depends` do not hand their return value to the endpoint. |
| D7 | **`execution.mode: stream` is required process-wide**, enforced by a startup failure. | The streaming-vs-request-response choice is made once at process start, so the handler cannot decide per request. |
| D8 | **AG-UI runs are not recorded as Agent Kernel conversation threads.** `thread_id` maps to `session_id` and nothing else. Must be documented, not silent. | The envelope's `thread_id` will otherwise make reviewers and adopters assume thread recording happens. |
| D9 | **`RunAgentInput.tools` (client-executed tools) is ignored**, as an explicit documented non-goal. | AK's tool registry is populated once at startup, and frontend-executed tools additionally need pause-and-resume machinery AK lacks. Silence would produce a feature that fails with no error. |
| D10 | **Inbound attachments are in scope** — images and documents. *(Reverses an earlier text-only decision taken the same day.)* | Requires only envelope mapping; no attachment-storage code. Two existing paths already handle the request objects: with managed attachment handling **enabled**, the `Runtime` system pre-hook describes, stores and injects metadata (`core/multimodal/factory.py:19-35`); with it **disabled**, a no-op hook lets the request through and the adapter hands the image to the model directly (`framework/openai/openai.py:117-128`). AG-UI must not add behaviour to either path, and must not require one. |
| D11 | **Agent-produced images are out of scope.** The reply degrades to its text form. | Two blockers, and the binding one is not AK's: AG-UI has no event able to carry an image back, and separately no adapter constructs `AgentReplyImage`. Unblocked by the protocol gaining an attachment event, not by any change here. |
| D12 | **No frontend example application.** Verification is pytest plus a scripted SSE client. | Avoids introducing a JavaScript build into a Python repository, and the maintenance that follows. |
| D13 | **Route shape mirrors A2A**: one POST per agent plus a discovery route, with a bare path only when a default agent is configured. | `RunAgentInput` has no agent field, and A2A already solved agent selection with a path segment. |
| D14 | **Queue mode is `in_memory` only.** | Streaming over a broker is already blocked pending #495 Phase C's pod-direct WebSocket delivery. |

### Recommendations not yet ratified

- **Audio and video content types** (AG-UI defines both; AK has no equivalent request type):
  refuse with an explanatory error rather than mapping them onto the generic file type. Treating a
  video as a document produces confusing vision-model output.
- **URL-sourced attachments**: *no recommendation — an earlier "refuse them" recommendation was
  withdrawn on 2026-08-14 because its premise was wrong.* AK does not fetch such URLs; the adapter
  already accepts `http://`, `https://`, `s3://` and `data:` prefixes and passes the URL to the
  model provider (`framework/openai/openai.py:122`), so refusing them at the AG-UI boundary would
  make AG-UI more restrictive than every existing surface. **Needs verification before PR 1:**
  whether the attachment pre-hook handles a URL source, since it expects base64 bytes to store.
  That specific combination — URL source with managed attachment handling enabled — is the only
  open risk.
- **`Runner.supports_streaming` default**: `True` on the base class, since `stream` is abstract
  and implementing it is the contract; set `False` explicitly on the two adapters that raise.
- **Client-submitted system prompts stripped**, and `RunAgentInput.context` entries fed to the
  model as tool output rather than as instructions — Pydantic AI's documented anti-injection
  posture, consistent with D5.

---

## 2. Intended delivery shape — five PRs

Tasks and PRs are not the same unit: #495 shipped as one issue with ordered PRs, and the same
applies here. Multimodal (D10) is its own task with its own verification but ships inside PR 1.

**Superseded — kept as the 2026-08-14 record.** `design.md`'s Delivery table is the current shape:
six PRs, differently scoped, with the streaming contract first rather than the integration. Queue
mode (PR 5 below) has since become an explicit non-goal, and "Nothing emits them yet" no longer
holds — `Runtime.stream` synthesises events from `str` from the first PR onward. Read the table
below as what was decided that day, not as the plan.

| PR | Scope | Green gate |
|---|---|---|
| **1** | AG-UI direct mode: event mapper, handler and routes, config block, `build_app` mount, `Runner.supports_streaming`, token-derived identity, inbound attachments, docs | new tests pass; existing suite untouched |
| **2** | Event union, widened `Runner.stream`, `Runtime.stream` normalization, and the collapse back to the existing streaming type so current surfaces are unaffected. Mapper learns the new members. Nothing emits them yet | **full suite green with zero test edits** |
| **3** | OpenAI, LangGraph, ADK, Pydantic AI adapters | per-adapter tests |
| **4** | CrewAI and smolagents adapters — net-new streaming implementations, version floors pinned, `supports_streaming` flipped | per-adapter tests; coverage becomes six of six |
| **5** | Queue mode: enqueue seam extracted, AG-UI queue handler, topology wiring, broker fail-fast | pipeline tests |

**Dependency shape.** Three independent roots, which is what allows parallel progress:

- PR 1 needs nothing.
- PR 2 needs nothing (it is independent of the AG-UI surface until its mapper step).
- PRs 3 and 4 both sit on PR 2 and are **siblings, not a chain** — merge in whichever order review returns; a stuck adapter never blocks another.
- PR 5 needs PR 1. The enqueue-seam extraction inside it is a standalone refactor that can land early to shrink the PR.

Adapter ordering within PRs 3–4 is deliberate: the four that already stream validate the event
union before two net-new SDK integrations are built on it.

---

## 3. Open questions carried into `design.md`

Spec-stage or low-controversy; recorded here so they are not silently dropped.

- The exact rules for collapsing rich events back into the existing streaming type. The
  *requirement* is "existing surfaces unaffected"; the rules themselves are spec-stage, and must be
  fixed in PR 2 before any adapter flips or PR 3 becomes a silent regression.
- Whether non-text events reach the streaming post-hook. Proposed: no — its signature is text, and
  a text-redaction hook should not begin receiving tool-call objects.
- Back-compatibility policy for user-written runners that still yield text: supported indefinitely
  via normalization, or deprecated with a removal version?
- Naming and module location of the event union; whether the existing streaming type is eventually
  deprecated or frozen as the text view.
- Per-adapter fidelity matrix — which union members each of the six can actually fill.
- AG-UI version pin, and behaviour when the client is newer than the server.
- Whether the AG-UI discovery route re-declares the existing agent-listing route, or relies on
  being additive.
- Known ceiling to document: shared response stores implement whole-message storage, not chunk
  streaming, so multi-instance AG-UI needs #495 Phase C.

### Unresolved research gap

Whether AG-UI publishes a conformance test kit upstream. If it does, PR 1's tests should use it
rather than hand-rolled assertions, following the reusable-contract pattern already used for queue
transports and sandbox providers. **Not investigated.**

---

## 4. Verified facts the spec should not re-derive

These took real digging. All read on `develop` at `1693d2e0`, 2026-08-14.

| Fact | Evidence |
|---|---|
| The whole streaming vocabulary is three fields; a session id passed alongside is silently dropped by the model and re-attached by the response builder | `core/model.py:173-176`, `core/runtime.py:257`, `core/chat_service.py:318-320` |
| The runner streaming contract is text-only, and adapters filter rich native events down to it | `core/base.py:355`, `framework/openai/openai.py:226-229`, `framework/adk/adk.py:280-286` |
| Streaming-vs-request-response is selected once at process start | `pipeline/io_handler.py:73` |
| Streaming over a broker transport already fails fast | `pipeline/io_handler.py:111-112` |
| The response handler pushes directly only when the client is addressable; otherwise it hands off through the response store | `pipeline/response_handler.py:44-57` |
| The pipeline builds its app through the shared builder, so config-gated routers coexist with queue mode | `pipeline/io_handler.py:52`, `api/http.py:131-143` |
| Agent Kernel constructs the CrewAI crew itself per run, so it can enable streaming without user cooperation | `framework/crewai/crewai.py:374` |
| An image reply type exists and every consumer handles it, but **no code constructs one** | `core/model.py:107`; all other references are imports, type checks, or the union |
| No route serves attachment bytes, so "return a link" is not available as an outbound workaround | absence verified across `api/` and the thread handler |
| Integrations are a dependency leaf — nothing in core, api or the pipeline imports them | absence verified across `core/`, `api/`, `pipeline/` |
| The framework-wide token validator already resolves a subject | `auth/handler.py:13-17` |
| Attachment storage is type-agnostic, so images and documents share one path | `core/multimodal/storage/base.py:19-28` |
| The two "cannot stream" adapter comments are stale | `framework/crewai/crewai.py:412`, `framework/smolagents/smolagents.py:188`; see `ag-ui.md` §3.2.1 |
