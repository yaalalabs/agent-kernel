from agentkernel import GlobalRuntime
from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agents import Agent,function_tool

from hooks import  RAGHook

from agentkernel import KeyValueCache, Runtime

@function_tool
def query_private_knowledge_base(query:str ) -> str:
    """
    Simulated function to query a private knowledge base.
    In a real implementation, this would query a secure database or document store.
    """
    # knowledge base
    kb = []
    cache:KeyValueCache = Runtime.instance().get_volatile_cache()
    rag_context = cache.get("rag_context")
    print(f"***************** query_private_knowledge_base: Retrieved context from volatile cache: {rag_context}")
    if rag_context:
        kb.extend(rag_context)
    
    for item in kb:
        if isinstance(item, dict):
            for topic, context in item.items():
                print(f">>>>>>>>>>>>>>>>>>>>>>> Checking topic '{topic}' against query. {query}")
                if topic in query:
                    return context
    return "No relevant information found in the knowledge base."

# Create a simple question-answering agent
senior_agent = Agent(
    name="senior_assistant",
    instructions=(
        "You are a helpful AI assistant that answers questions accurately. You must always call the provided tool to fetch additional information before answering any question"
        "If you cant find any information, respond with 'I don't know'."
    ),
    tools=[query_private_knowledge_base],
)

junior_agent = Agent(
    name="junior_assistant",
    instructions=(
        "You are a helpful AI assistant that answers questions accurately. You must always call the provided tool to fetch additional information before answering any question"
        "If you cant find any information, respond with 'I don't know'."
    ),
    tools=[query_private_knowledge_base],
)
# Register the agent with the OpenAI module
OpenAIModule([senior_agent, junior_agent])

# Get the runtime instance and register hooks
runtime = GlobalRuntime.instance()

# Register pre-execution hooks for senior agent: RAG hook to inject context. Junior agent has no extra RAG support
runtime.register_pre_hooks("senior_assistant", [RAGHook()])

if __name__ == "__main__":
    RESTAPI.run()
