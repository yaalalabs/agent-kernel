# Agent Kernel Conversation Threads with OpenAI Agent SDK Agents on a REST API

This package contains a demo of Agent Kernel Conversation Thread Support with an agent built using the OpenAI
Agents SDK. The app mounts `AgentThreadRequestHandler` (see `app.py`), which is what enables persistent
conversation threads; the `thread` block in `config.yaml` selects the store backend. Every chat request must
carry a bearer token (all chat routes here are the thread handler's, and a thread belongs to the caller), a
thread is auto-created for each new `session_id`, and the full conversation history is readable over REST.

Threads created without an explicit `thread_name` are named by the default LLM naming strategy: a single
LiteLLM call (using `OPENAI_API_KEY` from the environment) derives a concise title from the
first prompt; a gibberish first message gets a generic title instead of becoming the name. When the call
cannot be made (no `litellm`, no API key), the name falls back to the first prompt's leading characters.

The example also shows the identity capability. The `identity` block in `config.yaml` names the provider
that turns a bearer token into the request's principal; every route runs it, and the thread routes refuse
a request nothing authenticated. Here the `static` provider maps two credentials to two principals
(`alice` and `bob`). The credential values are not in the file: each key (`ALICE_TOKEN`, `BOB_TOKEN`) names
a secret the secret capability resolves at startup, from the environment by default. Listings are the
caller's own, reading or continuing another user's thread is a 403, and a `user_id` in a request body is a
400: the acting user comes from the credential, never from the client. To validate real tokens, swap the
provider for `oidc` (Auth0, Keycloak, Okta or any other OIDC issuer), `cognito`, `entra` or `firebase`;
[`examples/aws-serverless/openai-auth`](../../aws-serverless/openai-auth/README.md) shows an Auth0 block.

`OPENAI_API_KEY`, `ALICE_TOKEN` and `BOB_TOKEN` must be set in the environment:

    export OPENAI_API_KEY=sk-...
    export ALICE_TOKEN=alice-token BOB_TOKEN=bob-token

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

**Until a release includes it, the pause and decision history below needs the local build.** The plain
`./build.sh` installs `agentkernel` 0.9.5 from PyPI, which stores pauses and decisions without a
`media_type`, so `app_test.py` fails there. Run `ak-py/build.sh` to fill `../../../ak-py/dist`, then
`./build.sh local`.

Run this demo using the following.

Run REST API:

    python app.py

Chat as alice (repeat with the same `session_id` to continue the thread):

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "What is the capital of France?", "session_id": "ses-1", "thread_name": "Capitals quiz"}'

List threads (always the caller's own):

    curl http://localhost:8000/api/v1/threads -H "Authorization: Bearer alice-token"

Get a thread with its message history:

    curl http://localhost:8000/api/v1/threads/ses-1 -H "Authorization: Bearer alice-token"

Rename a thread: send `thread_name` on a later chat request for the same `session_id` (updates the name
only and locks it against automatic naming):

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "And of Italy?", "session_id": "ses-1", "thread_name": "European capitals"}'

The same requests with `Bearer bob-token` are refused with 403: bob does not own alice's thread. Without a
token every thread route answers 401.

## A pause in the history

`send_summary_email` is bound with `needs_approval=True`, so the agent stops before calling it and the
request answers `202` with `status: "PAUSED"`:

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Email a summary to anne@example.com", "session_id": "ses-2"}'

Answer it with the interruption id from that reply. This turn carries no prompt, because the decision
*is* the turn:

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Authorization: Bearer alice-token" \
      -H "Content-Type: application/json" \
      -d '{"session_id": "ses-2", "agent": "assistant",
           "resume": {"decisions": [{"id": "<interruption id>", "status": "approved"}]}}'

Read the thread back and the exchange is all there: the question the agent asked and the decision that
answered it are messages of their own, each carrying its payload as an object with a `media_type`:

    curl http://localhost:8000/api/v1/threads/ses-2 -H "Authorization: Bearer alice-token"

To run tests (the suite starts `app.py` with the two tokens above):

    uv run pytest -s

After `./build.sh local`, run `.venv/bin/pytest -s` instead: `uv run` re-resolves the environment and can
swap the local build back for the PyPI release.
