# #762: Port the A2A surface to a2a-sdk 1.x, and send structured replies as data parts — Implementation Plan

Builds [spec.md](spec.md) in six iterations. The pin bump and the port cannot be split (0.3 code
does not import on 1.x), so iteration 2 is the one large step; everything else is small.

## Iteration 1: A2UI scope helpers

- **Goal:** `a2ui/` can answer "is this agent labelled?" by name, and owns the extension URI. No
  A2A change yet; runs on 0.3.
- **Files:** `ak-py/src/agentkernel/a2ui/hook.py`, `ak-py/tests/test_a2ui_hook.py`
- **Steps:**
  1. Add `A2UIPostHook.EXTENSION_URI` and `A2UIPostHook.scopes(agent_name)`; make `_applies_to`
     delegate to it (spec §3).
  2. Add `A2UIPostHookFactory.labels(agent_name)` with `get()`'s fallback (spec §3).
  3. Tests for `scopes`, `labels` (disabled, out of scope, in scope, raising config).
- **Verify:** `cd ak-py && uv run pytest tests/test_a2ui_hook.py tests/test_cross_surface_parity.py`

## Iteration 2: Port to a2a-sdk 1.2.3 (behaviour-preserving where 1.x allows)

- **Goal:** the A2A surface imports and serves on 1.2.3; text replies and failures work through
  the queue; 0.3 routes are gone.
- **Files:** `ak-py/pyproject.toml`, `ak-py/uv.lock`, `ak-py/src/agentkernel/core/builder.py`,
  `ak-py/src/agentkernel/api/a2a/a2a.py`, `ak-py/src/agentkernel/api/a2a/handler.py`,
  `ak-py/tests/test_api_a2a.py`, `ak-py/tests/test_protocol_pipeline_roundtrip.py`
- **Steps:**
  1. Pin `a2a-sdk[http-server]==1.2.3`; `uv lock --upgrade-package a2a-sdk` (spec §1).
  2. `A2ACardBuilder`: `supported_interfaces`, `_description`, `_tag_untagged`; modes and
     extension still as today until iteration 3 (spec §2).
  3. Executor: 1.x helpers by keyword, `InternalError(message=...)`, `UnsupportedOperationError()`,
     delete `_send_error`; `_build` skips a `None` card (spec §4). Text-only replies for now.
  4. Handler: `DefaultRequestHandler(..., agent_card=card)`, `create_rest_routes` +
     `create_agent_card_routes` via `_add_route`; catalog through `agent_card_to_dict`; delete the
     dynamic card router; rewrite the docstring route list (spec §5).
  5. Port `test_api_a2a.py` (1.x `RequestContext`, `RecordingEventQueue`, failure rows) and
     `_a2a_send` in the round-trip test (spec Testing, Changed files). Labelled rows still expect
     JSON text in this iteration.
- **Verify:** `uv run pytest tests/test_api_a2a.py tests/test_protocol_pipeline_roundtrip.py tests/test_api_http.py tests/test_pipeline_io_handler.py`

## Iteration 3: Data parts and the A2UI card

- **Goal:** a labelled reply leaves as a data part; cards carry media-type modes and the A2UI
  extension for in-scope agents.
- **Files:** `ak-py/src/agentkernel/a2ui/hook.py`, `ak-py/src/agentkernel/api/a2a/a2a.py`,
  `ak-py/src/agentkernel/core/builder.py`, `ak-py/tests/test_api_a2a.py`,
  `ak-py/tests/test_a2ui_hook.py`, `ak-py/tests/test_api_a2a_surface.py` (new, card tests)
- **Steps:**
  1. `EXTENSION_URI` → v0.9.1 (D6); `A2UIPostHook.a2a_data` (D8) (spec §3).
  2. `Executor._as_message` per the D3/D7/D8 table (spec §4).
  3. `A2ACardBuilder.build`: `text/plain` modes, and `labels(name)` → A2UI output mode +
     `AgentExtension` (spec §2, rule 1).
  4. Move the labelled rows to `TestDataParts` (both labels, the list wrap, `1` → `1.0`); card
     tests start `test_api_a2a_surface.py`.
- **Verify:** `uv run pytest tests/test_api_a2a.py tests/test_api_a2a_surface.py tests/test_a2ui_hook.py`

## Iteration 4: Examples

- **Goal:** both example clients run against a 1.x server.
- **Files:** `examples/api/a2a/multi/client.py`, `examples/api/a2a/multi/pyproject.toml`,
  `examples/api/a2a/multi/uv.lock`, `examples/k8s/openai-queue-mode/protocol_client.py`,
  `examples/k8s/openai-queue-mode/pyproject.toml` (its `uv.lock` is git-ignored)
- **Steps:**
  1. Port both clients to the 1.x shape in spec [Consumer changes](spec.md#consumer-changes).
  2. k8s pin `==1.2.3`; multi gains the `api` extra (spec §1); re-lock both.
- **Verify:** `cd examples/api/a2a/multi && ./build.sh local && uv run pytest -s a2a_test.py` (needs
  `OPENAI_API_KEY`); `make lint-check-all`.

## Iteration 5: Tests

- **Goal:** every behaviour in spec [Behavioural changes](spec.md#behavioural-changes) has a test.
- **Files:** `ak-py/tests/test_api_a2a_surface.py` (card tests already in, from iteration 3),
  `ak-py/tests/test_protocol_pipeline_roundtrip.py`, `ak-py/tests/test_cross_surface_parity.py`,
  `ak-py/tests/test_packaging_extras.py`
- **Steps:**
  1. `test_api_a2a_surface.py`: add the imports and routes classes (spec Testing, New file).
  2. Round trip: `/v1/message:send` → 404; labelled reply through the queue as a data part
     (reset `Runtime._system_post_hooks`).
  3. Parity: `test_a2a_carries_the_same_pair`; A2A joins the all-surfaces test; drop the
     "sits out" docstring.
  4. Packaging: the `a2a` extra is exactly `==1.2.3`.
- **Verify:** the spec's [Run](spec.md#run) commands; full `uv run pytest` green.

## Iteration 6: Sync docs and skills

- **Docs:**
  - `docs/docs/api/a2a-server.md:85-95`: 1.0 route table, data-part sentence, 0.3 migration note.
  - `docs/docs/advanced/a2ui.md:82`: A2A row → supported as a data part.
- **Dev skills:**
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md:51` (`test_a2ui_hook.py`: `scopes`/`labels`),
    `:52` (parity: A2A no longer sits out), `:95` (`test_api_a2a.py`: data parts, no text message on
    failure), `:129` (packaging: the a2a pin), `:152` (round trip: 1.x client, 404, data part); add
    a row for `test_api_a2a_surface.py`.
  - `.agents/skills/ak-dev-architecture/SKILL.md:994` (`a2a/` line: a2a-sdk 1.x, labelled replies
    as data parts); the A2UI directory note near `a2ui/` (owns `EXTENSION_URI` and `labels`).
  - `.agents/skills/ak-dev-new-framework-integration/SKILL.md:284`: `description` should be a
    `str`; empty skill tags are filled by the builder.
- **Bundled user skill:** `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:563` — the
  well-known path is wrong today (`/.well-known/agent.json`); make it
  `/a2a/{agent}/.well-known/agent-card.json` and say callers need an a2a-sdk 1.x client.
  Its example `a2a.url` (`http://localhost:8000`) also loses the `/a2a` base, which 1.x clients
  would now call; and `evals/evals.json` (`cap-a2a`) expects the card path.
- **No update needed (verified):** `docs/versioned_docs/version-0.*/api/a2a-server.md` (they
  document released versions, which do serve `/v1/`);
  `ak-py/README.md:997-1013` (A2A config fields unchanged);
  `examples/api/a2a/multi/README.md` and `examples/k8s/openai-queue-mode/README.md` (no 0.3 route
  or SDK-version text).
- **Verify:** run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows
  before merge; `make lint-check-all`.
