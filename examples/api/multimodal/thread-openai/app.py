from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.thread import AgentThreadRequestHandler
from agents import Agent

general_agent = Agent(
    name="general",
    instructions="You provide assistance with general queries. Give short and clear answers",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([general_agent])

if __name__ == "__main__":
    # Mounting AgentThreadRequestHandler (instead of the default handler) is what
    # enables Conversation Thread Support: it serves the standard chat routes with
    # thread recording plus the thread read routes. The `thread` block in
    # config.yaml only selects the store backend and naming.
    #
    # Who is calling comes from the `identity` block in config.yaml: the bearer token
    # becomes the request's principal, and a thread belongs to that principal. The
    # handler refuses to build without the block.
    RESTAPI.run(handlers=[AgentThreadRequestHandler()])
