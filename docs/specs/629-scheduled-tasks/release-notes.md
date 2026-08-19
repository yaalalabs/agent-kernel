# Release notes draft: #629 scheduling capability

Paste-ready material for the GitHub release that ships #629. The capability lands over six PRs
(`plan.md` phases 1 to 6); this draft accumulates as each phase merges. **Shipped so far: phases 1
and 2** (shared authorization/pagination refactor, queue-path groundwork). The scheduling capability
itself (phases 3 to 6) adds its own sections below when those PRs land.

## Breaking changes

**`Authoriser` now lives in `agentkernel.auth`.**
`Authoriser` was defined inside the thread integration, which made it look thread-specific. It is
the generic authorization hook for *any* resource-management route (threads today, scheduled tasks
next), so it moved next to `AuthValidator` in `agentkernel.auth` — one import path, matching how
`AuthValidator` is already imported.

Before:

```python
from agentkernel.thread import Authoriser              # or agentkernel.integration.thread
```

After:

```python
from agentkernel.auth import Authoriser
```

The class itself is unchanged: same `authorise(token) -> Optional[str]` contract, same runtime
behavior, same 401 detail strings on the routes that use it. Apps that subclass it update one import
line and nothing else. `agentkernel.thread` and `agentkernel.integration.thread` no longer expose an
`Authoriser` attribute, so a stale import fails loudly at import time rather than silently.

**ECS REST_SYNC/REST_ASYNC error replies now surface as HTTP 4xx/5xx.**
An ECS-mode reply whose stored status is >= 400 previously came back as HTTP 200 with an error body.
It now raises the same `HTTPException` the direct and pipeline modes already raised. Clients that
keyed off the 200 status and parsed the body for errors will start seeing real error codes; this is
parity with every other deployment mode. Non-error responses are byte-identical.

## Improvements

- **New `AuthValidatorAuthoriser` adapter.** One user-supplied `AuthValidator` can now protect the
  global REST routes, WebSocket `$connect`, *and* the resource-management routes — wrap it rather
  than writing a second implementation:

  ```python
  from agentkernel.auth import AuthValidatorAuthoriser
  from agentkernel.thread import AgentThreadRequestHandler

  RESTAPI.run(handlers=[AgentThreadRequestHandler(authoriser=AuthValidatorAuthoriser(MyValidator()))])
  ```

- **Shared `AuthorisedRESTRequestHandler` base** (`agentkernel.api.handler`). Bearer parsing and 401 mapping
  live in one place; `ThreadRESTRequestHandler` now inherits `_resolve_user` from it instead of
  carrying its own copy. Behavior and error strings are identical. Custom management handlers can
  subclass it to get token handling for free.
- **Shared cursor-pagination helpers** (`agentkernel.core.util.pagination`): `encode_cursor`,
  `decode_cursor`, `clamp_limit`, and `MAX_PAGE_SIZE`. Extracted verbatim from the thread manager,
  which now delegates to them. Stores stay in plain `(limit, offset)` terms; the service layer owns
  the opaque cursor. Existing thread cursors are unchanged and remain valid.
- **Queue runners accept request metadata from the message body.** `request_id` and `user_id` are
  resolved from message attributes first, falling back to the body when an attribute is absent
  (pipeline, ECS, and serverless runners alike). A message carrying `request_id` in its body no
  longer permanently fails; messages missing the key in *both* places keep today's error path. This
  is the contract scheduler-emitted trigger messages use.
- **Queue paths preserve non-200 success statuses.** `ECSAgentRunner` forwards `ChatService`'s
  status code instead of discarding it, `ECSOutputConsumer` persists it (records gain an additive
  `status_code` key, defaulting to 200 and 500 on permanent failure), and sync/poll responses honor
  the stored status. A future 202 acknowledgement survives the round trip end to end.
- **Acting user is visible to hooks and tools.** A run whose request carries `user_id` exposes it in
  the session's volatile cache under `ak.acting_user_id` for the duration of that run:

  ```python
  from agentkernel.core import ACTING_USER_CACHE_KEY

  user_id = Session.current().get_volatile_cache().get(ACTING_USER_CACHE_KEY)
  ```

  `Runtime` both sets and clears the key inside the per-session lock, so it never leaks into another
  run and concurrent runs on one session cannot clobber each other. `AgentHandler.run_*`,
  `AgentService.run_multi`/`stream_multi`, and `Runtime.run`/`stream` each gain a backward-compatible
  optional `acting_user_id` parameter; existing callers are unaffected.

## Notes for maintainers

- Behavioral details and the full change inventory: `docs/specs/629-scheduled-tasks/spec.md`
  (Behavioural changes, items 4, 5, 6, 9, 11).
- Phased breakdown and per-phase sync steps: `docs/specs/629-scheduled-tasks/plan.md`.
- `docs/versioned_docs/` is a frozen release snapshot and intentionally still shows the old
  `Authoriser` import path.
