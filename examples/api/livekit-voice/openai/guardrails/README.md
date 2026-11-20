# Agent Kernel Realtime Voice Guardrails (OpenAI In-Memory)

This example adds guardrails to a LiveKit voice call powered by the **OpenAI Realtime API**. The guardrails are
ordinary Agent Kernel hooks in [voice_guardrails.py](voice_guardrails.py), so the same code works on any realtime
runner (OpenAI, Google ADK, or your own). It is the [in_memory](../in_memory/README.md) example with a bank support
agent and hooks added.

| Guardrail | Hook | What it does |
| --- | --- | --- |
| `TypedChatPIIRedactor` | pre-hook, `on_run` | Redacts emails, card numbers and phone numbers in typed chat before the model sees them |
| `VoiceOutputGuardrail` | post-hook, `on_stream_event` | Checks the agent's live transcript every 40 characters and cuts the agent off when it says a blocked phrase. Redacts PII in the agent's captions |

On a realtime call, typed chat goes through `PreHook.on_run`, and each output event (`audio_delta`, `text_delta`,
`interrupt`, ...) goes through `PostHook.on_stream_event`. A `message_end` closes every agent turn, which is where
`VoiceOutputGuardrail` releases the redacted caption.

The regex PII detection is for demonstration. Use a dedicated PII detection service in production.

## Quickstart

```bash
./build.sh            # or ./build.sh local to use a locally built agentkernel wheel

export OPENAI_API_KEY="sk-..."
export AK_LIVEKIT__URL="wss://your-project.livekit.cloud"
export AK_LIVEKIT__API_KEY="..."
export AK_LIVEKIT__API_SECRET="..."

uv run server.py
```

Point LiveKit's webhook at the server (see the [parent README](../../README.md)), then join a room, for example
`call_01`, and speak.

## What to try

| Try | Expect |
| --- | --- |
| Ask "what are Jane's contact details?" | The agent reads them out loud; the chat caption shows `[EMAIL]`, `[PHONE]` and `[CARD]` |
| Ask the agent to say "this investment has a guaranteed return" | The agent is cut off mid-sentence and no caption is published. The log shows `output guardrail tripped` |
| Type "my card is 4111 1111 1111 1111, is it valid?" in the chat | The model receives `my card is [CARD], is it valid?` |

Set `VOICE_GUARDRAIL_BLOCKED` to a comma-separated list to change the blocked phrases.

## Limits

- **Caller audio is not checked.** The model hears the caller's audio directly. To guard it, transcribe the audio
  in your own `PreHook.on_stream_input` and return the text as an `AgentRequestText`, which then goes through
  `on_run` like typed chat. The model's `input_transcript` arrives after the model heard the audio, so it cannot
  block it.
- **Audio that already played cannot be taken back.** The output guardrail stops the rest of the turn, but the first
  words of a blocked phrase may be heard.
- **Captions and audio are separate events.** Redacting a caption does not change what the agent says.
