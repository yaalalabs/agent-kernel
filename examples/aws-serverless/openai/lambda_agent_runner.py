from agentkernel.aws import ServerlessAgentRunner
from agentkernel.openai import OpenAIModule
from agentkernel.secret import SecretManager
from agents import Agent, set_default_openai_key

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the SDK in memory; it is never written back to os.environ.
set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. no reasoning and no need for steps explanation. Just give the final answer. \
        If asked about anything else, refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
    model="openai/gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[history_agent, math_agent],
    model="openai/gpt-4.1-mini",
)

OpenAIModule([triage_agent, math_agent, history_agent])


handler = ServerlessAgentRunner.handle
