# Agent Kernel queue mode over NATS JetStream (OpenAI Agents SDK)

This demo runs Agent Kernel's chat execution pipeline

```
Request Handler → AGENT_REQUESTS → Agent Runner → AGENT_REPLIES → Response Handler
```

across **two processes** with a real NATS server between them. It is the same pipeline the
`examples/api/openai` demo runs in a single process over in-memory queues, with only configuration
changed: `execution.queues.type: nats` plus a shared response store.

NATS is the recommended on-prem broker: a single static Go binary that idles at tens of megabytes,
with an official Helm chart and CRDs for declarative streams. `nats_tester.py` starts it, waits for
JetStream, and gives you commands for looking inside the streams while the pipeline runs.

## Prerequisites

- Docker (for the NATS server and Valkey)
- `OPENAI_API_KEY` exported
- `./build.sh` (or `./build.sh local` to install `agentkernel` from `../../../ak-py/dist`)

> The `nats` extra ships with the release that introduces this transport. Until that release is on
> PyPI, build with `./build.sh local` after `cd ak-py && ./build.sh` has produced a wheel in
> `ak-py/dist`.

## Quickstart

```bash
./build.sh
export OPENAI_API_KEY=sk-...

python nats_tester.py up         # NATS + Valkey, waits until JetStream answers
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
python nats_tester.py down        # stops both containers and deletes their state
```

## What the two processes do

| Process | Entrypoint | Responsibility |
|---------|-----------|----------------|
| `python app.py io` | `IOHandler.run()` | Serves `/api/v1/chat`, publishes to `AGENT_REQUESTS`, consumes `AGENT_REPLIES`, writes replies to the response store |
| `python app.py runner` | `AgentRunner.run()` | Consumes `AGENT_REQUESTS`, runs the agent, publishes the reply to `AGENT_REPLIES` |

Scale the runner by starting more of them (up to the partition count, see below). Note that
`RESTAPI.run()` is *not* used here: it boots the whole pipeline in one process only when the
transport resolves to `in_memory`, so on a broker transport the IO side starts explicitly through
`IOHandler`.

## The tester

```bash
python nats_tester.py up                     # compose up, wait for JetStream
python nats_tester.py streams                # message counts and partition consumers per stream
python nats_tester.py tail AGENT_REQUESTS    # print what a stream is holding
python nats_tester.py publish --session s1 --data '{"prompt":"hi"}'
python nats_tester.py provision              # create streams/consumers explicitly (see below)
python nats_tester.py purge                  # empty the streams, keep their configuration
python nats_tester.py down                   # stop everything, remove volumes
```

Two things about inspection are worth understanding, because they differ from Kafka:

- **You cannot browse a work-queue stream with another consumer.** Consumers on a work-queue stream
  must have non-overlapping filter subjects, so attaching one to peek would either be rejected by
  the server or steal work from the running pipeline. `tail` therefore reads by sequence with a
  JetStream *direct get*, which delivers nothing to any consumer.
- **An acked message is gone.** Work-queue retention removes a message when the pipeline
  acknowledges it, so a healthy request barely appears in `tail`. Messages you *do* see are usually
  in flight, retrying, or waiting behind a busy partition. That is the queue working, not a bug.

`publish` builds its subject with the transport's own partition hash, so an injected message lands
exactly where the pipeline would have put it.

## Provisioning: two postures

This example sets `auto_provision: true`, so Agent Kernel creates the streams and one durable
consumer per partition at startup. That is the local and dev posture.

Production leaves it `false` and manages the objects declaratively (NACK CRs, or the `nats` CLI), so
a missing stream or consumer fails loudly at startup, naming what is absent, instead of being
created with defaults that quietly disagree with your intent. To rehearse that here:

```bash
python nats_tester.py provision                     # create the objects explicitly
# set auto_provision: false in config.yaml, then start the pipeline: it verifies instead of creating
```

Delete a consumer and start again to see the failure message.

## Tests

```bash
uv run pytest -s
```

The suite brings the stack up, starts both processes, exercises `rest_sync` including a multi-turn
session, checks that both streams exist with one consumer per partition, and then feeds the runner
a message it cannot parse to prove the retry and termination path against a real server: it asserts
the wire shape while the message lingers through its retries, then that JetStream removes it once
the pipeline terminates it. It skips itself when Docker or `OPENAI_API_KEY` is missing.

## Things worth knowing about JetStream as a queue

- **It is the closest fit of any backend here.** The server provides the visibility timeout
  (`ack_wait`), an exact delivery count (`num_delivered`), a server-enforced delivery ceiling
  (`max_deliver`), deduplication (`Nats-Msg-Id` plus the stream's duplicate window), and a terminal
  disposition (`term()`). Unlike Kafka, none of that is rebuilt in Agent Kernel, so there is no
  retry-bookkeeping store and no dead-letter topic to provision.
- **Partitions set your concurrency, and the server enforces it.** Sessions hash to a partition
  subject, each served by a durable consumer with `max_ack_pending: 1`, so a session's turns stay
  ordered and at most `partitions` messages are in flight across the whole cluster. Keep
  `no_of_consumers × replicas` at or below the partition count; the runner logs the ratio at startup
  and warns when it is short. Changing the count re-maps sessions, so size it up front (32 is the
  production default; this example uses 4 to keep provisioning quick).
- **`ack_wait` must exceed your longest turn.** It defaults to 300 seconds here rather than
  JetStream's usual 30, because it is a visibility timeout: a turn that outlives it is redelivered
  and the agent runs a second time.
- **Permanent failure terminates rather than dead-letters.** After the pipeline's permanent-failure
  hook has delivered the error to the caller, the message is `term()`ed, which stops redelivery and
  removes it from the work-queue stream. `max_deliver` is the server-side backstop behind that.

This stack is deliberately not production shaped: one server, no clustering, ephemeral storage. A
real deployment runs a 3-node cluster with streams and consumers at `replicas: 3`, from the official
`nats` Helm chart. See the
[Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide) for the full picture.
