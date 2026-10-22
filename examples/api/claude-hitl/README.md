# Claude human approval example

This example shows one Claude Agent SDK tool call pausing for a human decision. `issue_refund` is
a demo tool: it logs when it runs and **does not move money**. It is bound with
`needs_approval=True`, so the first request should return a paused reply before the tool runs.
The app explicitly uses Agent Kernel's direct REST handler, the same one used by
`examples/api/hitl`, so a resume request needs no prompt.

## Run

Set Claude credentials, then install this branch's Agent Kernel package and start the API:

```bash
export ANTHROPIC_API_KEY=...
cd ak-py && uv build && cd ../examples/api/claude-hitl
./build.sh local
uv run app.py
```

Run the commands from the repository root. You can also use a configured Bedrock, Vertex, or
Foundry provider instead of an Anthropic API key. Use `./build.sh` for a published Agent Kernel
version that includes this Claude adapter.

## Try an approval

In another terminal, ask for a demo refund:

```bash
curl -i http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"claude-hitl-1","agent":"support","prompt":"Refund order ORD-1001."}'
```

Expect **HTTP 202** with `status: "PAUSED"`. The response contains one interruption with
`tool_name: "issue_refund"`, its `arguments`, and an `id`. The server should **not** log
`DEMO REFUND EXECUTED` yet.

Copy that interruption's `id` into the next request:

```bash
curl -i http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"claude-hitl-1","agent":"support","resume":{"decisions":[{"id":"PASTE_INTERRUPTION_ID","status":"approved"}]}}'
```

The resumed run should call `issue_refund` once. Look for one `DEMO REFUND EXECUTED for ORD-1001`
line in the server log. To try denial, start with a **new** `session_id`, then send a decision with
`"status":"denied"` and `"message":"Refund not permitted"`. No execution log should appear.

The Claude runner uses the SDK's `PreToolUse` hook to pause the call. On approval it resumes the
Claude conversation and gives the tool handler one matching permission through
`_ClaudeApprovalGuard`. That guard refuses an unapproved call even if Claude does not pause it.
The SDK only honors `defer` when Claude makes one tool call in a turn; the prompt asks for one.
This live run is the check for the exact SDK pause and replay behavior that the adapter's fake
client tests cannot prove.

The example uses an in-memory session store, so keep the API process running between the two
requests. For a restart or multiple workers, configure a shared session store such as Redis.
