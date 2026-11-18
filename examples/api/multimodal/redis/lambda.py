import litellm
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule
from agentkernel.secret import SecretManager
from agents import Agent, set_default_openai_key

# OPENAI_API_KEY from the environment when set, else from SSM (/ak/<prefix>/openai_api_key). The value is
# handed to the SDKs in memory, never written back to os.environ: the agents SDK for the agent, and LiteLLM
# for the multimodal pre-hook's attachment descriptions and the analyze_attachments tool.
openai_key = SecretManager.current().get("OPENAI_API_KEY")
set_default_openai_key(openai_key)
litellm.openai_key = openai_key

general_agent = Agent(
    name="general",
    instructions="You provide assistance with general queries. Give short and clear answers",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([general_agent])

handler = Lambda.handler
