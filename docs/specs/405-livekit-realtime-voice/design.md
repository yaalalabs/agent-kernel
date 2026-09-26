# #405: LiveKit realtime voice integration

Messaging integrations are request/reply: a platform event becomes one queue message, the agent
runs, and one reply is delivered. Realtime voice is not that shape — the model holds a persistent,
bidirectional socket per session and audio streams both ways while the user is still talking. This
design adds a fifth execution mode for it and the seams it needs, without changing the four
existing modes.

This document describes the design as implemented on `feature/livekit-integration`.

## Motivation

- The OpenAI Realtime API and Gemini Live speak over a long-lived WebSocket. The queue pipeline
  runs each message in a short-lived task, so a socket cannot live inside one run — it must
  outlive it.
- The LiveKit edge is stateful (it owns a WebRTC room), unlike the stateless webhook adapters.
- Audio must stream out as the model produces it, not as one collapsed reply, and barge-in must
  cut playback.

## Design

### Execution mode

`ExecutionMode.REALTIME` is a **process-level config** (`execution.mode: realtime`), exactly like
`stream`/`async`. It is never carried on a request body. The three groupings that several modes
share are centralized as predicates on `ExecutionMode` (`is_realtime`, `is_streaming`,
`is_live_delivery`) so a new mode is added in one place, not to scattered tuples.

### Core contract: `RealtimeRunner`

`core/base.py` adds `RealtimeRunner(Runner)`:

- `connect(session, agent, callback)` — open the persistent socket and bind an event callback.
- `append_audio(base64_audio)` / `send_text(text)` — push input.
- `execute_tool(name, arguments, context)` / `send_tool_result(call_id, result)` — tool round trip.
- `disconnect()` — close the socket.
- `run()` / `stream()` raise `NotImplementedError` (a persistent socket has no unary run).

The adapter owns the model socket and reports events (`audio_delta`, `interrupt`, `done`,
`tool_call`) through the callback; it never imports pipeline types. Tool execution is
adapter-owned because the native tool objects differ (OpenAI `FunctionTool.on_invoke_tool` vs ADK
`FunctionTool.func`); the pool owns the `ToolContext` lifecycle.

### Connection pool (`pipeline/realtime_pool.py`)

- `RealtimeConnection` — one per `session_id`; wraps the adapter, stamps output chunks
  (`ATTR_REALTIME`, `ATTR_INTEGRATION`, request/reply context) and emits them to the output queue
  over a single transport built once per connection.
- `RealtimeConnectionPool` — process-wide singleton (mirrors `ConversationThreadManager`); owns
  one asyncio loop and one connection per session, so any consumer thread can append audio to a
  session's socket.

### Adapters (`framework/`)

- `OpenAIRealtimeAdapter` (OpenAI Agents SDK): the GA `client.realtime` socket with server VAD;
  audio output is paced at playback rate and `done`/`interrupt` are emitted behind their own audio
  so they cannot overtake it.
- `GoogleADKRealtimeRunner` (Google ADK): Gemini Live `BidiGenerateContent`; 16 kHz input is
  resampled from the edge's 24 kHz; output is already 24 kHz.

Both resolve the model from the agent definition; there is no adapter-level default model.

### Edge gateway (`integration/livekit/`)

`LiveKitEdgeGateway` owns the WebRTC room: inbound mic audio is batched into ~100 ms
`AgentRequestVoice` requests, text arrives over the data channel, and the gateway registers itself
as the `livekit` outbound adapter so the Response Handler routes chunks back to the same
connection. `IOHandler.run(gateways=[...])` co-hosts it as a peer thread (the `pollers` seam).

### Delivery

The Response Handler dispatches a realtime chunk by the explicit `ATTR_REALTIME` attribute (not
body shape) to the adapter's `deliver_chunk`, on a per-thread event loop reused across chunks.

### Configuration

A `livekit` block (`livekit_url`, `api_key`, `api_secret`, `agent`). The examples pin the realtime
model on the agent (`gpt-realtime` / `gemini-live-2.5-flash-preview`).

## Non-goals

- Mixed-mode processes: the mode is per-process, as for every other mode.
- Non-LiveKit realtime edges: the seam is the `RealtimeRunner` ABC + `gateways=` host; another
  edge is another adapter/gateway.
- Long-running / confirmation-required ADK tools: `execute_tool` runs through ADK's `run_async`
  with a real `ToolContext`, but a tool that requests confirmation has no surface to answer it
  in realtime.

## Open questions

- Realtime over a broker transport (the examples are single-process `in_memory`).
- Guardrails on transcript deltas (`transcript_delta` is currently a no-op hook point).
- Backpressure: the adapter's audio queue is unbounded if the edge is slower than the model.
