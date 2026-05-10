import os

from agentkernel.api import RESTAPI
from agentkernel.livekit import AgentLiveKitRequestHandler
from agentkernel.openai import OpenAIModule
from agents import Agent as OpenAIAgent

voice_agent = OpenAIAgent(
    name="my-voice-agent",
    handoff_description="Agent for voice interactions",
    instructions="You are a helpful and concise voice assistant. Do not use markdown or emojis.",
)

OpenAIModule([voice_agent])

if __name__ == "__main__":
    RESTAPI.run([AgentLiveKitRequestHandler()])
