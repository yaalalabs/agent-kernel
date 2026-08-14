from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

from hooks import HistoryTrimHook

# Create a simple question-answering agent
qa_agent = Agent(
    name="qa_assistant",
    instructions=(
        "You are a helpful AI assistant that answers questions accurately. "
        "Keep your responses concise and informative."
    ),
)

# Register the agent with the OpenAI module
# Register a post-execution hook that caps the framework-native session history so it
# never grows unbounded
OpenAIModule([qa_agent]).post_hook(qa_agent, [HistoryTrimHook()])

if __name__ == "__main__":
    RESTAPI.run()
