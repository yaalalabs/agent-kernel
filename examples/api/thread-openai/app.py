from agentkernel.api import RESTAPI
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.thread import AgentThreadRequestHandler
from agents import Agent


def send_summary_email(recipient: str) -> str:
    """
    Simulate emailing a summary of this conversation; nothing is actually sent. Requires human
    approval before it runs.

    :param recipient: The address the summary would go to.
    :return: A note that the send was simulated.
    """
    return f"Simulated: a summary would be sent to {recipient}. Nothing was emailed."


assistant_agent = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Give short and direct answers.",
    # Gated so the thread records the pause and its decision, not just the turns either side.
    tools=OpenAIToolBuilder.bind([send_summary_email], needs_approval=True),
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
