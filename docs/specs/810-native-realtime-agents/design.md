# #810: Native realtime agents and handoffs

Use each framework's own realtime runner for live conversations. OpenAI Agents SDK or Google ADK owns agent turns, handoffs, tools, and model connections. Agent Kernel keeps only the audio, queue, session identity, and LiveKit boundary those SDKs do not provide.

## Motivation

- The current `RealtimeRunner` contract makes Agent Kernel receive a `tool_call`, run the tool, and send its result back (`ak-py/src/agentkernel/core/realtime/runner.py:83`, `:125`). The pool implements that loop (`ak-py/src/agentkernel/pipeline/realtime_pool.py:228`).
- The OpenAI adapter opens a raw Realtime API socket and builds its own tool and handoff flow (`ak-py/src/agentkernel/framework/openai/openai.py:627`, `:690`). The ADK adapter opens a raw Gemini Live socket and builds its own transfer flow (`ak-py/src/agentkernel/framework/adk/adk.py:918`, `:1159`).
- The native frameworks already offer these jobs: [OpenAI Agents SDK realtime](https://openai.github.io/openai-agents-python/realtime/guide/) uses `RealtimeAgent`, `RealtimeRunner`, and `RealtimeSession`; [ADK live workflows](https://adk.dev/live/workflows/) use `Runner.run_live()` and one `LiveRequestQueue` for the conversation.
- The current LiveKit gateway already shows multiple agent participants and blocks its own agents' audio and chat from returning as user input (`ak-py/src/agentkernel/integration/livekit/adapter.py:235`, `:252`, `:463`).

## Requirements

```mermaid
flowchart LR
    H[Human in LiveKit room] --> E[LiveKit gateway]
    E --> P[Agent Kernel realtime pool]
    P --> A[Thin framework adapter]
    A --> S[Native realtime session: OpenAI or ADK]
    S --> T[Active agent and its tools]
    T -- native handoff --> N[Next active agent and its tools]
    S -- audio, text, speaker --> A
    A --> P
    P --> E
```

### One conversation, several agents

- A human and several agent participants can share one LiveKit room. Agents known from the declared graph appear when the call starts; a dynamic handoff target appears when first identified. One framework conversation controls the agent turn; an agent explicitly hands off to another agent through the framework's native handoff feature.
  - Example: the coordinator speaks, invites the billing agent, and billing uses its lookup tool before answering. Billing can hand the turn back.
- Only the active agent receives the live caller input and speaks for that turn. A handoff carries conversation context through the native SDK; it does not replay one agent participant's room audio into another model.
  - In ADK this is one `run_live()` call and one input queue for the LiveKit call, even though ADK opens a fresh Gemini Live API session for the agent receiving a handoff ([ADK live workflows](https://adk.dev/live/workflows/)).
- Each active agent can use the tools declared on that native agent, subject to the SDK and model's actual support. The SDK runs tools and sends their results. Its native handoff changes the active agent. Agent Kernel does not implement a second tool or handoff engine.

### Framework adapters

- `OpenAIRealtimeRunner` wraps the Python Agents SDK's `RealtimeRunner` and `RealtimeSession`, with native `RealtimeAgent` definitions and handoffs. It maps SDK audio, text, interruption, handoff, error, and completion events into the existing framework-neutral realtime events.
- `GoogleADKRealtimeRunner` wraps ADK's `Runner.run_live()` with one `LiveRequestQueue` per AK realtime connection. It sends caller audio and text into that queue, reads ADK events, and uses the event author to report the speaker. ADK manages transfers, tool execution, and its Live API connections.
- ADK live workflow agents that speak declare `mode='chat'` or `mode='task'`. ADK's graph `Workflow` is a native container, not a speaking `BaseAgent`; the AK wrapper must accept that root. Do not run ADK `ParallelAgent` or `LoopAgent` on the live path; ADK does not support them there ([ADK live workflows](https://adk.dev/live/workflows/)).
- Both adapters use public SDK APIs and preserve the application's native agent relationships. AK does not clone or rebuild the graph. Remove raw socket loops, hand-built tool responses, transfer instructions, transcript replay, manual connection switching, and SDK-level retry logic.
- Reject a known unsupported native agent declaration before opening the SDK connection. If an SDK rejects a setting only after connection starts, close the partially opened session and report the error. OpenAI realtime examples move to native `RealtimeAgent`; ordinary OpenAI `Agent` is rejected in realtime mode.
- Use native SDK guardrails, resumption, and voice settings where the live path supports them. AK hooks and AK guardrails do not automatically run through a native realtime session; document that behavior clearly. The current LiveKit edge has no approval decision path, so a tool that requires human approval cannot run through this integration: reject it before the call when detectable, or reject the request and end the call if it arises later. Never silently approve or skip a declared guardrail.

### Agent Kernel boundary

- Keep `RealtimeRunner` as the framework-neutral input/output and lifecycle contract, selected through the existing `realtime_runner_cls` class seam (`ak-py/src/agentkernel/core/base.py:523`, `:560`). Remove `execute_tool`, `send_tool_result`, and the `tool_call` callback. A custom runner that still emits `tool_call` gets an explicit failure.
- Keep `RealtimeConnection` and `RealtimeConnectionPool` for AK session identity, input batching and sample-rate conversion, ordered audio delivery, pacing, queue routing, barge-in delivery, close, and eviction. Remove the pool's tool execution and reply path.
- Keep `AgentChanged` in the ordered output stream. The first event names the first speaking agent (which may differ from a non-speaking ADK workflow root); each native handoff names the next speaker before that agent's output. The LiveKit gateway uses this event to select the speaking participant.
- Let the SDK handle model interruption and conversation truncation. Do not tell OpenAI's playback tracker that audio was played merely because AK sent it to an output queue: downstream buffering means the listener may not have heard it. Use the tracker only if the LiveKit edge can provide a reliable playout signal; until then, document the SDK's default playback estimate and test barge-in behavior. Do not build another truncation algorithm in AK.
- Keep the LiveKit rule that audio and chat from AK's own agent participants never become caller input. The declared team remains visible, with only the active agent unmuted. A newly discovered agent joins when it first becomes active if it was absent from the starting roster.
- Realtime runs native agent features only: native tools, SDK handoffs and SDK guardrails. When `execution.mode` is `realtime`, the OpenAI and ADK wrappers skip automatic AK system tools and their prompt guidance. Other modes still attach them as configured. AK hooks and AK guardrails are not part of the native live path. Core does not import framework SDKs.
- Close the native session or ADK queue on AK connection shutdown and failed startup. Framework failures reach the existing error and eviction path; the next connection does not reuse a broken native session.

### Configuration and compatibility

- Reuse `execution.realtime` for pacing and input batching, the existing queue and LiveKit settings, and `Module.run_options` for supported native run settings (`ak-py/src/agentkernel/core/config.py:668`, `ak-py/src/agentkernel/core/module.py:101`). Add no parallel AK flags for SDK tools, handoffs, or reconnects.
- Raise the `google-adk` optional dependency floor from `>=1.24.0` (`ak-py/pyproject.toml:123`) to `>=2.7.0` for the verified live fix that finds a transfer even when its tool result is not first in a batch ([ADK 2.7.0 source](https://github.com/google/adk-python/blob/v2.7.0/src/google/adk/flows/llm_flows/base_llm_flow.py), [release notes](https://github.com/google/adk-python/releases/tag/v2.7.0)). Test refused or invalid transfers at the minimum version and document what actually happens; the release notes do not guarantee that the current connection survives one.
- Preserve the bring-your-own realtime runner class path, but document the breaking contract change. A runner that emits `tool_call` cannot use the removed pool tool path.
- Show native configuration and limits in the examples and docs: move ADK per-agent voice from today's `generate_content_config.speech_config` to `Gemini(speech_config=...)`, or use `RunConfig.speech_config` for one session voice ([ADK configuration](https://adk.dev/live/configuration/)); [OpenAI cannot change a session's voice after audio starts](https://developers.openai.com/api/docs/guides/realtime-conversations). ADK resumption, where enabled, covers its link to Gemini, not the LiveKit client link ([ADK sessions](https://adk.dev/live/sessions/)).
- Document a separate support list for each SDK adapter: native tools, handoffs, approvals, SDK guardrails, AK hooks/guardrails, MCP tools, and reconnect behavior. State which features AK carries through, which need an edge decision path, and which are rejected. Do not claim that SDK support alone makes a feature available in LiveKit.
- ADK 2.9.0 also has an experimental native `LiveKitRunner` for one ADK agent participant ([ADK LiveKit runner](https://adk.dev/integrations/livekit/)). It could remove more transport code for an ADK-only deployment. The documented interface does not establish AK's queue routing or a separate LiveKit participant per speaking agent; verify those contracts before replacing the existing shared AK edge. Do not add a second LiveKit path to this change without that proof.

### Verification

- For OpenAI and ADK, verify a live text or audio turn can move from agent A to B and back, with each agent's own declared tool called by the native SDK and the correct `AgentChanged` order.
- Verify audio, text, interruptions, and errors still reach the LiveKit participant for the active agent in order; agent participants' own audio and chat never feed the native session.
- Verify SDK approval or unsupported native-agent settings produce an explicit decision or error, rather than silently running a tool or dropping the setting.
- Verify a custom runner's `tool_call` fails explicitly; measure and document ADK behavior for a refused or invalid transfer on the minimum supported version.
- Verify native tools on both agents still run through the SDK after a handoff.
- Verify two AK sessions keep separate native sessions and closing one does not stop the other.

## Non-goals

- Several voice models listening or speaking at the same time, or an automatic group discussion without explicit handoffs.
- Feeding agent-generated LiveKit audio back into another model as if a human spoke it.
- A separate voice for each OpenAI agent within one Realtime API session.
- Removing AK's queue, LiveKit gateway, audio conversion, or playback coordination; the native SDK does not own those boundaries.
- Promising identical native SDK features across OpenAI and ADK, or durable recovery of LiveKit calls after an AK process restart.
- Rebuilding native SDK handoff, tool, guardrail, approval, or reconnection engines inside Agent Kernel.
- Unchanged behavior for custom realtime runners using the old tool callback.

## Open questions

- Can the LiveKit edge report actual playout to OpenAI's native playback tracker? A successful AK queue send is not proof that the listener heard the audio.


## Edge additions for the realtime requirements meeting (C1 to C6)

Six small, framework-neutral additions to Agent Kernel, built for the [realtime requirements meeting](../../../use-cases/realtime-requirements-meeting/docs/design.md) use case. Each works the same for OpenAI and ADK. No new `AKConfig` fields.

Each change works the same way for OpenAI and ADK. The use case picks ADK, but nothing in AK assumes it.

```mermaid
sequenceDiagram
    participant C as Client (room)
    participant G as LiveKit gateway
    participant P as Realtime pool
    participant A as Adapter: ADK or OpenAI
    participant N as Native session
    participant U as Use case: event log

    C->>G: speaks
    G->>P: audio (queue)
    P->>A: append_audio
    A->>N: audio
    N-->>A: caller's words as text
    A-->>P: input_transcript (C1, new)
    P-->>G: InputTranscript chunk
    G-->>C: caption for the client (C2)
    G-->>U: on_transcript: client line (C2)
    N-->>A: hands off, PM to Architect (native)
    A-->>P: agent_changed (v1)
    P-->>G: AgentChanged chunk
    G-->>U: on_agent_changed (C2)
    N-->>A: Architect's audio + text
    A-->>P: audio_delta, transcript_delta
    P-->>G: paced audio + text
    G-->>C: Architect's voice + live caption (C2)
    G-->>U: on_transcript: Architect line, at turn end (C2)
```

### C1. The caller's words as an event

- Add a stream event, `InputTranscript` (`core/event.py`, next to `AgentChanged`). It carries one finished caller
  utterance as text.
- Add a `RealtimeRunner` callback event, `input_transcript`, to the contract's list of events.
- Map it in both adapters from what the SDK already produces:
  - **ADK:** an event with `author == "user"` and a finished `input_transcription`.
  - **OpenAI:** the `input_audio_transcription_completed` model event.
- The pool emits it **in spoken order** with the agents' output, so the transcript reads in the right order.
- **No new AK setting.** It appears when the SDK's own input transcription is on:
  - ADK: on by default. `RunConfig.input_audio_transcription` defaults to on
    (`google/adk/agents/run_config.py:127`).
  - OpenAI: set `input_audio_transcription` in the session's model settings, through `Module.run_options`.
- An edge that does not use it (the existing examples) ignores it.
- **Test:** for each SDK, a scripted caller utterance gives exactly one `InputTranscript` chunk, before the reply that
  answers it.

### C2. Live captions and edge hooks

- **Live captions:** the LiveKit gateway publishes text as it plays.
  - Agent text deltas go out on a LiveKit text stream from the speaking agent's participant, paced with the audio.
  - The caller's line goes out attributed to the caller.
  - Use LiveKit's transcription conventions, so standard LiveKit client components can show the captions
    ([LiveKit text docs](https://docs.livekit.io/agents/build/text/)):
    - the text stream topic `lk.transcription`;
    - the attributes `lk.transcribed_track_id`, `lk.segment_id` and `lk.transcription_final`;
    - the sender identity is the transcribed participant.
- **Keep today's turn-end chat message**, so existing clients keep working.
- **Three hooks for server code**, as overridable methods on `StatefulEdgeAdapter`. Each does nothing by default, so
  existing edges are unchanged:
  - `on_transcript(line)`: one `TranscriptLine` (speaker, `user` or `agent`, text, time, message id, `typed`) for each
    finished line.
    - The LiveKit gateway calls it once for each finished agent turn (per speaker, split at handoffs) and once for each
      caller line.
    - **A message the client types in the room is a caller line too**, with `typed=True`. It is staged for the model as
      before; the hook is what lets a server read it. An agent participant's own chat is ignored, as before.
    - An interrupted turn gives the part that was spoken, marked `interrupted`.
  - `on_agent_changed(agent, previous)`: when the speaking agent changes, in order with the lines.
  - `on_error(message)`: when an error chunk reaches the edge, besides today's chat text.
- Hooks must never block the audio. Each edge runs its hooks in order on one worker thread of its own, off the
  delivery path. A hook that raises is logged and ignored.
- **Example:** the use case subclasses the gateway and turns each hook call into an event-log entry (A5).
- **Test:** a scripted turn with a handoff and an error checks three things: lines and speaker changes arrive in
  order with the right speaker, captions come from the right participant, and a hook that raises does not stop the
  audio.

### C3. Start and stop a gateway while the app runs

- Extend `GatewayRunner` (no new sibling class) so it can **start in the background**. It runs the gateway on its own
  thread and returns once the gateway has joined the room or failed.
- Add a **stop** that ends that one gateway cleanly. It leaves the room and removes its registry entry.
- Gateways started at boot through `IOHandler.run(gateways=...)` behave as today.
- A background gateway still stops when the process shuts down (`ThreadRunner.shutdown_event`).
- **Works for any `StatefulEdgeAdapter`**, not only LiveKit.
- **Test:** start two gateways after boot, stop one, and the other keeps working. Each reply reaches only its own room.

### C4. End a realtime session at once

- When an edge stops (C3, or the room closing), it sends an **end-of-session control** on the input queue for its
  session id. This uses the existing queue, not a new one.
- The realtime pool closes that session's native connection at once, instead of waiting up to 300 s for idle eviction.
- It works when the gateway and the pool run in different processes, because it goes through the queue.
- **A late audio frame cannot reopen it.** The pool ignores input for an ended session for a short while.
- **Trailing output is dropped quietly.** The Response Handler drops chunks still on their way to an edge that has just
  ended, instead of retrying them into permanent-failure errors.
- **Test:** after the control, the adapter's `disconnect` has run. Later audio for that session id is dropped, and a
  chunk for the ended edge is not retried.

### C5. A meeting's own first words

- Turn the fixed greeting (`adapter.py:258`) into an overridable gateway method that returns the opening prompt, or
  `None` to send nothing.
- Its default is today's text, so existing examples behave as today.
- **Example:** the use case returns *"Open the meeting as the PM: greet {name} and ask what they want to build."*
- **Test:** returning `None` sends no opening request, and a custom prompt is sent once.

### C6. Back off after a failed native session

- **The problem:** a native session that fails right after it opens (a bad setting, a quota error) was replaced by the
  next audio frame, about every 100 ms. Each replacement failed again, sent an error chunk to the room and hit the model
  provider.
- **The pool backs off per session.** After a failure, input for that session is dropped for 1 s, then 2 s, 4 s... up to
  30 s for each further failure in a row. A new connection is not opened before that time.
- **It resets:** a connection that produced output (audio, a transcript or a turn end) before it failed starts the count
  again; ending the session clears it.
- **Not config:** the delays are constants of the pool, like its other timeouts.
- **Test:** repeated immediate failures drop input between attempts with delays of 1, 2, 4... s; a connection that
  produced output restarts the count; ending the session clears it.
