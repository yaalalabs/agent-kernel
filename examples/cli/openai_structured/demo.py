from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent
from pydantic import BaseModel


class ContactCard(BaseModel):
    """Structured contact details extracted from free-form text."""

    name: str
    email: str
    phone: str | None


# Setting output_type on the agent makes the OpenAI Agents SDK produce a ContactCard
# instance instead of plain text. Agent Kernel detects this and returns the reply as an
# AgentReplyAny whose `content` is the structured result as a dict. String-oriented
# consumers such as the CLI render it as its JSON serialization.
contact_agent = Agent(
    name="contact",
    instructions="You extract contact details from the user's message. "
    "Fill in only the fields that are present in the message and set the rest to null.",
    output_type=ContactCard,
)

OpenAIModule([contact_agent])

if __name__ == "__main__":
    CLI.main()
