# Research — #606 human-in-the-loop

Supporting investigation behind [`../design.md`](../design.md). Not requirements; the design
distils these and cites them.

| File | Takeaway | Status |
|---|---|---|
| [`framework-hitl-survey.md`](framework-hitl-survey.md) | Four of the six frameworks (OpenAI, LangGraph, Pydantic AI, ADK) have a durable, programmatic pause/resume; CrewAI's is on Flows, which AK does not wrap, and smolagents has no serialisable pause at all. Exactly matches the four the issue names. | Complete. Framework APIs read from current official docs, then **import-checked against the pinned versions** — see `verification.md` for the results and four corrections. |
| [`adapter-strategies.md`](adapter-strategies.md) | Per-adapter mapping. LangGraph needs almost no new machinery (AK already assigns a pickle-serializable checkpointer keyed on `session.id`); ADK is the only target adapter with a structural blocker (`Runner` built from a bare agent, not an `App`) and unresolved upstream streaming-resume bugs. | Complete. All `path:line` citations read from `develop`. |
| [`verification.md`](verification.md) | Every symbol the design depends on exists at the pinned versions — 26 checks, 0 genuine failures. **`InMemorySessionService` pickles with a live session, so ADK pause state is durable through AK's session store.** Four documentation claims corrected. Plus two follow-ups: the **ADK `App` break analysis** (open question 5) and **AG-UI's native interrupt support**, present at AK's pinned `ag-ui-protocol` 0.1.20 with no bump needed (which withdrew open question 7). | Complete. Run against a throwaway venv at the `uv.lock` versions. |

## Both pre-`spec.md` verification gates are closed

They were: import-check the framework symbols against the pinned versions, and confirm
`google.adk.sessions.InMemorySessionService` is picklable. Both were run — see
[`verification.md`](verification.md). Everything the design relies on exists, and ADK durability is
confirmed rather than assumed.

Re-run the verification after any framework version bump. Correction 4 in that file (Pydantic AI's
deferred types are dataclasses, not Pydantic models) is the one most likely to change on an upgrade,
and it drives a serialisation choice in `spec.md`.
