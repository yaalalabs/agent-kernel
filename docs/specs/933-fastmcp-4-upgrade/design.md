# #933: Upgrade the MCP server to FastMCP 4 (MCP protocol 2026-07-28)

Agent Kernel's MCP server moves from FastMCP 3 to FastMCP 4. One server then answers both new
2026-07-28 clients and older 2025-11-25 clients. The code change is small. Most of the work is the
CrewAI dependency conflict, tests, examples and docs.

_Evidence at `develop` @ `696fb287`. Paths are relative to `ak-py/src/agentkernel/` unless they start
with a top-level folder. Upstream versions were checked on PyPI on 2026-11-24._

## At a glance

| | Today | After this change |
|---|---|---|
| `mcp` extra | `fastmcp>=3.4.10,<4.0.0` (locked 3.4.11) | `fastmcp>=4.2,<5` |
| MCP Python SDK | `mcp` 1.30.0 | `mcp` 2.3.x |
| Protocol versions served | up to 2025-11-25 | 2026-07-28 **and** 2025-11-25 |
| `agentkernel[crewai,mcp]` together | installs | **does not install** (declared conflict) |
| Configuration | `mcp.*` | Same fields. Only the `stateless_http` description changes |

- No new classes, no new config, and no change to the reply shapes clients see.

## Why

- MCP has a new protocol, 2026-07-28. It drops sessions: there is no `initialize` handshake and no
  `Mcp-Session-Id` header, so any server replica can answer any request.
- FastMCP 4 (now 4.2.5) and MCP SDK 2 (now 2.3.0) are the releases that speak it. FastMCP 3 tops out
  at 2025-11-25.
- AK does not need sessions anyway. Agent tools take `session_id` as an argument
  (`api/mcp/akmcp.py:67`), so conversation state never depended on `Mcp-Session-Id`.

## What we checked

We ran a small FastMCP 4.2.5 server, shaped like AK's, under uvicorn and called it with both client
modes. Each of the three tool shapes was called in both `stateless_http` settings.

| Check | New client (`mode="auto"`) | Old client (`mode="legacy"`) |
|---|---|---|
| Protocol agreed | 2026-07-28 | 2025-11-25 |
| Text tool, same `session_id` twice | works | works |
| Array reply (`wrap_result`) | client gets the array back | client gets the array back |
| `client.ping()` | **raises** `MCPError: Method not found` | works |
| `ctx.info()` on the server | `MCPDeprecationWarning` | `MCPDeprecationWarning` |

- Under the new protocol, the client also sees an extra `_meta` key, `io.modelcontextprotocol/serverInfo`.
  AK's own `_meta` keys are unchanged.
- All AK imports still exist in FastMCP 4 except one: `fastmcp.tools.tool` is gone, and `ToolResult`
  now imports from `fastmcp.tools`.
- FastMCP 4's HTTP client is `httpx2`, not `httpx`.
- Host/Origin checking is off by default in FastMCP 4 (`http_host_origin_protection = False`), so
  servers behind a load balancer keep working.

## What users will notice

- MCP clients on the 2026-07-28 protocol can now connect. Older clients keep working as before.
- `agentkernel[crewai,mcp]` no longer installs, because every CrewAI release pins `mcp<2`.
  - Latest `crewai` 1.15.45 (2026-11-24): `mcp>=1.30.0,<2`.
  - The upstream request to support MCP 2 (crewAIInc/crewAI#6750) was closed as not planned on
    2026-10-07.
  - No AK example or docs install line combines `crewai` with `mcp` today.
- `ping()` from a `fastmcp.Client` fails on the new protocol. Client code that uses it as a health
  check has to stop calling it or use `mode="legacy"`.
- With several IO replicas, `mcp.stateless_http: true` is needed only for older clients. New clients
  are always stateless.

## What changes

### Dependencies

- In `ak-py/pyproject.toml:207`, change the `mcp` extra to `fastmcp>=4.2,<5`, then run `uv lock`.
- Add `[{ extra = "crewai" }, { extra = "mcp" }]` to `[tool.uv] conflicts` (`ak-py/pyproject.toml:249`).
  This is the same pattern as the existing `crewai`/`test` entry, with a one-line comment on why.
- `openai-agents` (`mcp<3,>=1.19.0`) and `claude-agent-sdk` (`mcp<3.0.0,>=1.23.0`) already accept
  SDK 2, so neither pin changes.

### MCP server (`api/mcp/akmcp.py`)

- Change the `ToolResult` import from `fastmcp.tools.tool` to `fastmcp.tools` (`akmcp.py:8`).
- Replace `ctx.info` and `ctx.debug` (`akmcp.py:93`, `:111`) with the executor's own `self.log`.
  - MCP logging is deprecated and raises `MCPDeprecationWarning` on every call.
  - Log at `debug` level, with the agent and session id. Do not log prompt or reply text at `info`.
  - Drop the now-unused `ctx` parameter from `Executor.execute`.
- No other change: `http_app(path="/", stateless_http=...)` (`akmcp.py:141`) keeps the same signature.
- `api/mcp/auth.py` needs no change. All four of its imports exist in FastMCP 4.

### Configuration (`core/config.py`)

- Keep `mcp.stateless_http` (`core/config.py:177`), with the same default (`false`).
- Reword its description: it applies only to older (2025-11-25) clients. 2026-07-28 clients are
  always stateless.

### Tests

- Update the `ToolResult` import in `tests/test_api_mcp.py`, and update the `execute(...)` call sites
  that pass `ctx`.
- In `tests/test_api_mcp_auth.py:242`, build the client factory with `httpx2.AsyncClient` and
  `httpx2.ASGITransport`, which FastMCP 4's HTTP transport now expects.
- New test: a `mode="auto"` client and a `mode="legacy"` client each call one agent tool and one app
  tool over HTTP.
  - Both get the same reply. Two calls with the same `session_id` share the session.
- New assertion: running the executor raises no `MCPDeprecationWarning`.
- `test_api_mcp.py`, `test_api_mcp_auth.py`, `test_protocol_pipeline_roundtrip.py` and
  `test_cross_surface_parity.py` all pass on FastMCP 4.

### Examples and CI

- `examples/api/mcp/multi/client.py:20` and `examples/aws-containerized/mcp/multi/client.py:20`:
  remove the `assert await client.ping()` startup check, which raises on the new protocol.
- `examples/k8s/openai-queue-mode/protocol_client.py:58` needs no code change. It only calls
  `call_tool`. It runs in `chart-test.yaml:250` and must pass.
- Do not re-lock the example projects in this PR. They resolve `agentkernel` from PyPI, which still
  pins `fastmcp<4`, so the release workflow re-locks them after the next release. Until then the
  k8s smoke test runs the branch code on FastMCP 3.4.11, which the new import also supports.

### Docs and skills

- `docs/docs/api/mcp-server.md`:
  - Add a line naming the supported protocol versions: 2026-07-28 and 2025-11-25.
  - Reword the load-balancer note (`:101`) on `stateless_http` to say it is for older clients only.
- `docs/docs/installation.md`: note that `crewai` and `mcp` cannot be installed together, and why.
- `.agents/skills/ak-dev-testing-conventions/SKILL.md:133`: update the line about the FastMCP 3
  constructor and describe the new two-client test.
- `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:588`: same `stateless_http` rewording.
- `ak-dev-architecture`: state the supported protocol versions where it describes the MCP surface.

## Non-goals

- New protocol features: multi round-trip requests, the tasks extension, `server/discover` and cache TTLs.
- MCP streaming (#196) and MCP on Lambda (#932).
- Removing or deprecating `mcp.stateless_http`. Older clients still use it.
- Gateway changes. API Gateway, ALB, APIM and ingress forward unknown headers by default, so
  `Mcp-Method` and `Mcp-Name` need no new configuration. The e2e runs confirm this, and nothing is
  added up front.

## Decisions

- **CrewAI:** declare the conflict and upgrade now. `crewai` and `mcp` are not installed together.
  - We did not wait on FastMCP 3, because upstream has no plan for MCP 2 support (crewAIInc/crewAI#6750).
- **Gateways:** no changes up front. The AWS, Azure and GCP e2e runs prove that `Mcp-Method` and
  `Mcp-Name` pass through. A template is fixed only if a run fails.

## Open questions

- None.
