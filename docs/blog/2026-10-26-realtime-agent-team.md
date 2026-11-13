---
slug: /realtime-agent-team
title: "Your Voice Agent Can Bring in a Teammate"
authors: [pulindu]
tags: [agent-kernel, realtime, livekit, voice-agents, multi-agent, openai-agents-sdk, google-adk]
image: /img/blog/realtime-agent-team-cover.png
description: "Agent Kernel connects LiveKit audio to native OpenAI Agents SDK and Google ADK sessions, supports live agent handoffs, runs your hooks on the call, stores the session when it ends, and traces each call."
---

# Your Voice Agent Can Bring in a Teammate

![A caller on a LiveKit support call, with an active agent, a specialist in the room, live captions, and call events.](/img/blog/realtime-agent-team-cover.png)

**“I can help with that. Let me bring in our billing specialist.”** A voice agent can make that handoff without ending the call or asking the caller to start over. The specialist has a separate identity in the same LiveKit room and takes the next turn under their own name.

That experience needs more than a model that can speak. Audio has to keep moving, the right agent has to take the floor, and the caller must be able to interrupt. Agent Kernel connects those pieces to native live sessions from the OpenAI Agents SDK and Google ADK.

<!-- truncate -->

## See It on a Real Call

Here is a flight disruption desk built on this path. A traveller whose flight was cancelled talks to a concierge, a rebooking specialist and a care specialist by voice. The case board starts empty and fills in as the agents work: the booking once the concierge finds it, then the new flight, the meal voucher and the compensation claim. Watch the handoffs between the three agents, each one taking the call under its own name and voice. (This is a recording of a live call. The three agents are live Gemini voices; the caller's voice is synthetic.)

<video
  controls
  playsInline
  preload="auto"
  style={{width: '100%', borderRadius: '12px', margin: '1rem 0 1.5rem'}}
>
  <source src="/video/realtime-flight-desk.mp4" type="video/mp4" />
  A recording of a live flight disruption call: a caller whose flight was cancelled talks to a concierge, a rebooking specialist and a care specialist, hears each agent in its own voice, and watches the case board fill in as the agents work.
</video>

## A Voice Call Is an Active Stream

In a text chat, the agent can wait for a message and then return an answer. A voice call keeps moving: microphone audio arrives in small chunks, the model streams audio and text back, and the caller may speak before the response is finished.

The LiveKit gateway brings caller audio and room chat into Agent Kernel's realtime pipeline. The pipeline keeps a native live session for the AK session, delivers input, and paces streamed output back to the room. If the caller talks over the agent, the response is interrupted and audio the caller has not heard is cleared from playback.

![The realtime path from caller audio through LiveKit, the Agent Kernel pipeline, and a native OpenAI or Google live session, with streamed output and call events returning to the app.](/img/blog/realtime-agent-team-architecture.png)

## Let the Framework Choose the Next Speaker

Agent Kernel uses each framework's own live agent and handoff behavior. OpenAI's Agents SDK runs a native `RealtimeSession`; Google ADK runs `Runner.run_live()` with a `LiveRequestQueue`. Their native agents decide when to call a tool or transfer the conversation to another agent.

For example, a general support agent can hand a billing question to a billing specialist. Agent Kernel maps the handoff to LiveKit participants, and the room can mark which agent is active. Only the active voice agent speaks to the caller. The agents do not talk over each other, and an agent's own audio is not fed back as caller audio.

![A support-call screen after the caller interrupts: the agent stops, the caller's words appear, and the playback panel distinguishes heard audio from audio that was cleared.](/img/blog/realtime-agent-team-story.png)

The key boundary is simple: **the native SDK owns turns, tools, and handoffs; Agent Kernel owns the connection between that session and the live room.** That keeps framework behavior intact while giving the application one place to manage the room, audio flow, session identity, playback, and cleanup.

## Keep Your Application in the Conversation

The call can produce more than audio. LiveKit clients can show agent captions as the words are spoken. Caller transcript lines are available when SDK input transcription is enabled; ADK enables it by default, while OpenAI needs it configured in the session settings.

To follow the call from your own application, subclass `LiveKitEdgeAdapter` and override `deliver_chunk`. It receives each streamed chunk: audio, text, finished caller transcript lines (`InputTranscript`), agent changes (`AgentChanged`) and errors. Those events can update a call view or feed your own records. Keep slow work off this path, because the same path delivers the call's audio.

A call is a LiveKit room. LiveKit tells your app when a room opens (a signed webhook to `/livekit/webhook`), and Agent Kernel starts one edge for that room, with the room name as the session id. When the last caller leaves, the edge ends the session and closes its live session. A failed connection backs off before retrying, rather than reopening on every incoming audio chunk.

```python
from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler

if __name__ == "__main__":
    # One edge per LiveKit room, started and stopped by LiveKit's own room webhooks.
    IOHandler.run(handlers=[EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter())])
```

Override `should_start(session_id)` on the lifecycle adapter to choose which rooms get an edge, and `opening_prompt` on the edge to change how a call opens.

## Run Your Own Hooks on the Call

A live call is not a black box. Agent Kernel runs the same hooks you use in other modes, in the process that serves the call. It provides the hook points; what a hook does is your code.

- **Typed text** goes through `PreHook.on_run`. A hook can rewrite it, or stop it before the model sees it.
- **Caller audio** goes through the optional `PreHook.on_stream_input`, one chunk at a time. A hook can pass a chunk on, change it, or drop it.
- **Model output** goes through `PostHook.on_stream_event`. A hook sees each audio, text and transcript event, and a `MessageEnd` closes every turn.

![Where hooks, the call trace and the stored session sit around a live call.](/img/blog/realtime-agent-team-hooks.png)

The [voice guardrails example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/livekit-voice/openai/guardrails) shows two hooks in practice. One redacts emails, card numbers and phone numbers in typed chat. The other watches the agent's live transcript and cuts the agent off when it says a blocked phrase.

Two limits to know:

- Agent Kernel's built-in input guardrail checks typed text only. Caller audio reaches the model unless a pre-hook handles it.
- The built-in output guardrail does not run on a streamed reply, so write a post-hook for output you must control. A hook sits on the playback path, so a slow hook delays audio.

## The Call Keeps Its Session and Its Trace

A call now follows the same run lifecycle as a text request:

- **Session:** `Session.current()` and `Agent.current()` work inside native tools and hooks. When a call ends normally, Agent Kernel stores the session once, so a durable store (`redis`, `dynamodb` and others) keeps what the call changed. A call that fails stores nothing.
- **Trace:** with `trace.enabled: true`, each call is one span, tagged with the session id in Langfuse, Logfire, OpenLLMetry and CloudWatch. Google ADK adds its own agent and tool spans inside it. The OpenAI realtime session creates no spans of its own, so an OpenAI call shows as one span with its duration and errors.

## What to Plan For

- The realtime adapters currently support the OpenAI Agents SDK and Google ADK, using each SDK's native live path.
- A native framework handoff lets the next specialist take the speaking turn while the caller stays in the same live conversation.
- Handoff timing depends on the framework. An ADK transfer can open a new Gemini Live session, so plan for that transition instead of promising an instant switch.
- A tool that needs human approval cannot run on a LiveKit call, because the room has no way to ask. The connection fails instead of approving it.

## Get Started

1. Set `execution.mode: realtime` in `config.yaml`, and the LiveKit settings (`AK_LIVEKIT__URL`, `AK_LIVEKIT__API_KEY`, `AK_LIVEKIT__API_SECRET`).
2. Register your native live agents, with handoffs, in an OpenAI Agents SDK or Google ADK module.
3. Run the `IOHandler` with the edge handler shown above, and add `https://<your-host>/livekit/webhook` as a webhook in your LiveKit project. On a laptop, point a local LiveKit server at `http://127.0.0.1:8000/livekit/webhook`.
4. Join a room. The agents join it as participants of their own.

The [LiveKit voice examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/livekit-voice) include single-agent calls and multi-agent handoffs for OpenAI and Google ADK.

## The Bottom Line

A voice agent that can only talk is a demo. A voice agent that can bring in a specialist, take an interruption, run your hooks and leave a trace is a service.

With Agent Kernel, a real-time agent can listen, speak, pause for an interruption, and hand the conversation to a specialist. Your hooks, session and traces come along, and the caller stays in the same room.

Agent Kernel is open source under Apache 2.0.

- LiveKit integration guide: [integrations/livekit](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/integrations/livekit.md)
- Realtime hooks: [integrations/hooks](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/integrations/hooks.md#realtime-hooks)
- Call traces: [advanced/traceability](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/advanced/traceability.md#realtime-calls)
- Audio, handoffs and session lifetime through the pipeline: [architecture/realtime-internals](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/architecture/realtime-internals.md)
- Voice guardrails example: [livekit-voice/openai/guardrails](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/livekit-voice/openai/guardrails)
- GitHub: https://github.com/yaalalabs/agent-kernel
