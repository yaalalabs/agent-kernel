# AK-63 — Structured Agent Responses: High-Level Overview

This document explains the AK-63 change in plain terms — the problem, the fix, and what it
means for developers — without diving into line-by-line detail. For the full implementation
spec see [`ak-63-structured-agent-responses.md`](./ak-63-structured-agent-responses.md).

## The problem

Every agent framework Agent Kernel supports (OpenAI Agents SDK, Google ADK, CrewAI, LangGraph,
SmolAgents) has a first-class way to make an agent return **structured output** — a Pydantic
model or a JSON-schema-conforming result instead of free text. This is how you get an agent to
reliably answer "give me the weather as `{city, temp_c, condition}`" rather than a paragraph you
have to parse.

Agent Kernel was **throwing that structure away.** Each framework runner took the structured
result and coerced it to a string before returning it:

- The OpenAI and SmolAgents runners called `str(...)` on the result.
- CrewAI only read the plain-text `raw` field and ignored the structured fields it populates.
- LangGraph dropped the `structured_response` the graph produced.
- ADK returned the JSON as raw text the caller had to re-parse.

So a developer who asked for structured output got back a stringified Python object (often a
Pydantic `repr`, which **isn't even valid JSON**) and had to fragilely re-parse it. In effect,
structured output was unsupported end-to-end even though every framework offered it.

## The fix

Introduce one new reply type and teach the whole pipeline to carry it through intact.

**A new reply type — `AgentReplyAny`.** It sits alongside the existing `AgentReplyText` and
`AgentReplyImage` and holds the structured result as a plain `dict` in a `content` field. It
behaves like the other reply types everywhere that matters:

- `str(reply)` returns the JSON string, so every existing consumer that logs, traces, or renders
  a reply keeps working unchanged.
- It carries the same `prompt` field the other replies have.
- A helper, `AgentReplyAny.from_output(value)`, does the "is this structured?" decision once:
  a Pydantic model becomes a JSON-safe dict (`model_dump(mode="json")`), a plain dict is used
  as-is, and anything else returns `None` so the caller falls back to a normal text reply.

**Every runner now detects structure and returns `AgentReplyAny`** when the framework produced
it — using whatever mechanism that framework exposes (`output_type`, `output_schema`,
`output_pydantic`/`output_json`, `response_format`, or just a dict/model returned from the agent).
Plain-text agents are completely unaffected — they still return `AgentReplyText`.

**The structured reply flows through the hook chain untouched.** Pre-hooks and post-hooks now
receive the `AgentReplyAny` object with its live `content` dict, so a hook can inspect or modify
the structured data directly instead of string-surgery on text. The runtime's internal
type-checks were widened to accept the new type (previously they would have rejected it and
raised an error on the very first run with the default guardrail hook).

## What changes for a developer

**If you want structured output:** configure it on your agent the way your framework already
documents, then check the reply type:

```python
reply = await service.run_multi([AgentRequestText(text="Weather in Colombo as JSON")])
if isinstance(reply, AgentReplyAny):
    data = reply.content       # a dict — no re-parsing, no guessing
else:
    text = reply.text
```

- **OpenAI** — `Agent(output_type=MyModel)`
- **Google ADK** — `LlmAgent(output_schema=MyModel)`
- **CrewAI** — `module.get_agent("Name").output_pydantic = MyModel` (or `.output_json`)
- **LangGraph** — `create_react_agent(..., response_format=MyModel)`
- **SmolAgents** — return a dict or model from `final_answer`

**If you don't:** nothing changes. Text agents behave exactly as before; this is fully backward
compatible.

**If you write hooks:** a post-hook may now receive an `AgentReplyAny`. If your hook assumed
`reply.text` always exists, handle the structured case (`reply.content` for the dict, or
`str(reply)` for the JSON string).

**At the edges (API / chat / guardrails):** anywhere a reply is rendered to a string still works,
because `str(AgentReplyAny)` yields JSON. The REST `result` field, Slack, and Teams now render
structured replies as their JSON string instead of "Non textual result received", and output
guardrails now scan the JSON content (previously structured replies could slip past them). In
process, callers who want the actual dict use `run_multi()` and read `reply.content`.

## What is explicitly out of scope

- **Streaming.** Streamed runs still emit token-by-token text deltas; no structured parsing is
  added to the stream path. Structured output is a non-streaming feature.
- **A nested-object API response.** The REST `result` field stays a JSON *string* to avoid
  breaking existing API clients; a structured API shape may follow later.
- **Agent-to-agent handoffs inside a framework workflow**, where hooks don't run today anyway.

## A side change bundled in (CrewAI)

Because CrewAI's structured knob lives on the per-run `Task` (which the runner builds), the CrewAI
work also hardened conversation handling: the runner now keeps a short, deterministic conversation
**transcript** in the session so follow-up prompts have context even when embedding-based memory
isn't configured, and a memory-write failure (e.g. no embedder) now logs a warning and continues
instead of failing the run. This is additive and transparent to callers.

## Why this approach

- **One new type, not a rewrite.** Reusing the existing `AgentReply` union and the `str()`
  contract meant the vast majority of the codebase needed no changes.
- **Symmetric with the request side.** `AgentReplyAny` mirrors the existing `AgentRequestAny`
  (`type: "other"`), so the model stays consistent.
- **Fail-safe.** Structured detection only *adds* a branch; every unrecognized or error case
  falls back to the exact text behavior that existed before.
