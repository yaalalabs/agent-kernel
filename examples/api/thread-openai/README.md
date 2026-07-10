# Agent Kernel Conversation Threads with OpenAI Agent SDK Agents on a REST API

This package contains a demo of Agent Kernel Conversation Thread Support with an agent built using the OpenAI
Agents SDK. Adding a `thread` block to `config.yaml` turns on persistent conversation threads: every chat request
must then carry a `user_id`, a thread is auto-created for each new `session_id`, and the full conversation history
becomes readable over REST.

The example also demonstrates the pluggable `Authoriser`. Agent Kernel does not authenticate users itself — you
supply a subclass that validates the Bearer token against your own authentication provider and resolves the caller's
`user_id`. Here, `DemoAuthoriser` uses a static token map (`alice-token` → `alice`, `bob-token` → `bob`). With an
Authoriser configured, the thread read endpoints require a valid token, listings are scoped to the resolved user,
and reading another user's thread is rejected. Without one, the thread routes are open.

`OPENAI_API_KEY` must be set in the environment.

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

Run REST API:

    python app.py

Chat — `user_id` is required because thread support is enabled (repeat with the same `session_id` to continue the
thread):

    curl -X POST http://localhost:8000/api/v1/chat \
      -H "Content-Type: application/json" \
      -d '{"prompt": "What is the capital of France?", "session_id": "ses-1", "user_id": "alice", "thread_name": "Capitals quiz"}'

List threads (scoped to the authorised user):

    curl http://localhost:8000/threads -H "Authorization: Bearer alice-token"

Get a thread with its message history:

    curl http://localhost:8000/threads/ses-1 -H "Authorization: Bearer alice-token"

To run tests:

    uv run pytest -s
