from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule
from agentkernel.thread import AgentThreadRequestHandler
from agents import Agent

assistant_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
    model="openai/gpt-4.1-mini",
)

OpenAIModule([assistant_agent])

if __name__ == "__main__":
    # Mounting AgentThreadRequestHandler (instead of the default handler) is what
    # enables Conversation Thread Support: it serves the standard chat routes with
    # thread recording plus the thread read routes. The `thread` block in
    # config.yaml only selects the store backend and naming.
    #
    # Who is calling comes from the `identity` block in config.yaml: every route runs
    # the identity dependency, which turns the bearer token into the request's
    # principal, and a thread belongs to that principal. The handler refuses to build
    # without the block, since its routes serve authenticated callers only.
    RESTAPI.run(handlers=[AgentThreadRequestHandler()])
