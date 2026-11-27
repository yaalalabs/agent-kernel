---
name: ak-dev-bench-new-client-driver
description: >
  Step-by-step guide for adding a new execution mode or message type to the ak-bench benchmark harness
  (benchmarks/ak_bench/load/driver/): a new ClientDriver that talks to the deployed AK app over another transport
  or reply shape, e.g. WebSocket streaming (delta chunks), REST async, SSE. Use this skill when ak-bench must
  benchmark a mode × message type other than async + complete. Covers the ClientDriver contract (connect, send,
  close, response events), reply matching, trace_stages and the per-request durations, DriverFactory registration,
  the deployment folders per host, and tests against a local mock server.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Client Driver (Execution Mode × Message Type)

The load generator is shared by every mode. A driver is the only mode-specific piece: it connects one client to the
deployed app, sends requests, and reports replies as `ResponseEvent`s. Read `ak-dev-bench-architecture` first if you
haven't. The reference implementation is `load/driver/ws_complete.py` (`async` + `complete`), tested in
`tests/load/test_ws_complete_driver.py` against `tests/mocks/ws_server.py`.

A new mode × message type is:

1. one driver class in `load/driver/<transport>_<message-type>.py` (e.g. `ws_delta.py`, `rest_async.py`);
2. one branch and one `BUILTINS` tuple in `DriverFactory`;
3. a deployment folder `app/deploy/<host>-<mode>-<message-type>/` for every host that should run it
   (see `ak-dev-bench-new-host`, Step 2).

Names: `mode` and `message_type` are lowercase with **no `-`** (they are parts of the `-`-split deployment id and of
the deployment folder name). `mode` is AK's execution mode (`async`, `sync`, ...); `message_type` is the reply shape
(`complete`, `delta`, ...).

## Step 0: Research the mode (before any code)

Follow the workflow in `ak-dev-bench-architecture` (baseline, research rules, recording, when to ask). For a
driver, most facts come from this repo; cite `file:line` for each:

- **The AK handler that serves the mode** (`ak-py/src/agentkernel/pipeline/ws/handler.py` for WebSocket, the REST /
  API handlers under `ak-py/src/agentkernel/api/` for HTTP): the exact request frame or body, every frame or
  response it sends back (acks, chunks, final reply, errors), which ones carry the request id, and how failures
  look (enqueue failure, agent error, permanent delivery failure).
- **How a client authenticates** on that API with the bench token (`benchmarks/app/identity.py`,
  `ak-py/src/agentkernel/identity/`).
- **Which `TRACE` stages the request path logs** for this mode (grep the trace points for `TraceStage` in `ak-py`),
  in order: this is `trace_stages`.
- **What "first chunk" and "complete" mean** for the mode, so the latency columns mean the same across modes.
- **Front-door behaviour per host** that runs it (official docs): idle and integration timeouts, frame / payload
  size limits, connection limits; these can cap or distort results and belong in the #786 notes.
- **The client library**: asyncio support, keep-alive, how it reports a closed connection.

Record the frame shapes and stage chain in the #786 "Client drivers" section and any front-door limits in its
research notes.

## How the load generator uses a driver (`load/generator.py`)

- One driver **per client**: client `i` is user `bench-i` with its own signed token, session and driver, created as
  `driver_cls(endpoint, token, on_event)`.
- `connect()` for all clients is gathered before load starts. A client whose `connect()` raised is kept; its
  requests end as `error` ("connect failed: ...").
- `send(request_id, session_id, prompt)` is awaited at each scheduled time. The prompt **is** the request id (the
  mock agent echoes it, so a reply can be matched by its text). A raised `send()` is that request's `error`.
- The generator stamps `sent` itself, just before calling `send()`; the driver stamps reply times.
- A request with no `complete` or `error` within `client_timeout_s` becomes `timeout`; later events for it are
  ignored, as are duplicates.
- `close()` is called once after the step, also after failures.
- Connections are opened **before** the before window and stay open, mostly idle, through the before window
  (`before_window_s`, default 60 s), the load and the cool-down. Keep them alive if the transport or front door drops
  idle connections (the `websockets` client pings by default).
- `on_event` is a plain function that updates the generator's state; call it only from the event loop (a receive
  task), never from another thread.

## Step 1: Write the driver

```python
from collections.abc import Callable
from typing import ClassVar

from agentkernel.core import TraceStage

from ak_bench.load.driver.base import ClientDriver
from ak_bench.load.records import ResponseEvent


class WebSocketDeltaDriver(ClientDriver):
    """AK's WebSocket chat frames with streamed delta replies (async mode, delta message type)."""

    # Request-path stages this mode logs, in request order; drives the per-request durations
    trace_stages: ClassVar[tuple[TraceStage, ...]] = (...)

    async def connect(self) -> None: ...      # open, start the receive task; raise if the server refuses
    async def send(self, request_id: str, session_id: str, prompt: str) -> None: ...   # write, return; never wait
    async def close(self) -> None: ...        # cancel the receive task, close the connection
```

The contract (`load/driver/base.py`, #786 "Client drivers"):

- **`connect()`** prepares the client (socket, HTTP session) and raises when the server refuses it (bad token). If
  the server accepts and then closes on a bad token, detect it (the WebSocket driver waits `AUTH_GRACE_S` for a
  close). Authenticate with `self.token` the way the app's `BenchIdentityProvider` expects (WebSocket: `?token=` in
  the URL; HTTP: the header the app reads).
- **`send()` never waits for the reply.** It hands the request over and returns. Replies arrive through a receive
  task (one per connection for a socket, or one task per request for HTTP) that calls `self.on_event`.
- **Events:** for each request emit `first_chunk` then `complete`, or one `error` (with `detail`). A mode with no
  chunks emits `first_chunk` and `complete` with the same timestamps. A streaming mode emits `first_chunk` on the
  first delta and `complete` on the final one; don't emit per-delta events. Stamp `wall = datetime.now(UTC)` and
  `mono = time.monotonic()` once when the frame arrives, before any other work.
- **Match every reply to its request id.** Use the reply's request id if the app sends one; else the in-flight
  request id found in the reply text (the prompt is the id); only as a last resort the connection's single in-flight
  request. Keep an in-flight set per driver and add the id **before** writing the request (the reply can arrive before
  `send()` returns), removing it again if the write fails. Never let an unknown frame or an ack (e.g. `CHAT_QUEUED`) count as a
  reply: drop it, with a `debug` log (a `warning` for a dropped error reply).
- **Failures are events, not exceptions.** An app-reported failure is an `error` event. The receive task must not
  die on one bad frame; a closed connection ends it quietly (the remaining requests time out).
- **Asyncio only, no threads.** Thousands of clients run on one event loop: no blocking calls, no per-request
  threads. Pick an asyncio client library already in `benchmarks/pyproject.toml` (`websockets`); add one (with a
  bounded range, then `uv lock`) only if the transport needs it.
- **Read the app's real frame / response shapes** from the AK handler that serves the mode (e.g.
  `ak-py/src/agentkernel/pipeline/ws/handler.py` for WebSocket) and cite the lines in a comment where the shape is
  not obvious.
- **Record and report only:** no retries, reconnects or back-off that would hide failures from the results.

## Step 2: `trace_stages` and the per-request CSV

`trace_stages` is the ordered subset of AK's `TraceStage` (`agentkernel.core`) that this mode's request path
actually logs. `PerRequestWriter` builds the duration columns along `[client sent] + trace_stages + [client
complete]`, so a stage the mode never logs must not be in the chain (it would leave a gap and skip a duration).

- Start from the WebSocket complete chain (every `TraceStage` except `AGENT_FIRST_CHUNK`, `RESPONSE_POLL_START`,
  `RESPONSE_FOUND`) and add or remove stages: e.g. a streaming mode adds `AGENT_FIRST_CHUNK`.
- `per_request.py` currently leaves `RESPONSE_POLL_START` and `RESPONSE_FOUND` out of the CSV columns, and
  `KeyedCsv` silently drops keys that aren't columns. Putting them in `trace_stages` today loses their timestamps and
  durations without an error. A mode that polls for its response (REST async with a status poll) needs a
  `per_request.py` and #786 design change first.
- A stage AK doesn't log yet is an AK change (`TraceStage` in `ak-py/src/agentkernel/core/logger.py` plus the trace
  point), designed and reviewed separately, not part of the driver.

## Step 3: Register it in `DriverFactory` (`load/driver/factory.py`)

```python
BUILTINS: ClassVar[tuple[tuple[str, str], ...]] = (("async", "complete"), ("async", "delta"))

@staticmethod
def driver_class(mode: str, message_type: str) -> type[ClientDriver]:
    if (mode, message_type) == ("async", "complete"):
        return WebSocketCompleteDriver
    if (mode, message_type) == ("async", "delta"):
        return WebSocketDeltaDriver
    ...
```

- `BUILTINS` is also where `ak-bench run` takes its default `modes` / `message_types`, so a new tuple means `run`
  with no flags tries it on every host. Add the deployment folders (Step 4) in the same change, or `run` is refused at
  its pre-check ("deployment folder incomplete").
- **The defaults are a cross product.** `run` takes the distinct modes and the distinct message types from
  `BUILTINS` and runs every mode × message type. Adding `("sync", "delta")` next to `("async", "complete")` makes
  it try `async + delta` and `sync + complete` too, which have no driver, so `run` with no flags is refused before
  any deploy. Either keep `BUILTINS` a full cross product, or change `Run.execute` to take the pairs from
  `BUILTINS` (a harness change, with its test).
- Built-ins only: no dotted-path or plugin loading.

## Step 4: Deployment folders

For each host that should run the mode, add `app/deploy/<host>-<mode>-<message-type>/` following
`ak-dev-bench-new-host` Step 2 and `benchmarks/app/deploy/README.md`. Mode-specific app config (streaming on, the
REST route, the API front door) lives in the folder, not in `app/config.yaml`. `deployment.json`'s `endpoint` must
be what this driver connects to.

## Step 5: Tests (local only, `127.0.0.1`)

Put tests in `benchmarks/tests/load/test_<transport>_<message_type>_driver.py`.

- A local mock of the app's endpoint in `tests/mocks/` that behaves like AK for this mode: accepts only tokens signed
  with the test secret (`TokenSigner`), replies after a delay with the real frame shapes, and can drop, fail, error,
  duplicate and refuse on demand. Extend `MockWsServer` for a WebSocket mode; add a small server for HTTP.
- Cover: request shape on the wire; `first_chunk` / `complete` timing (same stamp for non-streaming, first delta for
  streaming); matching with and without a request id in the reply; app error replies → `error` events; acks and
  unknown frames ignored; refused token → `connect()` raises; `send()` returns before the reply; `close()` with
  requests in flight.
- An end-to-end `LoadGenerator` run with the new driver (burst and steady) where every request ends `ok`, `error` or
  `timeout`.
- Update `tests/test_registries.py`: the factory returns the new class, and the "built-ins" list in
  `test_unknown_driver_lists_builtins` includes it.
- `cd benchmarks && uv run pytest -q` and ruff must pass.

## Step 6: Docs

- #786 `design.md` "Client drivers": the mode is now built-in, its trace-stage chain, and any timing caveat (e.g.
  what "first chunk" means for it).
- `benchmarks/README.md` and `ak-bench.example.yaml`: the new `modes` / `message_types` values.

## Checklist

- [ ] Driver in `load/driver/<transport>_<message-type>.py`; names have no `-`
- [ ] `send()` never waits; every request ends in `complete` or `error` events; ack / unknown frames ignored
- [ ] Reply matching by request id, else prompt text; per-driver in-flight set; asyncio only
- [ ] `trace_stages` lists only stages this mode logs, in order; no poll stages without the CSV change
- [ ] `DriverFactory` branch + `BUILTINS` tuple; deployment folders for every host that runs it
- [ ] Mock endpoint + driver tests + generator test; registry test updated; all green
- [ ] #786 design, README and example config updated
