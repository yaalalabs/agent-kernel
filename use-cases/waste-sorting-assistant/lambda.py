from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule

from agent import AGENTS

OpenAIModule(AGENTS)

handler = Lambda.handler
