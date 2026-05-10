from agentkernel.api import RESTAPI
from agentkernel.framework.autogen import AutogenModule

from autogen import ConversableAgent

# Create a conversable agent for testing
general_agent = ConversableAgent(
    name="general",
    system_message="You provide assistance with general queries. Give short and clear answers.",
    llm_config={"config_list": [{"model": "gpt-4o", "api_type": "openai"}]},
    human_input_mode="NEVER",
)

AutogenModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
