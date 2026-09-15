# #706 research — A2UI as an unopinionated platform

Supporting investigation for "[FEATURE] A2UI Support for Agent Kernel" (issue #706).

Read [`../../523-ag-ui-support/research/a2ui.md`](../../523-ag-ui-support/research/a2ui.md) first —
it is the protocol survey (what A2UI is, what the Python SDK does, four candidate routes) and it is
not repeated here. This document only answers the question that survey left open, and that the
issue answered narrowly:

> The issue proposes **v1 = payload layer, REST only**, with the payload leaving as a JSON string
> that the client double-parses. This research assumes a different target: **A2UI as an
> unopinionated platform** — one payload capability, and *every* AK surface able to carry it,
> starting with the two we already run (A2A, AG-UI) and then REST and WebSocket.

Code facts verified on `feature/706-a2ui-transport-agnostic` at `9d3d3a40`. Protocol facts are
inherited from the #523 survey and were **not** re-verified; A2UI was v0.9.1 there.

The file-by-file change list that follows from this is in [`changes.md`](changes.md).

## 1. The framing that keeps this unopinionated

A2UI is a payload, not a transport. If AK builds "A2UI transport support", it ends up with A2UI
branches inside four surfaces — which is exactly the opinion [AGENTS.md](../../../../AGENTS.md)
tells adapters not to take.

The unopinionated split is one layer lower:

| Layer | What it is | A2UI's part in it |
|---|---|---|
| **Payload** | A capability that teaches an agent to produce a validated structured reply | A2UI is one such capability. Others (JSON Schema output, AG-UI state patches) fit the same slot. |
| **Carriage** | Every surface can emit a *structured* reply as structured data, not `str()` | A2UI is just one media type riding it. Nothing in a surface says "a2ui". |

So the work is: **stop flattening structured replies at the surfaces**, and add A2UI as one
payload capability on top. Every surface fix below is valuable to existing `AgentReplyAny` users
who have never heard of A2UI — that is the test that the change is not an A2UI opinion.

## 2. What exists already

Nothing needs inventing at the payload layer — AK ships all four mechanisms:

| Need | AK has | Where |
|---|---|---|
| Per-capability config block with an `agents` filter | The sandbox / `agui` block pattern | `core/config.py:758` (`_SandboxConfig`), `core/config.py:845` (`_AGUIConfig`) |
| Inject a capability's system prompt into every agent | `SystemToolFactory.get_system_prompt_suffix` | `core/tool.py:224`, built from `get_all` at `core/tool.py:179` |
| Post-process and validate every reply | `PostHook.on_run` | `core/hooks.py:51` |
| A structured reply type | `AgentReplyAny(content: dict)` | `core/model.py:129` |
| Optional dependency gating | The extras pattern (`agui` at `ak-py/pyproject.toml:88`, `a2a` at `:167`) | `ak-py/pyproject.toml` |

And structured replies already work on **all six** framework adapters (verified in the #523
survey), because A2UI needs no streaming. AG-UI reaches only four.

## 3. What is missing — payload layer

1. **No `a2ui` config block and no `a2ui` extra.** Mechanical; follows `_SandboxConfig`.

2. **`SystemToolFactory` can only carry a prompt on a tool.** `get_system_prompt_suffix` joins
   `SystemTool.description` strings (`core/tool.py:243`). An A2UI catalog is prompt-only — there is
   no tool to hang it on. Either register a description-only `SystemTool` (the sandbox already sets
   the precedent of one tool carrying a whole prompt section) or give the factory a prompt
   contributor that is not a tool. The second is cleaner and helps every future prompt-only
   capability.

3. **The system post-hook list is hardcoded.** `Runtime._get_system_post_hooks` returns
   `[OutputGuardrailFactory.get()]` (`core/runtime.py:63`). A second system capability makes this a
   small builder rather than a literal.

4. **`AgentReplyAny` cannot say *what kind* of structured payload it holds.** This is the one real
   core addition, and the linchpin of the whole platform story: a transport cannot emit
   `application/json+a2ui` unless the reply tells it the media type. Without it, every surface has
   to guess — or import A2UI to sniff the dict, which puts the opinion back. Suggested: an optional
   media-type / kind field on `AgentReplyAny`, defaulted so existing users are unaffected.

5. **Open questions the design must answer, not assume** (carried from the #523 survey §6):
   catalog ownership (does AK ship one, or only pass one through?), version pinning, and whether
   the action/callback round trip is in v1 or render-only. A UI with dead buttons is worse than no
   UI, so render-only is defensible but must be stated.

## 4. What is missing — carriage, per surface

Ordered as the user asked: the transports we already run first.

### 4.1 A2A — the protocol's own canonical wrapping

`api/a2a/a2a.py:49` hardcodes `new_agent_text_message(str(response), ...)`. Every A2A reply is a
text message; there is no `DataPart` path at all.

- **Needed:** part-aware event construction — a `DataPart` when the reply is `AgentReplyAny`,
  carrying the media type from §3.4. The agent card should also advertise the output mode.
- **Note:** JSON-as-a-string does **not** give this for free. An A2UI-aware A2A client will not
  recognise a text message, so this is the difference between "works" and "doesn't" — not polish.
- **Scope honesty:** this changes A2A wire behaviour for *all* structured replies, not just A2UI.
  That is the unopinionated outcome, but it is a behavioural change and needs saying out loud.

### 4.2 AG-UI — blocked on a real gap, not on a mapping

Two things are missing, and only the first is obvious:

- **No `CustomEvent` in the mapper.** `AGUIMapper.to_agui` (`integration/agui/mapping.py`) maps AK
  stream events to AG-UI ones and returns `None` for anything with no equivalent
  (`mapping.py:64`). AG-UI's `CustomEvent` has a structured `value` field, which is where an A2UI
  payload belongs. AK emits none today.
- **The deeper block: a streamed run never produces a final reply object.** `Runtime.stream`
  (`core/runtime.py:233-286`) calls `PostHook.on_stream_chunk` on text deltas only; it never calls
  `PostHook.on_run`. So an A2UI post-hook that parses the model's final output **will not fire on
  an AG-UI run at all**. There is also no AK `StreamEvent` variant that could carry structured data
  to map onto `CustomEvent`.

  Two ways out, and this is a genuine design fork:
  - **(a) A final-reply hook on the streaming path** — `Runtime.stream` assembles the finished
    reply and runs the post-hook chain before the terminal `StreamChunk(done=True)`
    (`core/runtime.py:286`). Reuses the payload capability unchanged; adds a hook contract.
  - **(b) A structured `StreamEvent` variant** (e.g. a data/custom event) that adapters can emit
    mid-stream and the mapper turns into `CustomEvent`. Matches A2UI's advertised incremental
    parse-and-heal, but needs per-adapter work and reaches only the four streaming adapters.

  (a) is the smaller change and keeps A2UI on all six frameworks; (b) is the one that eventually
  supports streaming UI. They are not exclusive — (a) first is the cheaper order.

### 4.3 REST and WebSocket — one chokepoint covers both

Good news, and it is worth checking before anyone plans two work items:

`ResponseBuilder.build_response` (`core/chat_service.py:317`) emits
`{"result": str(result) ...}` for every reply type including `AgentReplyAny`. It is the **only**
place non-streaming replies are flattened — verified: no other `str(reply)` exists across
`api/`, `pipeline/`, or `integration/agui/`; the sole other flattening site in the codebase is
A2A's line 49 above.

And the pipeline reaches it too: `AgentRunner.process` (`pipeline/agent_runner.py:44`) calls
`ChatService.process_chat_request`, whose response dict travels the output queue and leaves over
WebSocket as a dict (`WebSocketHandlerABC.send(..., message: dict)`, `pipeline/ws/base.py:108`).

So **one change to `ResponseBuilder` gives REST, WebSocket, async mode, and conversation threads
structured carriage at once.** The frame is already a dict on the WS side; nothing there stringifies.

- **Needed:** emit the structured content when the reply is `AgentReplyAny`, alongside (not
  instead of) the existing string, so current clients do not break.
- **Terminology warning for the design:** "WebSocket" in this repo means the queue-mode gateway
  (`pipeline/ws/`), not a direct socket on the REST app. A2UI over WebSocket therefore means
  *A2UI through the pipeline*, with the pipeline's constraints — not a new socket surface.

## 5. Suggested shape

Five pieces, each independently useful, each landing without the others:

| # | Piece | Unblocks |
|---|---|---|
| 1 | Media type on `AgentReplyAny` (§3.4) | Every surface below; nothing else can be done honestly first |
| 2 | `ResponseBuilder` carries structured content (§4.3) | REST + WebSocket + async + threads |
| 3 | A2A `DataPart` (§4.1) | The canonical A2UI wrapping |
| 4 | The `a2ui` payload capability — config, extra, prompt suffix, post-hook (§3.1–3.3) | A2UI itself, on all six adapters |
| 5 | Final-reply hook on `Runtime.stream` + AG-UI `CustomEvent` (§4.2) | A2UI over AG-UI |

Pieces 1–3 contain **no A2UI code**. That is the point: they are structured-reply carriage, useful
to today's `AgentReplyAny` users, and they are what makes piece 4 a capability rather than a
transport rewrite.

Note this inverts the issue's stated v1 (REST-only, JSON-in-a-string, deliberately accepted). The
issue's ordering is cheaper to ship; this ordering is what "unopinionated platform" costs. That
trade-off is the first thing `design.md` has to settle.
