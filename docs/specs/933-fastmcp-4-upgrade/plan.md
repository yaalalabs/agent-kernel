# #933: Upgrade the MCP server to FastMCP 4 — Implementation Plan

Four short iterations. Each one leaves the branch green. Details are in [spec.md](spec.md).

## Iteration 1: Dependencies and server code

- **Goal:** AK runs on FastMCP 4, and the existing MCP tests pass.
- **Files:**
  - `ak-py/pyproject.toml`
  - `ak-py/uv.lock`
  - `ak-py/build.sh` (comment only)
  - `api/mcp/akmcp.py`
  - `core/config.py`
  - `tests/test_api_mcp.py`
  - `tests/test_api_mcp_auth.py`
  - `tests/test_cross_surface_parity.py`
  - `tests/conftest.py`
- **Steps:**
  1. Change the pin, add the conflict entry, then run `uv lock` and `./build.sh` (spec: Dependencies).
  2. In `akmcp.py`, fix the `ToolResult` import, drop `ctx`, and replace the two `ctx` log calls
     with `self.log.debug` (spec: MCP server).
  3. Reword the `stateless_http` description (spec: Config changes).
  4. Fix the tests:
     - the `ToolResult` imports;
     - the 12 `execute(...)` call sites;
     - `httpx` → `httpx2`, moving `_http_factory` into the `mcp_asgi_transport` fixture in
       `conftest.py`.
- **Verify:** `uv run pytest tests/test_api_mcp.py tests/test_api_mcp_auth.py tests/test_protocol_pipeline_roundtrip.py tests/test_cross_surface_parity.py`

## Iteration 2: New protocol test

- **Goal:** prove that both protocol versions work, and that AK raises no deprecation warning.
- **Files:** `tests/test_api_mcp.py`
- **Steps:** add `TestProtocolVersions`, with 4 cases covering `mode` × `stateless_http`
  (spec: New test).
- **Verify:**
  - `uv run pytest tests/test_api_mcp.py -k TestProtocolVersions`
  - then the full `uv run pytest` and `make lint-check`.

## Iteration 3: Examples

- **Goal:** the example clients work against a 2026-07-28 server.
- **Files:**
  - `examples/api/mcp/multi/client.py`
  - `examples/aws-containerized/mcp/multi/client.py`
- **Steps:** delete the `ping()` asserts. Do not re-lock the example projects (spec: Examples and CI).
- **Verify:**
  - `make lint-check-all`;
  - `chart-test.yaml` passes on the PR;
  - run `examples/api/mcp/multi` locally once, against the branch wheel.

## Iteration 4: Sync docs and skills

- **Goal:** the docs state the supported protocol versions, the `crewai`/`mcp` conflict and the new
  `stateless_http` meaning.
- **Files:** everything in the spec's Docs and skills table.
- **Steps:**
  1. Apply each row of the table, and add the changelog fragments `changelog.d/933.added.md` and
     `changelog.d/933.breaking.md`.
  2. Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows, to catch
     anything the table missed.
- **Verify:**
  - `git grep -n -F -e 'fastmcp.tools.tool' -e 'await client.ping()' -- ak-py/src docs/docs examples .agents`
    returns nothing (`-F` and `await` keep out the Redis driver's own `client.ping()`, and the
    `mcp-server.md` note naming `fastmcp.Client.ping()` on purpose);
  - `git grep -n stateless_http -- docs/docs .agents ak-py/src/agentkernel/skills` shows only
    reworded lines.

## After merge

- The next release re-locks the MCP examples onto FastMCP 4, through the release workflow.
- From then on, the k8s smoke test runs on FastMCP 4.
- The weekly e2e runs confirm that the gateways pass `Mcp-Method` and `Mcp-Name` through.
