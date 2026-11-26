# #933: Upgrade the MCP server to FastMCP 4 — Implementation Spec

How the change in [design.md](design.md) gets built. It is a dependency bump plus a handful of small edits:
one import, two log calls, one config description, the test fixes that FastMCP 4 forces, one new
test, two example lines, and docs.

_Evidence at `develop` @ `696fb287`. Paths are relative to `ak-py/src/agentkernel/` unless they start
with a top-level folder._

## How this spec was checked

Every claim below was checked by running it, not just by reading the code:

- **Lock:** a scratch copy of `ak-py/pyproject.toml` with the new pin and the conflict entry ran
  `uv lock` cleanly. It resolved `fastmcp` 4.2.0 and `mcp` 2.3.0, with `mcp` 1.28.1 kept for the
  `crewai` fork. The same copy **without** the conflict entry fails: "your project's requirements
  are unsatisfiable".
- **Tests:** an editable install of this branch with `fastmcp==4.2.5` forced in. `test_api_mcp.py`,
  `test_api_mcp_auth.py`, `test_protocol_pipeline_roundtrip.py` and `test_cross_surface_parity.py`
  give:
  - as-is: collection fails on `fastmcp.tools.tool`;
  - with only that import fixed: 67 passed, 1 failed (the `httpx` client factory in the auth test);
  - with the factory moved to `httpx2`: all pass.
- **Old FastMCP:** `from fastmcp.tools import ToolResult` also works on FastMCP 3.4.11. This matters
  for the k8s smoke test (see [Examples and CI](#examples-and-ci)).
- **New test shape:** the two-client test below was run as a prototype (4 cases, all pass).

## Design

### Dependencies (`ak-py/pyproject.toml`)

- `mcp` extra (`:206-208`):

  ```toml
  mcp = [
      "fastmcp>=4.2,<5"
  ]
  ```

- `[tool.uv] conflicts` (`:249`): add a second entry, with a comment in the same style as the first.

  ```toml
  # crewai pins mcp<2 in every release (crewAIInc/crewAI#6750 closed, not planned) and fastmcp 4 needs mcp>=2.3
  [
      { extra = "crewai" },
      { extra = "mcp" },
  ],
  ```

- Run `uv lock` in `ak-py/`. The expected lock diff is `fastmcp`/`fastmcp-slim` going to 4.2.x,
  `mcp` going to 1.28.1 + 2.3.0, and `mcp-types` being added (`httpx2` was already locked). Some transitive packages
  that only FastMCP 3 pulled in (`keyring` and its deps) are dropped.
- `ak-py/build.sh:12-13` already runs `uv sync --all-extras --no-extra crewai`, so the dev and CI
  environment installs `mcp` without `crewai` and needs no change. Only the comment on line 12
  changes, to say that `crewai` also conflicts with `mcp`.
- `openai-agents` (`mcp<3,>=1.19.0`) and `claude-agent-sdk` (`mcp<3.0.0,>=1.23.0`) need no change.

### MCP server (`api/mcp/akmcp.py`)

- Imports (`:4`, `:8`):

  ```python
  from fastmcp import FastMCP            # Context is no longer used
  from fastmcp.tools import ToolResult   # was fastmcp.tools.tool (gone in 4.x; also valid in 3.x)
  ```

- `Executor.execute` (`:67`) loses the `ctx` parameter:

  ```python
  async def execute(self, session_id: str, prompt: str) -> Any:
  ```

  - FastMCP builds a tool's input schema from its parameters and leaves out `Context` ones. Dropping
    `ctx` therefore leaves the published schema unchanged: `session_id` and `prompt`.
- Replace `await ctx.info(...)` (`:93`) with one server-side line, and delete `await ctx.debug(...)`
  (`:111`):

  ```python
  self.log.debug(f"Executing agent '{self.agent_name}' for session_id={session_id}")
  ```

  - Prompt and reply text are no longer logged anywhere. Before this change they went to the MCP
    client, which already had them, and never to the server log.
- Nothing else changes. `http_app(path="/", stateless_http=...)` (`:141`) has the same signature in
  4.x, and `FastMCP(name, auth=...)` (`:149`), `ToolError` and `get_access_token` are unchanged.
- `api/mcp/auth.py` needs no change. Its imports (`AuthProvider`, `RemoteAuthProvider`,
  `TokenVerifier`, `mcp.server.auth.provider.AccessToken`) all exist in 4.x, and its tests pass.

### Consumer changes

- `agentkernel.mcp` (`mcp.py:8`) re-exports `api.mcp` unchanged.
- Callers of `MCP.Executor.execute` are FastMCP itself and the tests listed below. No other code
  calls it (`git grep 'execute('` over `ak-py/src`).

### Config changes

- `_MCPConfig.stateless_http` (`core/config.py:177-181`): same name, type and default (`False`).
  Only the description changes:

  ```python
  description="Serve older (2025-11-25) MCP clients statelessly: each request is independent "
  "(no Mcp-Session-Id), so any replica can answer it. Set it when more than one replica serves /mcp. "
  "2026-07-28 clients are always stateless and are not affected. "
  "Trade-off for older clients: server-side session features (sampling, mid-call notifications) are unavailable.",
  ```

- No new fields. Existing YAML and `AK_MCP__*` env vars load unchanged.

### Behavioural changes

1. **New protocol served.** 2026-07-28 clients can connect, and 2025-11-25 clients keep working. The
   version is agreed per connection by FastMCP 4. Intentional: this is the point of #933.
2. **`crewai` + `mcp` can no longer be installed together.** Intentional: this is the design decision.
3. **No MCP log messages reach the client.** The executor sent one `info` and one `debug`
   notification per call. Intentional: the logging capability is deprecated, and no AK test or
   example reads these messages.
4. **`ping()` fails on 2026-07-28 connections.** This comes from FastMCP 4, not from AK. AK's own
   example clients stop calling it.
5. **Extra `_meta` key on 2026-07-28 replies.** FastMCP 4 adds `io.modelcontextprotocol/serverInfo`
   to tool result `_meta`. AK's `media_type` and `fastmcp.wrap_result` keys are unchanged.

**Non-changes:**

- Tool names, descriptions and input schemas.
- Reply shapes: text, a labelled object as `structuredContent`, a labelled array wrapped under
  `result` with `fastmcp.wrap_result`, and image replies as text.
- The fixed `ToolError` messages.
- Auth: 401s and principal hand-off.
- The `mcp.*` config fields and defaults.

## Error handling

- No new failure paths. The executor's `try/except` around `RestHandler.request` (`akmcp.py:98-109`)
  is untouched, so a timeout and every other failure still raise `ToolError` with the fixed messages.
- A missing `mcp` extra fails the same way as before, with an `ImportError` on `fastmcp`.

## Testing

Run: `cd ak-py && uv run pytest tests/test_api_mcp.py tests/test_api_mcp_auth.py tests/test_protocol_pipeline_roundtrip.py tests/test_cross_surface_parity.py`,
then the full `uv run pytest`.

### Existing tests that change

| File | Change |
|---|---|
| `tests/test_api_mcp.py` | `:118`, `:166` import `ToolResult` from `fastmcp.tools`. Drop the third `AsyncMock()` argument from `execute(...)` at `:127`, `:141`, `:153`, `:175`, `:218`, `:232`, `:253`. Remove `AsyncMock` imports that become unused |
| `tests/test_api_mcp_auth.py` | `import httpx` → `import httpx2` (`:13`), and use it in `_http_factory` (`:242-246`) and the raw 401 request (`:288`). FastMCP 4's `StreamableHttpTransport` rejects an `httpx` client and its auth (`Invalid "auth" argument`). Drop the `AsyncMock()` argument at `:210`, `:221`, `:233` |
| `tests/test_cross_surface_parity.py` | Drop the `AsyncMock()` argument at `:147`, `:189` |

- `_http_factory` moves to `tests/conftest.py` as the fixture `mcp_asgi_transport`. It returns
  `StreamableHttpTransport("http://mcp.test/", ..., httpx_client_factory=...)` over an ASGI app.
  The auth tests and the new test below both use it.
- `test_protocol_pipeline_roundtrip.py` needs no edit. It already proves the session carries across
  calls through `session_id`, over a real `Client(MCP.get())`.

### New test: `TestProtocolVersions` in `tests/test_api_mcp.py`

- Parametrized over `mode` (`"auto"` expecting `"2026-07-28"`, `"legacy"` expecting `"2025-11-25"`)
  and `stateless_http` (`True`, `False`): 4 cases.
- Server: `FastMCP(MCP_NAME)` with:
  - one agent tool, `MCP.Executor("a").execute`, answered by `FakeClient` (`_queue_reply`);
  - one app tool, a plain function `def add(x: int) -> int`.
- Served by `http_app(path="/", stateless_http=...)` inside its lifespan, and reached through
  `mcp_asgi_transport`.
- Asserts:
  - `client.protocol_version` is the expected version;
  - two agent-tool calls with `session_id="s1"` return the runner's text, and both queued bodies
    carry `session_id == "s1"`;
  - the app tool returns `x + 1`;
  - no `MCPDeprecationWarning` is raised. The calls run under
    `warnings.simplefilter("error", MCPDeprecationWarning)`, with the warning imported from
    `mcp.shared.exceptions`.

### Not covered by unit tests

- `Mcp-Method` and `Mcp-Name` passing through a real gateway. That is the AWS, Azure and GCP e2e
  runs' job (see the design's Decisions section).

## Examples and CI

- `examples/api/mcp/multi/client.py:20` and `examples/aws-containerized/mcp/multi/client.py:20`:
  delete `assert await client.ping()`. `list_tools()` on the next line already proves the server
  answers, on both protocols.
- `examples/k8s/openai-queue-mode/protocol_client.py` needs no change, since it only calls
  `call_tool`.
- **Example locks are not re-locked in this PR.** This corrects the design.
  - Each example resolves `agentkernel` from PyPI, whose last release still pins `fastmcp<4`, so its
    lock cannot move to FastMCP 4 until the next release. The release workflow bumps and re-locks
    them then (`ak-dev-code-quality`, `lock-bounds-check`).
  - Until then, `chart-test.yaml`'s dev smoke (`deploy/package.sh local`) installs the example lock
    (FastMCP 3.4.11) and force-installs the branch wheel with `--no-deps`
    (`examples/k8s/openai-queue-mode/deploy/package.sh:51-55`).
  - That still works, because the new `ToolResult` import is valid on 3.4.11 and the removed `ctx`
    is never passed by callers. But it means the smoke runs on FastMCP 3 until the release.
  - `make lock-bounds-check` will report the three MCP example locks as drifting from
    `fastmcp>=4.2`. That report is expected, and the release closes it.

## Docs and skills

| Surface | Change |
|---|---|
| `docs/docs/api/mcp-server.md` | Add a "Protocol versions" line: 2026-07-28 and 2025-11-25, agreed per connection. Reword `:101` so `stateless_http` applies to older clients only. Update the `:158` comment to match |
| `docs/docs/core-concepts/configuration.md` | Update the `stateless_http` comments at `:70` and `:1072` to match the new description |
| `docs/docs/installation.md` | Under "Dependency Conflicts" (`:282`), add: `crewai` and `mcp` cannot be installed together, and why |
| `docs/docs/deployment/onprem-kubernetes.md:45` | Say that `mcp.stateless_http` is for older clients when several IO replicas run |
| `.agents/skills/ak-dev-testing-conventions/SKILL.md:133` | Add `TestProtocolVersions` to the `test_api_mcp.py` row, and note that the auth tests' ASGI transport uses `httpx2` |
| `.agents/skills/ak-dev-architecture/SKILL.md` | Name the supported protocol versions where the MCP surface is described |
| `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:588` | Same `stateless_http` rewording |

- `docs/versioned_docs/**` is left alone, since those pages are frozen snapshots of past releases.
