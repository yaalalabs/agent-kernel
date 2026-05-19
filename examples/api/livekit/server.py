from agentkernel.api import RESTAPI
from agentkernel.integration.livekit import AgentLiveKitRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent

general_agent = Agent(
    name="my-voice-agent",
    instructions="You are a helpful and concise voice assistant. Do not use markdown or emojis. You may receive images from the user's webcam. If an image is attached, incorporate what you see into your response naturally.",
)

OpenAIModule([general_agent])


if __name__ == "__main__":
    handler = AgentLiveKitRequestHandler()
    RESTAPI.run([handler])
