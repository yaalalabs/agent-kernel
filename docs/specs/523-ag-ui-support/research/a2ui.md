# A2UI: protocol survey and routes for Agent Kernel support

Companion research for #523. A2UI is not named in the issue body; it is included because it is the
other half of the "agentic UI" question and because AG-UI is one of its documented transports.
Protocol facts marked **[docs]** come from vendor documentation fetched 2026-08-14 and were not
exercised locally; code facts were read on `develop` at `1693d2e0`.

## 1. What A2UI is — and what it is not

A2UI (Agent-to-UI) is Google's open, Apache-2.0 protocol for **generative UI**: an agent describes
an interface as declarative JSON, and the client renders it using *its own* component catalog.
Made public 2025-12-15; currently v0.9.1, with v1.0 a release candidate and the project self-described
as early-stage public preview. **[docs]**

The defining stance is JSON over executable code: an agent emits a declarative payload, never JSX,
HTML, or JavaScript, so a compromised or hallucinating model cannot execute anything on the user's
device. Components are abstract types (`Card`, `Text`, `Button`, `Table`, …) resolved against a
client-side catalog of pre-approved native widgets, with ID references for incremental updates, a
data-model binding system, and action/callback wiring for user interaction. **[docs]**

**A2UI is a payload format, not a transport.** Its own documentation is explicit: "A2UI over MCP,
Websockets, REST, AG UI, A2A, or whatever you want." The canonical wrapping is an A2A `DataPart`
with MIME type `application/json+a2ui`. **[docs]**

This is the single most important fact for #523: **supporting A2UI does not require AK to build a
new frontend.** It requires (a) teaching the model to produce the JSON, (b) validating/parsing it,
and (c) getting it to a renderer over a transport AK already has.

### 1.1 What the agent side actually does

The Python SDK (`pip install a2ui-agent-sdk`) is thinner than the protocol's scope suggests: **[docs]**

- `A2uiSchemaManager(catalogs=[...])` loads component catalogs (JSON config, optionally with
  few-shot examples) and calls `generate_system_prompt(role_description=...)` — i.e. it **produces a
  system prompt** that teaches the LLM to emit valid A2UI JSON.
- `BasicCatalog.get_config()` supplies a built-in starter catalog; production apps supply their own.
- `parse_response()` / `parse_response_to_parts()` parse and validate model output, with documented
  support for incremental parse-and-heal so a client can render while generation is still streaming.
- `a2ui.a2a.create_a2ui_part({...})` wraps a payload as an A2A `DataPart`.

The reference ADK integration is three lines of wiring — build a schema manager, generate the
instruction, hand it to `LlmAgent(instruction=...)`. **[docs]**

Renderers exist for Lit, Flutter (via the GenUI SDK), and web-core-based Angular/React; Go and
Kotlin agent SDKs are listed as coming. **[docs]**

## 2. Why this fits Agent Kernel unusually well

Every mechanism A2UI needs already exists in AK, built for other reasons:

| A2UI needs | AK already has | Where |
|---|---|---|
| Inject a capability-specific system prompt into every agent | `SystemToolFactory.get_system_prompt_suffix(agent_name)` → `Agent._setup_system_prompt()` → per-framework `override_system_prompt()` | `core/tool.py:203`, `core/base.py:456-464`, `core/base.py:430` |
| Return structured JSON instead of text | `AgentReplyAny(content: dict)`, with `__str__` returning JSON | `core/model.py:127-141` |
| Post-process/validate every reply | `PostHook.on_run(session, requests, agent, agent_reply) -> AgentReply` | `core/hooks.py:51` |
| Per-agent opt-in for a capability | The `agents: List[str]` filter pattern used by sandbox/A2A/MCP config | `core/config.py:112`, `core/tool.py:167` |
| Optional dependency gating | The extras pattern | `ak-py/pyproject.toml:23-172` |

Critically, **structured replies already work on all six frameworks** — verified individually, not
assumed:

| Framework | Structured reply constructed at |
|---|---|
| OpenAI | `framework/openai/openai.py:193` (`AgentReplyAny.from_output`) |
| LangGraph | `framework/langgraph/langgraph.py:409` |
| Pydantic AI | `framework/pydanticai/pydanticai.py:162` |
| Smolagents | `framework/smolagents/smolagents.py:175` |
| Google ADK | `framework/adk/adk.py:247` |
| CrewAI | `framework/crewai/crewai.py:387,389` |

That coverage beats AG-UI's *today*: AG-UI depends on streaming, and AK's CrewAI and smolagents
adapters refuse it (`crewai.py:415`, `smolagents.py:191`) — though both SDKs do stream, so that gap
is AK's to close, not the frameworks' (see `ag-ui.md` §3.2.1). **A2UI needs no streaming at all**,
so it reaches every adapter without any adapter work, which is a strong argument for not treating it
as merely a follow-on to AG-UI.

## 3. The one real obstacle: `str(reply)` at the surfaces

AK's response surfaces flatten replies to strings, so a structured A2UI payload would arrive as a
JSON string inside a text field rather than as structured data:

- REST: `ResponseBuilder.build_response` emits `{"result": str(result), ...}` for every reply type
  including `AgentReplyAny` (`core/chat_service.py:295-297`).
- A2A: the executor sends `new_agent_text_message(str(response), ...)`
  (`api/a2a/a2a.py:49`) — text only, no `DataPart`. So the documented A2UI-over-A2A wrapping is
  **not** reachable today without changing this line.
- Streaming: `StreamChunk.delta` is `str | None` (`core/model.py:174`), so nothing structured can
  travel mid-stream at all.

Because `AgentReplyAny.__str__` JSON-serializes its content (`core/model.py:140-141`), a client
*could* double-parse the string and get the payload. That works, and it is ugly, and the design
should decide deliberately whether v1 accepts it or fixes the surfaces.

## 4. Four routes for AK to emit A2UI

### Route 1 — A2UI as an AK capability (prompt + parse), transport-agnostic

Model it on the multimodal and sandbox capabilities: an `a2ui` config block; when enabled, a system
prompt suffix carrying the catalog schema is injected via the existing `SystemToolFactory` path; a
system `PostHook` parses and validates the model's output and returns it as an `AgentReplyAny`.

- **For:** framework-agnostic by construction — all six adapters, streaming or not. Reuses three
  mechanisms AK already ships. No new frontend, no new transport. Independent of AG-UI, so it can
  land before, after, or without it.
- **Against:** does not by itself solve §3 — the payload still exits through `str(reply)` unless a
  surface is also taught about it. Catalog management (whose catalog, shipped how, versioned how)
  is new surface area. Prompt-injected schemas consume context on every request.
- **Verdict:** the natural core of any A2UI support, and the piece the other three routes build on.

### Route 2 — A2UI payloads over AG-UI

Once #523 ships an AG-UI surface, carry the payload in an AG-UI `Custom` event (`name` + `value`),
which is the protocol's documented extension point — this is what "AG-UI as middleware lets any
AG-UI framework drive A2UI on day zero" refers to. **[docs]**

- **For:** the vendor-blessed pairing; a CopilotKit-style frontend gets generative UI with no
  bespoke channel; solves §3 for streaming clients because the event is structured, not a string.
- **Against:** strictly gated on AG-UI landing first, and on AG-UI Route B/C/D choices. Inherits
  AG-UI's streaming dependency, so it silently excludes CrewAI and smolagents.

### Route 3 — A2UI over the existing A2A surface

Emit the payload as an A2A `DataPart` with `application/json+a2ui`, per the canonical wrapping.

- **For:** AK already runs an A2A server (`api/a2a/`), config-gated at `core/config.py:110-114`; this
  is the protocol's own reference transport; works for non-streaming frameworks.
- **Against:** requires replacing the text-only `new_agent_text_message` call at `api/a2a/a2a.py:49`
  with part-aware construction, which changes A2A wire behavior for structured replies generally —
  a behavioral change beyond A2UI that needs its own justification. A2A is also an agent-to-agent
  channel; using it as the UI channel is legitimate per the spec but unusual in AK's topology.

### Route 4 — A2UI as a tool the agent calls

Register a `render_ui(payload)` system tool (the `SystemToolFactory` shape AK already uses for
multimodal's `analyze_attachments` and the sandbox's eight tools) and let the agent invoke it
explicitly instead of shaping its whole final answer as UI JSON.

- **For:** the agent can interleave prose and UI; no need to force every reply into a schema; tool
  calls are already observable in AK; degrades gracefully when the model ignores it.
- **Against:** diverges from the reference A2UI agent pattern (system-prompt-shaped final output),
  so upstream examples and catalogs won't map cleanly; the payload still needs a route out to the
  client, so this composes with Routes 2/3 rather than replacing them.

## 5. Suggested framing for `design.md`

Treat A2UI and AG-UI as **one capability with two layers**, matching the issue's own phrasing that
"AG-UI can be one adapter":

- an *event/transport* layer, where AG-UI is the first adapter (research: [`ag-ui.md`](ag-ui.md));
- a *payload* layer, where A2UI is the first adapter (Route 1 above), reachable over AG-UI (Route 2),
  A2A (Route 3), or plain REST.

Deciding this shape up front is what prevents A2UI arriving later as a bolt-on to whatever AG-UI
happened to build.

## 6. Questions `design.md` must answer, not assume

1. **Is A2UI in scope for #523 at all**, or does it get its own issue? It is not mentioned in the
   issue body, and Route 1 has no technical dependency on AG-UI.
2. **Catalog ownership**: does AK ship/bundle a catalog, require the application to supply one, or
   only pass one through? This is the difference between a small capability and an ongoing
   maintenance surface.
3. **Structured replies at the surfaces** (§3): does v1 accept JSON-in-a-string via `str(reply)`, or
   does it change `ResponseBuilder` and/or the A2A executor? The latter is a behavioral change to
   existing non-A2UI structured-output users.
4. **Streaming A2UI**: the SDK advertises incremental parse-and-heal, but AK's `StreamChunk.delta` is
   `str`. Is partial-payload streaming in scope, or is A2UI non-streaming-only in v1?
5. **Version pinning**: v0.9.1 with a v1.0 release candidate outstanding — pin, or wait for 1.0?
6. **Interaction/callbacks**: A2UI defines actions and callbacks from the rendered UI back to the
   agent. Is that round trip in scope, or is v1 render-only? Render-only is a defensible v1 but must
   be stated, since a UI with dead buttons is worse than no UI.

## Sources

- [Introducing A2UI (Google Developers Blog)](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/)
- [A2UI v0.9: portable, framework-agnostic generative UI](https://developers.googleblog.com/a2ui-v0-9-generative-ui/)
- [google/A2UI on GitHub](https://github.com/google/A2UI)
- [A2UI — Agent-to-UI for ADK](https://adk.dev/integrations/a2ui/)
- [a2ui-agent-sdk on PyPI](https://pypi.org/project/a2ui-agent-sdk/)
- [Google A2UI v0.9 release coverage (InfoQ)](https://www.infoq.com/news/2026/07/google-a2ui-genui/)
- [Open Agent Specification support for A2UI through CopilotKit AG-UI (Oracle)](https://blogs.oracle.com/ai-and-datascience/announcing-agent-spec-for-a2ui-copilotkit-ag-ui)
