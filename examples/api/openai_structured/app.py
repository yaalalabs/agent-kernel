from agentkernel import Agent as AKAgent
from agentkernel import PostHook, Session
from agentkernel.api import RESTAPI
from agentkernel.core.model import AgentReply, AgentReplyAny, AgentRequest
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
# AgentReplyAny whose `content` is the structured result as a dict. The REST API renders
# it as its JSON serialization in the `result` field of the response.
contact_agent = Agent(
    name="contact",
    instructions="You extract contact details from the user's message. "
    "Fill in only the fields that are present in the message and set the rest to null.",
    output_type=ContactCard,
)


class NormalizeContactPostHook(PostHook):
    """
    Structured replies flow through the post-hook chain as AgentReplyAny objects, so hooks
    can inspect and modify the dict content directly — no re-parsing of a stringified reply.
    This hook normalizes the extracted email address to lowercase.
    """

    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: AKAgent, agent_reply: AgentReply
    ) -> AgentReply:
        if isinstance(agent_reply, AgentReplyAny):
            email = agent_reply.content.get("email")
            if isinstance(email, str):
                agent_reply.content["email"] = email.lower()
        return agent_reply

    def name(self) -> str:
        return "normalize_contact_posthook"


OpenAIModule([contact_agent]).post_hook(contact_agent, [NormalizeContactPostHook()])

if __name__ == "__main__":
    RESTAPI.run()
