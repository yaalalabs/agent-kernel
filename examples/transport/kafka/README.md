# Agent Kernel queue mode over Kafka (OpenAI Agents SDK)

This demo runs Agent Kernel's chat execution pipeline

```
Request Handler → agent-input → Agent Runner → agent-output → Response Handler
```

across **two processes** with a real Kafka broker between them. It is the same pipeline the
`examples/api/openai` demo runs in a single process over in-memory queues, with only configuration
changed: `execution.queues.type: kafka` plus a shared response store.

Everything runs on a laptop. The `kafka_tester.py` harness starts one Kafka broker in KRaft mode
(no ZooKeeper, no operator, roughly 1 GiB of RAM), provisions the topics, and gives you a few
commands for looking inside the queues while the pipeline runs.

## Prerequisites

- Docker (for the broker and Valkey)
- `OPENAI_API_KEY` exported
- `./build.sh` (or `./build.sh local` to install `agentkernel` from `../../../ak-py/dist`)

> The `kafka` extra ships with the release that introduces the Kafka transport. Until that
> release is on PyPI, build with `./build.sh local` after `cd ak-py && ./build.sh` has produced a
> wheel in `ak-py/dist`.

## Quickstart

```bash
./build.sh
export OPENAI_API_KEY=sk-...

python kafka_tester.py up        # broker + Valkey + topics, waits until Kafka answers
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
python kafka_tester.py down       # stops both containers and deletes their state
```

## What the two processes do

| Process | Entrypoint | Responsibility |
|---------|-----------|----------------|
| `python app.py io` | `IOHandler.run()` | Serves `/api/v1/chat`, produces to `agent-input`, consumes `agent-output`, writes replies to the response store |
| `python app.py runner` | `AgentRunner.run()` | Consumes `agent-input`, runs the agent, produces the reply to `agent-output` |

Scale the runner by starting more of them (up to the partition count, see below). Note that
`RESTAPI.run()` is *not* used here: it boots the whole pipeline in one process only when the
transport resolves to `in_memory`, so on a broker transport the IO side starts explicitly through
`IOHandler`.

## The tester

```bash
python kafka_tester.py up --partitions 4   # compose up, wait for the broker, create topics
python kafka_tester.py topics              # partition counts and records retained per topic
python kafka_tester.py tail agent-output    # print what is currently in a topic
python kafka_tester.py tail agent-input.dlq # inspect permanently failed records
python kafka_tester.py produce agent-input --key s1 --value '{"prompt":"hi"}'
python kafka_tester.py reset               # delete and recreate the topics for a clean slate
python kafka_tester.py down                # stop everything, remove volumes
```

`tail` reads with a throwaway consumer group and never commits, so inspecting a queue cannot steal
work from the running pipeline or move its offsets.

Four topics are provisioned: `agent-input`, `agent-output`, and a dead-letter topic for each.
Agent Kernel never creates topics (a production cluster manages them through Strimzi or your
platform team), and the compose file disables auto-creation so a wrong topic name fails here
exactly as it would in production. The dead-letter topics matter for the same reason: a
permanently failed record can only be preserved if its DLQ already exists.

## Tests

```bash
uv run pytest -s
```

The suite brings the stack up, starts both processes, exercises `rest_sync` including a
multi-turn session, checks that both topics carry traffic with the `request_id` header, and then
feeds the runner a record it cannot parse to prove the retry and dead-letter path works against a
real broker: retried up to `max_receive_count`, routed to `agent-input.dlq` with an `ak-error`
header, then committed so it stops blocking its partition. It skips itself when Docker or
`OPENAI_API_KEY` is missing.

## Things worth knowing about Kafka as a queue

- **Partitions set your concurrency.** The record key is the `session_id`, which keeps a session's
  turns ordered. Kafka then gives each partition to one consumer thread, so two sessions sharing a
  partition wait for each other, and threads beyond the partition count never receive work. Keep
  `no_of_consumers × replicas` at or below the partition count; the runner logs the ratio at
  startup and warns when a topic is short of partitions. To see that warning, try
  `python kafka_tester.py reset` after `up --partitions 1`. Adding partitions later re-maps session
  keys, so size up front (production defaults to 32).
- **Retry bookkeeping needs a home.** Kafka has no delivery count or deduplication of its own, so
  Agent Kernel keeps them in whatever the `session` block points at. This example uses Valkey, so
  they survive a restart. With an in-memory session store it still works, but Agent Kernel warns
  that a message which *crashes* its worker could reset its own delivery count.
- **No visibility timeout.** An unacknowledged record returns through the in-process retry, or when
  its uncommitted offset is reassigned after a crash or rebalance. Nothing redelivers a record
  while the worker is alive but stuck, so `max.poll.interval.ms` defaults to 15 minutes (rather
  than librdkafka's 5) to keep a long agent turn from being mistaken for a dead consumer.
- **`auto.offset.reset` is `earliest`,** so a new consumer group reads a topic from its oldest
  retained record instead of skipping ahead. That is what stops a cold start from losing requests
  produced before the consumers were ready, but it also means pointing a new `group_id` at a topic
  with history replays that history.

This stack is deliberately not production shaped: one broker, replication factor 1, ephemeral
storage. A real deployment runs three brokers with replication factor 3 and
`min.insync.replicas: 2`. See the
[Queue Mode Guide](https://kernel.yaala.ai/docs/advanced/queue-mode-guide) for the full picture.
