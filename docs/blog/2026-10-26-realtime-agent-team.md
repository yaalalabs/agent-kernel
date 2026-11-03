---
slug: /realtime-agent-team
title: "Your Voice Agent Can Bring in a Teammate"
authors: [pulindu]
tags: [agent-kernel, realtime, livekit, voice-agents, multi-agent, openai-agents-sdk, google-adk]
image: /img/blog/realtime-agent-team-cover.png
description: "Agent Kernel connects LiveKit audio to native OpenAI Agents SDK and Google ADK sessions, supports live agent handoffs, and makes captions and call events available to the room and application."
---

# Your Voice Agent Can Bring in a Teammate

![A caller on a LiveKit support call, with an active agent, a specialist in the room, live captions, and call events.](/img/blog/realtime-agent-team-cover.png)

**“I can help with that. Let me bring in our billing specialist.”** A voice agent can make that handoff without ending the call or asking the caller to start over. The specialist has a separate identity in the same LiveKit room and takes the next turn under their own name.

That experience needs more than a model that can speak. Audio has to keep moving, the right agent has to take the floor, and the caller must be able to interrupt. Agent Kernel connects those pieces to native live sessions from the OpenAI Agents SDK and Google ADK.

<!-- truncate -->

## A voice call is an active stream

In a text chat, the agent can wait for a message and then return an answer. A voice call keeps moving: microphone audio arrives in small chunks, the model streams audio and text back, and the caller may speak before the response is finished.

The LiveKit gateway brings caller audio and room chat into Agent Kernel's realtime pipeline. The pipeline keeps a native live session for the AK session, delivers input, and paces streamed output back to the room. If the caller talks over the agent, the response is interrupted and audio the caller has not heard is cleared from playback.

![The realtime path from caller audio through LiveKit, the Agent Kernel pipeline, and a native OpenAI or Google live session, with streamed output and call events returning to the app.](/img/blog/realtime-agent-team-architecture.png)

## Let the framework choose the next speaker

Agent Kernel uses each framework's own live agent and handoff behavior. OpenAI's Agents SDK runs a native `RealtimeSession`; Google ADK runs `Runner.run_live()` with a `LiveRequestQueue`. Their native agents decide when to call a tool or transfer the conversation to another agent.

For example, a general support agent can hand a billing question to a billing specialist. Agent Kernel maps the handoff to LiveKit participants, and the room can mark which agent is active. Only the active voice agent speaks to the caller. The agents do not talk over each other, and an agent's own audio is not fed back as caller audio.

![A support-call screen after the caller interrupts: the agent stops, the caller's words appear, and the playback panel distinguishes heard audio from audio that was cleared.](/img/blog/realtime-agent-team-story.png)

The key boundary is simple: **the native SDK owns turns, tools, and handoffs; Agent Kernel owns the connection between that session and the live room.** That keeps framework behavior intact while giving the application one place to manage the room, audio flow, session identity, playback, and cleanup.

## Keep the application in the conversation

The call can produce more than audio. LiveKit clients can show agent captions as the words are spoken. Caller transcript lines are available when SDK input transcription is enabled; ADK enables it by default, while OpenAI needs it configured in the session settings. A gateway subclass can handle finished transcript lines, agent handoffs, and errors with `on_transcript`, `on_agent_changed`, and `on_error`. Those events can update a call view or feed the application's own records. The hooks run on their own worker thread, so slow application work does not hold up audio delivery.

In the single-process `in_memory` setup, the `IOHandler` hosts the gateway and response handler. The application controls when its gateway starts and stops: `GatewayRunner.start_background()` starts a room gateway when a call begins, and `stop()` ends it and sends a control message to close its live session. A failed connection backs off before retrying, rather than reopening on every incoming audio chunk.

```python
from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway

gateway = LiveKitEdgeGateway(session_id="support-42", agent_name="triage")
runner = GatewayRunner(gateway)
runner.start_background()  # start when the room is ready

# The call runs here.

runner.stop()  # leave the room and close its live session
```

## What to plan for

- The realtime adapters currently support the OpenAI Agents SDK and Google ADK, using each SDK's native live path.
- A native framework handoff lets the next specialist take the speaking turn while the caller stays in the same live conversation.
- Handoff timing depends on the framework. An ADK transfer can open a new Gemini Live session, so plan for that transition instead of promising an instant switch.

## Try the realtime path

The [LiveKit voice examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/livekit-voice) include single-agent calls and multi-agent handoffs for OpenAI and Google ADK. The [LiveKit integration guide](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/integrations/livekit.md) covers setup, controls, and current boundaries. The [realtime internals guide](https://github.com/yaalalabs/agent-kernel/blob/develop/docs/docs/architecture/realtime-internals.md) traces audio, handoffs, and session lifetime through the pipeline.

With Agent Kernel, a real-time agent can listen, speak, pause for an interruption, and hand the conversation to a specialist—while the caller stays in the same room.
