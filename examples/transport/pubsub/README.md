# Agent Kernel queue mode over Google Cloud Pub/Sub (OpenAI Agents SDK)

This demo runs Agent Kernel's chat execution pipeline

```
Request Handler → agent-input → Agent Runner → agent-output → Response Handler
```

across **two processes** with the Pub/Sub emulator between them. It is the same pipeline the
`examples/api/openai` demo runs in a single process over in-memory queues, with only configuration
changed: `execution.queues.type: pubsub` plus a shared response store.

Pub/Sub is the broker for queue mode on GCP: serverless, nothing to run, and it scales to zero.
The emulator gives you the same API locally. `pubsub_tester.py` starts it, waits until it answers,
and gives you commands for looking at the topics while the pipeline runs.

## Prerequisites

- Docker (for the Pub/Sub emulator and Valkey)
- `OPENAI_API_KEY` exported
- `./build.sh` (or `./build.sh local` to install `agentkernel` from `../../../ak-py/dist`)

> The `pubsub` extra ships with the release that introduces this transport. Until that release is
> on PyPI, build with `./build.sh local` after `cd ak-py && ./build.sh` has produced a wheel in
> `ak-py/dist`.

## Quickstart

```bash
./build.sh
export OPENAI_API_KEY=sk-...

python pubsub_tester.py up       # emulator + Valkey, waits until the emulator answers
python app.py runner             # terminal 2: the Agent Runner
python app.py io                 # terminal 3: the REST API and Response Handler
```

Then send a request:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "I am Andy Dufresne. I did some deposits.",
       "session_id": "session-1",
       "agent": "support"}'
```

When you are done:

```bash
python pubsub_tester.py down     # stops both containers and deletes their state
```

`app.py` sets `PUBSUB_EMULATOR_HOST=localhost:8085` unless it is already set. The Pub/Sub client
libraries read that variable themselves, so pointing at real Pub/Sub is a matter of removing that
line and setting `project_id` in `config.yaml`.

## What the two processes do

| Process | Entrypoint | Responsibility |
|---------|-----------|----------------|
| `python app.py io` | `IOHandler.run()` | Serves `/api/v1/chat`, publishes to `agent-input`, pulls `agent-output`, writes replies to the response store |
| `python app.py runner` | `AgentRunner.run()` | Pulls `agent-input`, runs the agent, publishes the reply to `agent-output` |

Scale the runner by starting more of them: Pub/Sub has no partition ceiling. Locally the runner
pulls requests. On Cloud Run the `io` side is what `CloudRun.run()` starts, and the runner is a
second service that Pub/Sub pushes each request to, started by `CloudRunAgentRunner.run()` (see the
ak-gcp modules' `queue_mode`).

## The tester

```bash
python pubsub_tester.py up                       # compose up, wait for the emulator
python pubsub_tester.py topics                   # topics, subscriptions, ordering and dead-letter settings
python pubsub_tester.py tail agent-input-dlq     # peek at what a subscription holds (no ack)
python pubsub_tester.py publish --session s1 --data '{"prompt":"hi"}'
python pubsub_tester.py provision                # create topics/subscriptions explicitly (see below)
python pubsub_tester.py purge                    # drain every subscription (stop the pipeline first)
python pubsub_tester.py latency --messages 200   # delivery latency to idle consumers
python pubsub_tester.py down                     # stop everything, remove volumes
```

- **An acked message is gone.** A healthy request is acknowledged as soon as it ran, so `tail` on a
  pipeline subscription rarely shows anything. The dead-letter subscriptions are where messages wait
  to be read.
- **`tail` peeks by pulling and releasing at once.** On the dead-letter subscriptions nothing else
  consumes, so that is harmless. On a pipeline subscription it briefly holds messages away from the
  running consumers.
- **`publish` goes through the transport**, so an injected message has exactly the envelope and
  ordering key the pipeline would have given it.

## Provisioning: two postures

This example sets `auto_provision: true`, so Agent Kernel creates both topics, their dead-letter
topics (`agent-input-dlq`, `agent-output-dlq`), the subscriptions with message ordering and a
dead-letter policy, and a subscription on each dead-letter topic. That is the emulator and dev
posture. The first send creates the whole queue, not just the topic: Pub/Sub drops a message
published to a topic that has no subscription yet.

Production leaves it `false`. The `ak-gcp` Terraform modules create the objects (with IAM), and a
missing topic or subscription fails startup, naming what is absent, instead of being created with
defaults. To rehearse that here:

```bash
python pubsub_tester.py provision                   # create the objects explicitly
# set auto_provision: false in config.yaml, then start the pipeline: it verifies instead of creating
```

## Tests

```bash
uv run pytest -s
```

The suite brings the stack up, starts both processes, exercises `rest_sync` including a multi-turn
session, checks the topics and subscriptions that were provisioned, and then feeds the runner a
message it cannot parse to prove the retry and dead-letter path: the message is retried
`max_receive_count` times and then copied to `agent-input-dlq` with an `ak-error` attribute. It
skips itself when Docker or `OPENAI_API_KEY` is missing.

## Things worth knowing about Pub/Sub as a queue

- **Per-session order comes from ordering keys.** The session id is the message's ordering key, and
  the subscriptions have message ordering enabled. Pub/Sub can hand one consumer several messages
  of a session at once; the transport holds them and runs one at a time.
- **Agent Kernel keeps the delivery bookkeeping.** Pub/Sub's delivery count is approximate and it
  does not deduplicate on publish, so exact receive counts, deduplication on `dedup_id`, and a memory
  of acknowledged messages live in a key store (Valkey here). On GCP, sessions usually live in
  Firestore, and the Redis response store holds it instead.
- **Acknowledged messages can come back.** When an earlier message of a session is redelivered,
  Pub/Sub redelivers every later one too, acknowledged or not. The transport recognises those and
  acknowledges them again without running the agent twice.
- **`ack_wait` must exceed your longest turn.** The transport keeps extending each message's lease
  while the agent runs, up to `ack_wait` (300 seconds here). A turn that outlives it is redelivered
  and the agent runs a second time.
- **Permanent failure dead-letters.** After the pipeline's permanent-failure hook has delivered the
  error to the caller, the message is copied to the dead-letter topic with the reason in `ak-error`,
  then acknowledged. The subscription's own dead-letter policy is the server-side backstop behind
  that.

This stack is deliberately not production shaped: the emulator has no IAM and keeps messages in
memory. See the [Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide) for the
full picture.
