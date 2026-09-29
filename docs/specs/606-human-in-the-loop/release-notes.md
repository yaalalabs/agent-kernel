# Release notes draft: #606 Human in the loop

Paste-ready material for the GitHub release that ships #606 (three stacked PRs land in the same
release: core contract and wiring, the adapters, then AG-UI, the example and docs).

## Behavioural changes

**Google ADK: which sub-agent handles the next turn can change.**
Pausing an ADK run requires `ResumabilityConfig(is_resumable=True)`, which lives on an `App` rather
than an agent — so the adapter now wraps your agent in an `App` and enables it on **every** ADK run,
not only ones that pause. A per-agent switch would have reintroduced the "turn the feature on" knob
this feature deliberately avoids.

Resumability changes how ADK routes a turn: when the previous event was a function response, the
turn is routed back to the agent that made the call rather than re-entering at the root. **Existing
multi-agent ADK apps can therefore see a different sub-agent handle a turn.** Single-agent apps are
unaffected.

Two further consequences, both inherent to ADK rather than to Agent Kernel:

- **ADK sessions grow.** `is_resumable` also gates agent-state event emission.
- **`ResumabilityConfig` is marked experimental** by ADK and may change without notice. It is the
  only way to enable resumability.

Details and the per-framework behaviour table: `docs/docs/frameworks/google-adk.md`.

**HTTP 202 now means two things.** A deferred (scheduled) request and a paused one both answer 202.
Clients branch on the new top-level `status` discriminator: `"SCHEDULED"` for an acknowledgement,
`"PAUSED"` for a run waiting on a person. Existing scheduled-request clients that ignore `status`
still read the same body they always did.

## New: pausing a run for a person

An agent can stop mid-run to ask a human something — a gated tool awaiting approval, or a question
needing an answer — and resume from that decision minutes or hours later, on any replica.

```json
POST /api/v1/chat → 202
{ "status": "PAUSED", "run_id": "9f2c…", "agent": "support",
  "interruptions": [ { "id": "call_abc123", "kind": "tool_call",
                       "tool_name": "issue_refund", "arguments": "{\"order_id\": \"ORD-1001\"}" } ] }
```

Answer it by sending `resume` **instead of** a prompt (`prompt` is now optional):

```json
{ "agent": "support", "session_id": "user-123",
  "resume": { "decisions": [ { "id": "call_abc123", "status": "approved" } ] } }
```

- **Three decision statuses**: `approved`, `denied`, and `cancelled` — "nobody decided", which never
  reaches the model as a refusal.
- **`message`** carries the human's own words, **`payload`** a structured answer. Both optional.
- **`run_id` is optional** on the resume block; the run is resolved from the interruption ids.
- Works on **REST, streaming, and AG-UI**, and on the WebSocket pipeline.
- **Four frameworks pause**: OpenAI Agents SDK, LangGraph, Pydantic AI, Google ADK. CrewAI and
  smolagents report that they cannot (`supports_pause = False`) rather than pretending to.
- **Input guardrails inspect decisions.** A decision's `message` and the human-written strings in
  its `payload` go through the same input guardrail path as a prompt, so a resume is not a route
  that bypasses them. WalledAI redaction rewrites those strings in place, leaving the payload's
  shape untouched.

A pause is stored in the session's non-volatile cache, so **a durable pause needs a shared session
backend** — the in-memory default loses pending pauses on restart, and clearing the non-volatile
cache discards them. Limits, including per-framework ones, are in the new
[Human in the Loop](../../docs/advanced/human-in-the-loop.md) page.

**AG-UI**: a paused run ends with the protocol's interrupt outcome — a third terminal shape beside
`RunFinished` and `RunError` — and resumes via `RunAgentInput.resume`. The stream still closes
cleanly.

**Example**: `examples/api/hitl` — an OpenAI approval agent and a LangGraph question agent behind a
minimal React AG-UI frontend.

## Fixed

- **LangGraph: `interrupt()` was never resumable.** The checkpointer's `get_tuple` did not return
  `pending_writes`, so a resume silently re-ran the interrupting node from the top instead of
  delivering the stored answer. Pre-existing; any graph using `interrupt()` was affected.
- **LangGraph: sessions could not be stored.** Agent Kernel's checkpointer held an unpicklable
  serializer, so pickling the session raised and a LangGraph session never reached a shared
  backend — Redis, Valkey, DynamoDB. It now drops that field on pickle and rebuilds it on unpickle
  (`__getstate__` / `__setstate__`). Pre-existing, and load-bearing now that a pause lives in the
  checkpoint.
- **Streaming: the runner's generator is now closed** when a stream ends early. A pause breaks out
  of the event loop by definition, and an adapter holding a framework HTTP stream previously kept
  that connection open until garbage collection.

## Notes for maintainers

- Design, spec and iteration plan: `docs/specs/606-human-in-the-loop/`.
- Per-framework capabilities were established by running each SDK, not by reading its docs; the
  evidence is in `docs/specs/606-human-in-the-loop/research/verification.md`.
- A new adapter declares `supports_pause` and implements `resume()` / `resume_stream()`, or leaves
  the default `False` — see the checklist in `ak-dev-new-framework-integration`.
- Anything a session persists is now pickle-checked at write time through
  `core/util/picklable.py`, shared by the paused-run record and the per-run framework context.
