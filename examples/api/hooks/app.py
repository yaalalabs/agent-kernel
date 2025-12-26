from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent

from hooks import DisclaimerHook, GuardRailHook, RAGHook

# Create a simple question-answering agent
qa_agent = Agent(
    name="qa_assistant",
    instructions=(
        "You are a helpful AI assistant that answers questions accurately. "
        "Keep your responses concise and informative."
    ),
)

# Register the agent with the OpenAI module
# Register pre-execution hooks in order: RAG hook first (to inject context), then GuardRail (to validate input)
# Register post-execution hooks to add disclaimer to responses
# The hooks will be executed in the order they are provided
OpenAIModule([qa_agent]).pre_hook(qa_agent, [RAGHook(), GuardRailHook()]).post_hook(qa_agent, [DisclaimerHook()])

if __name__ == "__main__":
    RESTAPI.run()
