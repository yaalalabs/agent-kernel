# Release notes draft: #612 ChatService refactor and thread integration

Paste-ready material for the GitHub release that ships #612 (all five PRs land in the same release).

## Breaking changes

**Conversation Thread Support is now enabled by mounting a handler, not by config presence.**
Thread support is packaged as an integration (like Slack or WhatsApp): mounting
`AgentThreadRequestHandler` is what enables it, and it serves the standard chat routes (with thread
recording) plus the thread read routes in one handler. The `thread:` block in `config.yaml` only
selects the store backend and naming model; its presence no longer activates anything on its own.

Before:

```python
from agentkernel.api import RESTAPI, AgentRESTRequestHandler, ThreadRESTRequestHandler

# thread block in config.yaml enabled recording everywhere; read routes were auto-mounted
RESTAPI.run(handlers=[AgentRESTRequestHandler(), ThreadRESTRequestHandler(authoriser=MyAuthoriser())])
```

After:

```python
from agentkernel.api import RESTAPI
from agentkernel.thread import AgentThreadRequestHandler

RESTAPI.run(handlers=[AgentThreadRequestHandler(authoriser=MyAuthoriser())])
```

1. **Thread recording only happens through `AgentThreadRequestHandler`.** The plain REST handler and
   the deployment adapters (AWS Lambda REST/WebSocket, ECS queue and direct-WebSocket modes, Azure
   Functions) no longer record conversation threads when a `thread:` block is present. Threads are
   the history mechanism for clients that connect to the agent directly; messaging platforms keep
   their own native history.
2. **`user_id` is no longer required on non-thread chat requests.** Previously, adding a `thread:`
   block made every chat surface reject requests without `user_id`. That requirement now applies
   only to the thread handler's routes.
3. **Thread read routes are no longer auto-mounted.** `GET /api/v1/threads*` appears only where
   `AgentThreadRequestHandler` (or `ThreadRESTRequestHandler`) is mounted.
4. **Import paths moved.** `agentkernel.api.ThreadRESTRequestHandler` and the whole
   `agentkernel.core.thread` module no longer exist. Everything thread-related is importable from
   `agentkernel.thread` (alias of `agentkernel.integration.thread`): `AgentThreadRequestHandler`,
   `ThreadRESTRequestHandler`, `ThreadRecorder`, `ConversationThreadManager`, `Authoriser`,
   `ThreadNamingStrategy`, `ThreadStore`, `ThreadStoreBuilder`, and the thread models. Thread store
   data layouts are unchanged; existing stored threads read back identically.

## Improvements

- **ChatService execution core.** `ChatService` now exposes transport-neutral `execute`,
  `execute_sync`, `execute_stream`, and `execute_stream_sync` methods returning typed replies and
  raw `StreamChunk`s, with support for caller-built request lists (attachment-only messages
  included). The HTTP-shaped `process_*` methods are unchanged wrappers over this core.
- **All seven messaging integrations (Slack, WhatsApp, Messenger, Instagram, Telegram, Teams,
  Gmail) route through the ChatService core** instead of using `AgentService` directly, with
  handler-level unit test suites added (previously none existed). Platform behavior is unchanged.
- **Fixed: phantom thread writes.** On streaming chat with threads enabled, a request naming a
  missing agent used to record a user message (and create a thread) before failing; agent
  availability is now checked before any thread write on every path.
- **Fixed: error-payload asymmetry.** Synchronous chat error responses now include `session_id`
  whenever the request carried one, matching the async path.
- **Consistency: empty-string `session_id`** is now rejected with 400 on all paths (previously
  accepted by the synchronous path only).

## Notes for maintainers

- Behavioral details and the full change inventory: `docs/specs/612-chatservice-refactor/spec.md`
  (Behavioural changes, items 1-11).
- The chat execution layering diagram and the "which layer does new code call" rubric are in the
  architecture docs; new surfaces should follow them.
