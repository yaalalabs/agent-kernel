# #405: LiveKit voice integration

Add a realtime execution mode for persistent, bidirectional model sessions and a stateful
LiveKit voice gateway. Reuse the queue pipeline while keeping model adapters behind a core contract.

## Motivation

- Ordinary agent execution handles one queue message with one chat execution call
  (`ak-py/src/agentkernel/pipeline/agent_runner.py:59`); a realtime socket must outlive individual messages.
- A voice edge owns a live platform connection and must receive input and deliver output through it
  (`ak-py/src/agentkernel/integration/adapter/base.py:239`).
- Audio delivery needs a playback schedule and interruption handling across queue hops
  (`ak-py/src/agentkernel/pipeline/realtime_pool.py:127`).

## Requirements

### Execution and lifecycle

- Add `ExecutionMode.REALTIME`, selected through process-level `execution.mode: realtime`.
  - Keep the four existing execution modes and their behavior unchanged.
  - Requests must not select or override the process's execution mode.
  - A stateful edge is the only entry: the REST chat routes reject REALTIME requests with a 400, and REALTIME never co-hosts the WebSocket handlers, since its replies are delivered to the edge that sent the request.
- `RealtimeAgentRunner` must forward audio and text requests to the session's persistent connection.
- `ECSRealtimeAgentRunner` must provide the equivalent input-consumer behavior for ECS/SQS.
- Both runner hosts must start the pool's event loop before creating connections.
  - Pool initialization alone must not be treated as starting its loop.
- `RealtimeConnectionPool` must own one event loop and at most one live connection per session in its process.
  - Consumer threads must send input through that connection's loop.
  - Failed, idle, and shutdown connections must be closed and removed so later input can reconnect.
- `RealtimeConnection` must own queue emission, delivery context, shared audio pacing, and the AK `ToolContext` lifecycle.
  - Reuse one configured queue transport for the connection's lifetime.

### Core contract and framework selection

- `RealtimeRunner(Runner)` must define the persistent-session contract independently of pipeline and integration types.
  - `connect(session, agent, callback)` and `disconnect()` manage the model connection.
  - `append_audio(base64_audio)` and `send_text(text)` accept input.
  - `execute_tool(name, arguments, context, call_id)` and `send_tool_result(call_id, result)` provide the tool round trip.
  - `input_sample_rate` and `output_sample_rate` declare the adapter's PCM16 mono rates.
  - Unary `run()` and `stream()` must raise `NotImplementedError`.
- Model adapters must report audio, transcript, interruption, completion, tool-call, and error events through the callback.
  - Adapters must not import pipeline types or implement their own queue emission or playback pacing.
  - Tool invocation must use the framework-native tool API; the pool supplies the AK tool context.
- Select the realtime adapter through `Agent.realtime_runner_cls`.
  - `OpenAIModule(realtime_runner_cls=...)` and `GoogleADKModule(realtime_runner_cls=...)` must accept a custom `RealtimeRunner` subclass.
  - This existing class-injection seam supplies bring-your-own adapters without a second provider selector or factory.
  - Built-in realtime support is limited to OpenAI Agents SDK and Google ADK.
  - CrewAI, LangGraph, Smolagents, and Pydantic AI have no built-in realtime runner; connection creation must fail explicitly when the class is absent.
- The OpenAI runner must use the native `client.realtime` socket and server voice activity detection.
  - Function calls are read from a completed `response.done`, and the follow-up `response.create` is sent once, after every call of that response has its output.
- `GoogleADKRealtimeRunner` must use the native Gemini Live connection.
- Both model adapters must resolve the realtime model from the agent definition, with no fallback model.
- Both model adapters must send only what the agent declares, with no defaults the native API would not apply.
  - OpenAI instructions are resolved with the SDK's `get_system_prompt` over the session's framework context; none leaves the server default.
  - ADK instructions must be a string: an `InstructionProvider` is rejected with a clear error, and the agent's `description` is not used as an instruction.
  - Only function tools are offered to the OpenAI session; other tool types are skipped with a warning.
- Use the `Runner` suffix for both implementations of the core contract.
  - The implementations are `OpenAIRealtimeRunner` and `GoogleADKRealtimeRunner`.

### Voice models and protocol boundaries

- `AgentRequestVoice` must carry the inbound base64 PCM audio; `AgentRequestText` must carry data-channel text.
- Stream output must use `StreamChunk` with `AudioDelta`, `TextDelta`, and `Interrupt`, plus terminal `done` or `error` chunks.
- Realtime output is streamed chunks only; no completed voice-reply model is added.
  - A completed voice reply (and its `Runtime`, `ResponseBuilder` and guardrail branches) is deferred to the feature that produces one.
- AG-UI must leave `AudioDelta` and `Interrupt` deliberately unmapped rather than inventing a voice protocol mapping.

### Stateful edge and delivery

- `StatefulEdgeAdapter` must define start/stop, completed reply, streamed chunk, and error delivery for a live platform connection.
  - Realtime edges must declare `Source.REALTIME`.
  - Applications supply the edge instance to `GatewayRunner`; no outbound factory may recreate its live connection.
- `LiveKitEdgeGateway` must own one room, with its room name used as the session ID.
  - Receive microphone audio and data-channel text, and publish model audio and completed transcripts back to that room.
  - Stage inbound requests in a bounded queue; drop incoming requests with a warning when it is full.
- `GatewayRunner` must register and unregister the edge in `StatefulEdgeRegistry` under its session ID.
  - The registry is process-local, and the gateway must share a process with its Response Handler.
  - `IOHandler.run(gateways=[GatewayRunner(...)])` must host gateways alongside the pipeline tasks.
- Output chunks must carry `ATTR_REALTIME`, `ATTR_INTEGRATION`, request/reply context, and the session ID as their queue group.
- `ResponseHandler` must dispatch marked realtime output to the registered edge's `deliver_chunk`.
  - Reuse a delivery event loop per consumer thread.
  - Preserve realtime routing for error delivery; a missing edge must enter the existing bounded queue-retry path.

### Audio pacing and interruption

- The pipeline must convert between the edge's 24 kHz PCM16 mono and the adapter's declared sample rates.
  - Google ADK input is 16 kHz; both built-in adapters use 24 kHz output.
- The pool must pace outbound audio by emitted PCM duration and elapsed time, using `playback_lead_ms` as the target lead.
  - After a chunk takes cumulative emitted duration beyond elapsed time plus the lead, delay subsequent audio by that excess.
  - The lead is a sender-schedule target, not a hard bound on the remote LiveKit buffer; individual chunks and broker delay affect actual playback.
  - A larger lead allows more audio ahead of playback to absorb broker jitter, at the cost of more buffered audio; uninterrupted playback is not guaranteed.
- Audio and terminal/control events must retain per-session queue order.
  - `done` must follow the completed turn's queued audio.
  - On interruption, discard audio still waiting in the pool and deliver `Interrupt` after chunks already emitted.
  - Keep queued `done` events on interruption and deliver them after the `Interrupt`, so the edge resets its interrupted state on the cut-off turn rather than the next one.
- Adapters report `interrupt` only when the user speaks while the model is responding; speech outside a response is reported as `speech_started`.
  - The pool treats `speech_started` as an interruption only while it still holds paced audio, since the model finishes generating before playback ends; otherwise it is the start of the user's turn.
- The gateway must clear buffered playback on `Interrupt` and suppress publication of the interrupted turn's transcript.
- Outbound staging must be bounded and apply backpressure to the model-event reader when full.
  - The current pool queue has a capacity of 1,024 events; it is not an unbounded adapter queue.

### Configuration and reuse

- Keep configuration in `AKConfig`, with existing YAML/environment binding and defaults preserved.
- Reuse `execution.queues` (`_QueuesConfig`) and `QueueTransportFactory` for input/output transport selection.
  - Reuse the existing `session` backend configuration for loading sessions.
  - No separate realtime queue, session-store, or response-store selector is introduced.
- A `livekit` block supplies gateway settings; its presence must not start a connection.
  - `execution.mode: realtime` selects execution behavior, and an explicitly hosted gateway starts the room connection.
  - The block has defaults even when omitted, and callers can supply gateway constructor arguments; presence is not an enablement signal like an optional thread/schedule block.
  - No `outbound_adapter` override is added: applications supply a `StatefulEdgeAdapter`, and the registry routes to that live instance.
- `livekit.url` defaults to `""` and is read by `LiveKitEdgeGateway` as the room server URL.
  - The endpoint is deployment-specific and cannot be derived from agent or queue configuration.
- `livekit.api_key` defaults to `""` and is read by the gateway when generating a room token.
  - LiveKit credentials are independent of model-provider and queue credentials.
- `livekit.api_secret` defaults to `""` and is read by the gateway when signing a room token.
  - The signing secret cannot be derived from the API key; callers may instead provide an existing token.
- `livekit.agent` defaults to `""` and is read by the gateway as its configured agent name.
  - Multi-agent applications need an explicit selection; the selected name must reach pipeline agent selection.
- `execution.realtime.playback_lead_ms` defaults to `50`, accepts `0` or greater, and is read by `RealtimeConnection` for pacing.
  - Network and broker jitter vary within a transport type, so the transport name alone cannot determine the lead; SQS examples explicitly use `250` ms.
- `execution.realtime.input_batch_ms` defaults to `100`, accepts `0` or greater, and is read by `LiveKitEdgeGateway` for microphone batching.
  - This controls input-message overhead independently of outbound pacing; `0` sends each received frame, and a final partial batch is flushed when input ends.

### Deployment and broker constraints

- Provide an `in_memory` topology with the gateway, Agent Runner, pool, and Response Handler in one process.
- Provide broker examples for SQS, Kafka, and NATS with IO and Agent Runner in separate processes.
  - Run the Agent Runner as one replica because its session-to-socket pool is process-local.
  - Require per-session ordering with one input message in flight per queue group or partition.
  - For multiple rooms sharing an output queue, run one IOHandler process hosting one gateway per room and all output consumers.
  - Separate IO processes require isolated output queues or explicit routing to the owning IO process; the local registry supplies neither.
- Account for the current NATS consumer's sequential partition sweep when choosing partitions and playback lead.
  - Empty-partition waits can accumulate into voice latency; the local example uses one partition.

## Non-goals and current limitations

- Mixed execution modes in one process and built-in realtime adapters for other frameworks.
- Additional voice platforms, video processing, and distributed gateway/socket ownership.
- Confirmation-required or long-running ADK tool workflows with an interactive confirmation surface.
- Runtime hook parity on realtime voice or data-channel text turns.
  - These turns bypass `Runtime.run()`/`stream()`, so user pre/post hooks, input/output guardrails, and multimodal/sandbox pre-hooks do not run.
  - Transcript forwarding is not a guardrail hook point; adding voice-reply branches does not change this limitation.
  - Tool calls activate session and agent scopes, but this does not run the Runtime hook pipeline.
- Automatic acting-user propagation into the volatile cache; forwarding delivery user IDs is not `acting_user_id` propagation.
- Conversation history across reconnects.
  - A replaced model connection (after idle eviction or a socket failure) starts with no prior turns; adapters neither record turns nor inject them on connect.
  - Session state is not saved back to persistent session backends; a replaced connection starts with the session as last stored, so tool changes made during the previous connection are not carried over.
  - Recording and re-injecting history, and saving it on persistent session backends, is deferred to a follow-up change.
- Model session limits and server-initiated reconnects.
  - Gemini Live connections last about 10 minutes and audio sessions 15 minutes; `GoAway`, session resumption, and context window compression are not handled, so a long call ends with an error chunk and the next input opens a fresh connection.
  - OpenAI Realtime sessions last at most 60 minutes, with the same outcome.
- Gemini `tool_call_cancellation` is not handled: a tool call the user interrupted still runs and its response is still sent.
- An OpenAI `response.done` with a `failed` or `incomplete` status is reported as an ordinary `done`, not an error.
- ADK instruction templates (`{state_key}` placeholders) are sent as written; ADK's own Runner is what fills them from session state.
- The ADK runner builds each tool's `InvocationContext` itself, because the pool owns tool execution; ADK's native `Runner.run_live()`, which executes tools itself, is not used.

## Open questions

- How should realtime history be recorded, re-injected on reconnect, and saved on persistent session backends in the follow-up change?
- What routing and ownership mechanism should lift the single-IO-process and single-Agent-Runner-replica constraints in a later change?
