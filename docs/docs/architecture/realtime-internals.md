---
title: Realtime Voice Internals
---

Agent Kernel uses a native live agent session for each call. The OpenAI Agents SDK or Google ADK decides which agent speaks, runs that agent's tools, and handles handoffs. Agent Kernel carries audio and text between that session and the LiveKit room.

```mermaid
flowchart LR
    H[Human in LiveKit room] --> G[LiveKit gateway]
    G --> P[AK realtime pool]
    P --> N[Native live session]
    N --> A[Coordinator agent]
    A -->|native handoff| B[Specialist agent]
    B -->|native handoff| A
    N --> P --> G --> H
```

## Who owns what

| Component | Responsibility |
| --- | --- |
| LiveKit gateway | Room participants, caller audio and chat, playback, and the active speaker's participant |
| AK realtime pool | One connection per AK session, input conversion, output pacing, queue delivery, interruptions, and cleanup |
| OpenAI `RealtimeSession` or ADK `Runner.run_live()` | Model connection, agent turns, native tools, tool results, handoffs, and native session state |

The gateway never sends an agent participant's own audio or chat back to the model. The SDK conversation stays in one AK session even when the speaking agent changes. For example, a coordinator can invite billing to answer, billing can call its invoice tool, and billing can hand the conversation back. The pool only receives the speaker changes and output.

## Runner contract

`RealtimeRunner` is the shared input and output contract. An adapter accepts caller audio with `append_audio()` and text with `send_text()`. Its callback reports `audio_delta`, `transcript_delta`, `agent_changed`, `interrupt`, `speech_started`, `done`, or `error`. The pool paces these events in order, so the next speaker is announced before their first output. The pool announces the root agent as the first speaker (`initial_speaker`); an adapter whose root does not speak, such as an ADK `Workflow`, returns `None` and reports the first speaking node itself in its `agent_changed` event, with the roster.

## Native adapters

- **OpenAI:** the entry agent is an `agents.realtime.RealtimeAgent`. One SDK `RealtimeRunner` and `RealtimeSession` serve the call. `RealtimeAgent.handoffs` select the next agent. `Module.run_options(agent, model_config=...)` sets the session model and voice.
- **Google ADK:** one `Runner.run_live()` and one `LiveRequestQueue` serve the call. `Event.author` identifies the speaker. ADK handles transfers and any Gemini connection changes. Speaking agents in a live workflow must set `mode='chat'` or `mode='task'`; ADK raises nothing for a node without one, and the caller hears nothing from it; ADK does not run `ParallelAgent` or `LoopAgent` in live mode; they fail inside ADK. Use `Gemini(speech_config=...)` for a speaking agent's voice, or `RunConfig.speech_config` for a session voice.

The SDK runs the tools; the pool does not. Before the native session starts, the pool sets `ToolContext`, `Session.current()` and `Agent.current()` once for the call, and the SDK's own tasks inherit them, so a tool sees them as it does on the unary path. The session lock is not held, since a call is one long-lived session. AK system tools (multimodal, sandbox, schedule, knowledge base) and their prompt guidance are attached as in every other execution mode; an ADK `Workflow` root holds no tools, so they attach to its speaking agents, looked up by their own names for the `agents` allow-lists.

A realtime session neither injects nor stores the AK session's `framework_context`, and the AK session is not saved when a call ends.

AK pre/post hooks and AK guardrails do not automatically run during native live turns. Use the SDK's own live hooks and guardrails where supported. A tool needing human approval or confirmation cannot continue through this LiveKit edge because the room has no decision path; both adapters fail the connection when one is requested (an OpenAI tool with `needs_approval`, an ADK `FunctionTool` with `require_confirmation`) rather than approving it.

## Connection lifetime

Each AK session has its own native session and queue. Closing one call closes its resources without closing another call.

A failed native session produces a terminal error and is removed; a later input starts a new native session. AK does not replay a transcript or restore a call after a process restart.
