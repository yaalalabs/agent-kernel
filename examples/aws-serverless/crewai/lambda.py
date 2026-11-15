import os

os.environ["CREWAI_TRACING_ENABLED"] = "false"

from agentkernel.aws import Lambda
from agentkernel.crewai import CrewAIModule
from agentkernel.secret import SecretManager

from crewai import LLM, Agent

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the CrewAI LLM in memory; it is never written back to os.environ.
openai_key = SecretManager.current().get("OPENAI_API_KEY")

math_agent = Agent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
    verbose=False,
    tracing=False,
    llm=LLM(model="openai/gpt-4.1-mini", api_key=openai_key),
)

history_agent = Agent(
    role="history",
    goal="Specialist agent for historical questions",
    backstory="You provide assistance with historical queries. Explain important events and context clearly.",
    verbose=False,
    tracing=False,
    llm=LLM(model="openai/gpt-4.1-mini", api_key=openai_key),
)

CrewAIModule([math_agent, history_agent])

handler = Lambda.handler
