from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.whatsapp import AgentWhatsAppRequestHandler

from agent import AGENTS

OpenAIModule(AGENTS)


if __name__ == "__main__":
    handler = AgentWhatsAppRequestHandler()
    RESTAPI.run([handler])
