from agentkernel.integration.livekit import AgentKernelLLM

from livekit import agents
from livekit.plugins import deepgram, openai, silero


async def entrypoint(ctx: agents.JobContext):
    agent_name = "my-voice-agent"

    agent = agents.VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=AgentKernelLLM(agent_name=agent_name, session_id=ctx.room.name),
        tts=openai.TTS(),
        instructions="You are a helpful voice assistant.",
    )

    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    session = agents.AgentSession()
    await session.start(agent, room=ctx.room)


if __name__ == "__main__":
    agents.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, worker_type=agents.WorkerType.ROOM))
