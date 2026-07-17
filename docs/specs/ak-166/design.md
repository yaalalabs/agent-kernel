# AK-166: Rename text/prompt Fields in Agent Request/Reply Models

Rename the input field `AgentRequestText.text` to `prompt`, and rename the agent-output field in the reply models (`AgentReplyText`, `AgentReplyImage`) from `text` to `response`, so a single concept has a single name across requests, replies, and the REST layer. Reply models keep `prompt` for the originating input prompt. This is a straight rename with no behavioural change; the surface area is large (frameworks, guardrails, tracing, integrations, tests, docs) but every change is mechanical.

## Motivation

- The input concept has two names depending on layer:
  - REST/queue request bodies already call it `prompt` — `BaseChatRequest.prompt` (`ak-py/src/agentkernel/core/model.py:213`), consumed as `req.prompt` in `chat_service.py:42,56` and `service.py`.
  - The internal request model calls it `text` — `AgentRequestText.text` (`ak-py/src/agentkernel/core/model.py:17`), so every runner does `AgentRequestText(text=req.prompt)` (`chat_service.py:42`, `service.py:127`) — a rename-in-place at every boundary.
- The reply models overload `text`/inheritance confusingly:
  - `AgentReplyText(AgentRequestText)` **inherits `text` and repurposes it as the agent OUTPUT**, while adding an explicit `prompt` field for the INPUT (`model.py:89-101`; `__str__` returns `self.text`, `:101`). A field named for user input is reused to hold agent output.
  - `AgentReplyImage` has an explicit `text` (output) plus `prompt` (input) (`model.py:116,117`).
  - `AgentReplyAny` uses `content` (output dict) plus `prompt` (input) (`model.py:140,141`).
  - The output concept therefore has three names (`text`, `text`, `content`) across the three reply types.
- After renaming `AgentRequestText.text → prompt`, `AgentReplyText`'s inherited field becomes `prompt` — which would then be used to hold output, worsening the confusion. Giving reply output its own name (`response`) resolves this: reply models inherit/keep `prompt` for input and expose `response` for output.
- `response` is a clean target: no request/reply model field or attribute read named `response` exists (verified — the only `.response` reads in source are botocore/httpx exception objects, unrelated to these models), so no collisions.

## Requirements

### Request model (`core/model.py`)

- Rename `AgentRequestText.text` → `prompt` (field, type stays `str`).
  - Update the class docstring and `__str__` (returns `self.prompt`).
- Update every construction `AgentRequestText(text=...)` → `AgentRequestText(prompt=...)` and every read `req.text` → `req.prompt`, including:
  - Core: `service.py:127`, `chat_service.py:42,56`, `multimodal/hooks.py:155,169,172`.
  - Framework runners (isinstance + `.text` read): `framework/openai/openai.py:111-112`, `adk/adk.py:113-114`, `langgraph/langgraph.py:339-340`, `crewai/crewai.py:339-340`, `smolagents/smolagents.py:142-143`, `trace/langfuse/langgraph.py:39-40`.
  - Guardrails: `guardrail/guardrail.py:84-87`, `guardrail/walledai.py:107,112,159`.
  - Integrations that build request text via `AgentRequestText(text=...)`: slack, teams, gmail, telegram, instagram, messenger, whatsapp chat handlers.

### Reply models (`core/model.py`)

- `AgentReplyText`: the agent-output value currently held in the inherited `text` field becomes an explicit `response` field.
  - Keep inheriting from `AgentRequestText` so the reply carries `prompt` (input); override `prompt` with a default to preserve the current optional behaviour (`prompt: str = ""`, was `model.py:98`).
  - Add `response: str = ""`; `__str__` returns `self.response`.
- `AgentReplyImage`: rename `text` → `response` (output); leave `prompt` (input) and image fields unchanged; `__str__` uses `self.response`.
- `AgentReplyAny`: `prompt` (input) unchanged; `from_output(..., prompt=...)` signature unchanged. Whether the output field `content` is renamed is an open question (see below) — default recommendation is to leave it `content`.
- The `AgentReply` union alias (`model.py:128`) and `core/__init__.py` re-exports (`:20,22,23,24`) are unaffected by field renames (class names unchanged).

### Reply consumers

- Reads of the output field `.text` → `.response`:
  - `service.py:131` (`result.text`), `guardrail/guardrail.py:97,101` (`agent_reply.text`).
- Reads of the input field `.prompt` are **unchanged** (field keeps its name): trace runners `trace/langfuse/{openai,crewai,smolagents,adk}.py` (`result.prompt`), `guardrail/openai.py:188`, `guardrail/bedrock.py:276`.
- Reply construction `AgentReplyText(text=..., prompt=...)` → `AgentReplyText(response=..., prompt=...)` in all runners and guardrails: `framework/{openai,adk,langgraph,crewai,smolagents}`, `trace/langfuse/langgraph.py`, `guardrail/{walledai,bedrock,openai}.py`.
- String-keyed serialization surfaces that name the model field:
  - `guardrail/walledai.py:207,210` — `model_copy(update={"text": ...})` → `{"response": ...}` for `AgentReplyText`/`AgentReplyImage`.
  - `guardrail/walledai.py:204` — `model_copy(update={"content": ...})` for `AgentReplyAny` follows the `content` open-question decision.
- `str(reply)` renderings rely only on `__str__` and need no change once `__str__` is updated: `chat_service.py:292`, `integration/slack/slack_chat.py:157`, `integration/teams/teams_chat.py:294`.

### API / serialization

- No dedicated API/OpenAPI/A2A/MCP schema hard-codes these reply field names; the REST `ResponseBuilder` (`chat_service.py:274-292`) emits `str(result)` via `__str__`, so response payload shape is preserved.
- `AgentReplyAny.content` is serialized via `model_dump(mode="json")` (`model.py:160,162`; `crewai.py:380`) — behaviour preserved unless `content` is renamed (open question).

### Tests

- Update all constructions, isinstance checks, and attribute assertions that use `text`/`.text` on requests/replies to `prompt`/`response`:
  - `test_runtime.py`, `test_module.py`, `test_tool.py`, `test_tool_adk.py`, `test_api_http.py`. (`test_model.py` is excluded — its only relevant line is `AgentReplyAny(content=..., prompt=...)`, both names unchanged.)
  - Runner tests: `test_openai_runner.py`, `test_adk_runner.py`, `test_crewai_runner.py`, `test_langgraph_runner.py`, `test_smolagents_runner.py`.
  - Guardrail tests: `test_guardrail.py`, `test_guardrail_walledai.py`.
  - Thread/multimodal tests: `test_thread_chat_service.py`, `test_thread_multimodal_hook.py`, `test_thread_manager.py`.
- `reply.content` assertions change only if `content` is renamed (open question).

### Documentation & skills

- Active docs referencing the renamed fields (`AgentRequestText(text=...)`, `AgentReplyText(text=...)`, `.text`) — verified against the base branch: `docs/docs/core-concepts/{runner,runtime}.md`, `docs/docs/architecture/memory-management.md`, `docs/docs/integrations/hooks.md`, `docs/blog/2025-12-18-hooks-and-smart-memory.md`. No change needed on `docs/docs/architecture/execution-flow.md`, `docs/docs/advanced/multimodal.md`, or `docs/blog/2026-03-10-*.md` (zero occurrences), nor on `docs/docs/frameworks/{crewai,google-adk,langgraph,smolagents}.md` (match only on `AgentReplyAny`/`content` prose; `content` keeps its name). `openai.md` has no matches.
- Dev skills under `.agents/skills/`: `ak-dev-architecture`, `ak-dev-testing-conventions`, `ak-dev-new-framework-integration`, `ak-dev-new-guardrail-provider`, `ak-dev-new-messaging-integration`, `ak-dev-new-tracing-provider`.
  - `ak-dev-new-tracing-provider/SKILL.md:135` needs a deliberate edit, not a mechanical rename: `len(result.text) if hasattr(result, 'text') else 0` — the `'text'` string literal inside `hasattr` won't be caught by an attribute rename and would silently fall through to the `else 0` branch.
  - `.claude/skills/` holds real file copies (not symlinks) of the dev skills, kept aligned by the `chore(auto): sync skills/docs` automation — either rely on that sync or update the copies in the same change so the diff stays clean.
- User skills under `ak-py/src/agentkernel/skills/`: `ak-add-capabilities/SKILL.md` (includes `agent_reply.text += ...`). `ak-build/SKILL.md` only describes `AgentReplyAny.content` / `str(reply)` — it changes only if the `content` rename open question resolves to yes.
- Source docstrings that name the field: `core/model.py` (field descriptions at :13, :93, :95, :108). (`core/hooks.py`, `core/runtime.py:194`, and `core/service.py:144` say "text prompt"/`content` only as prose — no field rename there; `crewai.py`'s `.text` usages are code already covered under the framework runners above.)
- Examples: `examples/api/hooks/*`, `examples/api/openai/app.py`, `examples/api/openai_structured/*`, `examples/cli/openai_structured/*`, `examples/memory/key-value-cache/hooks.py:38-39` (includes `agent_reply.text` mutation examples).

## Non-goals

- Not renaming `BaseChatRequest.prompt` / `BaseRunRequest.prompt` — already named correctly; only the internal model changes.
- Not renaming unrelated `text`/`content` occurrences: `ThreadMessage.content`, external SDK/LLM payload keys (LiteLLM `{"type": "text"}`, Slack/WhatsApp/Bedrock payloads), knowledge-base result dicts, httpx `response.text`.
- Not restructuring the `AgentReplyText → AgentRequestText` inheritance relationship beyond the field rename.
- Not changing any behaviour: reply/response payload shapes, structured-output semantics, guardrail masking logic, and `str()` renderings stay identical.
- Not editing frozen versioned doc snapshots under `docs/versioned_docs/version-*` (subject to the scope open question below).

## Resolved decisions

All five questions below were resolved on the AK-166 ticket (approved there before this branch landed); the recommended answers were adopted.

- **`AgentReplyAny.content` keeps its name** (not renamed to `response`). `AgentReplyAny`'s output is a `dict` named `content`, semantically distinct from the text-reply field; renaming would ripple into `from_output`, `walledai.py:204`, and many `reply.content` tests/docs for no benefit.
- **Third-clause interpretation confirmed.** "Replace any remaining prompt fields in reply models with response where applicable" resolves the `AgentReplyText` inheritance conflict by giving it an explicit `response` output field while the inherited field carries `prompt` (input). No reply field that holds *input* is renamed to `response`.
- **Backward compatibility: clean break** (no Pydantic aliases / deprecation shims). External users construct/read these models directly (`AgentRequestText(text=...)`, `agent_reply.text`), so this is a breaking change, shipped with a version/changelog note. Approved on AK-166 — this satisfies the maintainer sign-off the plan's prerequisite calls for.
- **Reply `prompt` field stays optional** (`prompt: str = ""`) to preserve current construction ergonomics.
- **Versioned doc snapshots excluded** (`docs/versioned_docs/version-*` — historical archives of past releases are left untouched).
