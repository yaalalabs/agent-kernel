# Sandbox — Principal & Identity (REST API, end-to-end)

Running sandboxed code under the **end user's** identity instead of one shared agent
identity — the practical multi-tenant pattern. A single deployed agent serves many users;
each user's code should run within *their* permissions, be audited as *them*, and never see
another user's resources.

This is a full REST application, not a snippet: the request carries an auth token, the app
authenticates it, and sandboxed code runs as the authenticated user.

## The flow (all application code)

1. A client calls `POST /api/v1/chat` with a prompt and an `auth_token` field.
2. [`IdentitySeedPreHook`](identity.py) (registered on the agent in [`app.py`](app.py)) runs
   before the agent: it reads the token (Agent Kernel delivers any extra request field to
   hooks), rejects a missing/invalid one, and on success looks the user up in
   `USER_DIRECTORY` (your IdP / IAM stand-in) and records the identity on the session.
3. The agent runs and calls the sandbox tools.
4. The sandbox asks the configured `PrincipalResolver`
   ([`SessionUserPrincipalResolver`](identity.py)) for the execution identity; it reads what
   the pre-hook stored and returns a **user-mode** `SandboxPrincipal` (subject, role ARN,
   groups).
5. That principal is handed to the provider's `create()` — where a real backend assumes the
   role / sets impersonation. The [demo provider](sandbox_provider.py) instead exposes the
   identity to the code as `SANDBOX_PRINCIPAL`, so you can watch it end to end with no cloud.

The agent's own instructions say nothing about identity — it's entirely the pre-hook,
resolver, and config.

## Why a demo provider

Real user-identity providers need cloud infrastructure (`kubernetes` impersonation,
`bedrock_agentcore` / `ec2_ssm` via `sts:AssumeRole`). To keep this runnable, the example
wires a bring-your-own provider (a dotted path in `config.yaml`) that declares
`principal_user` support and runs code locally with the caller's identity in
`SANDBOX_PRINCIPAL`. The same request → auth → resolver → provider path runs unchanged; only
the provider `type` in `config.yaml` changes for production. (Like `local_subprocess`, the
demo provider gives **no isolation** — it's for demonstration only.)

## Fail-closed

The `secure` profile sets `identity.mode: user`, so Agent Kernel enforces (worker-side,
before any provider call) that both the provider supports user identity **and** a user-mode
principal was actually resolved. A user-scoped request can never silently fall back to the
agent identity — it is rejected instead. Here the pre-hook rejects unauthenticated requests
up front; the worker-side check is the backstop.

## Run

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    uv run app.py

Then, from another shell:

    # Alice's code runs as alice
    curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
      "prompt": "Run python that prints the SANDBOX_PRINCIPAL env var, then tell me only that value.",
      "session_id": "s-alice", "agent": "coder", "auth_token": "token-alice"}'

    # Bob's identical request runs as bob
    curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
      "prompt": "Run python that prints the SANDBOX_PRINCIPAL env var, then tell me only that value.",
      "session_id": "s-bob", "agent": "coder", "auth_token": "token-bob"}'

    # No/invalid token is rejected
    curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
      "prompt": "Run some code.", "session_id": "s-x", "agent": "coder"}'

## Tests

    uv run pytest -s

The tests drive the running API over HTTP and assert alice's and bob's code run under their
own identities and that unauthenticated requests are rejected. Running them requires
`OPENAI_API_KEY` (the agent decides to call the sandbox tools).
