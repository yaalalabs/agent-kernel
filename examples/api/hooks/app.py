from agentkernel.api import RESTAPI
from agentkernel.core import GlobalRuntime
from agentkernel.openai import OpenAIModule
from agents import Agent

from hooks import GuardRailHook, RAGHook

# Create a simple question-answering agent
qa_agent = Agent(
    name="qa_assistant",
    instructions=(
        "You are a helpful AI assistant that answers questions accurately. "
        "Keep your responses concise and informative."
    ),
)

# Register the agent with the OpenAI module
OpenAIModule([qa_agent])

# Get the runtime instance and register hooks
runtime = GlobalRuntime.instance()

# Register hooks in order: RAG hook first (to inject context), then GuardRail (to validate input)
# The hooks will be executed in the order they are provided
runtime.register_pre_hooks("qa_assistant", [RAGHook(), GuardRailHook()])

if __name__ == "__main__":
    RESTAPI.run()
