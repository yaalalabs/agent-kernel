from agentkernel import Agent as AKAgent
from agentkernel import PreHook, Session
from agentkernel.api import RESTAPI
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestAny, AgentRequestText
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder
from fastapi import APIRouter
from pydantic_ai import Agent

from tool import fetch_customer_activity

# Provider-agnostic: swap for "anthropic:...", "google-gla:...", etc. (install the matching provider
# extra, e.g. pydantic-ai-slim[anthropic]). Requires OPENAI_API_KEY for the model below.
MODEL = "openai:gpt-4o-mini"

general_agent = Agent(
    model=MODEL,
    name="general",
    description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

support_agent = Agent(
    model=MODEL,
    name="support",
    description="Customer feedback and support agent",
    instructions="You are a customer feedback agent. When I give you the name of the customer you will generate "
    "the feedback conversation. I will also tell the banking operation this customer carried out. "
    "You will only ask questions on satisfaction based on only the activities the user carried out. "
    "When I provide the name and the work, you will assume you are having a conversation with this "
    "customer itself and mimic the conversation. Ask questions one by one and gather answers and show "
    "the summary once the conversation is over.",
    tools=PydanticAIToolBuilder.bind([fetch_customer_activity]),
)


# Pydantic AI has no handoffs= primitive; the triage agent routes with delegation-via-tool.
async def ask_general(question: str) -> str:
    """Delegate a general-knowledge question to the general agent."""
    return str((await general_agent.run(question)).output)


async def ask_support(question: str) -> str:
    """Delegate a customer-support / banking-feedback question to the support agent."""
    return str((await support_agent.run(question)).output)


triage_agent = Agent(
    model=MODEL,
    name="triage",
    description="Front-line agent that routes each question to the right specialist",
    instructions="You determine which specialist should answer the user's question and call the matching tool: "
    "ask_support for customer-support / banking-feedback questions, ask_general for everything else. "
    "Return the specialist's answer directly.",
    tools=PydanticAIToolBuilder.bind([ask_general, ask_support]),
)

# Optional custom route to add your own endpoints
router = APIRouter()


@router.post("/deposit")
async def run(req: dict):
    amount = req.get("amount")
    return {"result": f"Deposited ${amount} over the counter"}


RESTAPI.add(router=router)

# End of optional code block for REST API mode


# Optionally Using additional context passed in a pre-hook to be used in a RAG
class RAGPreHook(PreHook):
    async def on_run(
        self, session: Session, agent: AKAgent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        """
        REST API will pack all keys and their values from the request body into AgentRequestAny objects.
        In this example, we look for an AgentRequestAny with name 'additional_context' to get the additional_context (i.e. a dictionary)
        we packed into the request body under the key 'additional_context'.
        In this example, we are using it to fetch the bank agent's name and assume that additional_context['bank_agent'] is the bank agent's name
        """
        additional_context = None
        prompt = ""
        for req in requests:
            if isinstance(req, AgentRequestText):
                prompt = req.prompt

            if isinstance(req, AgentRequestAny) and req.name == "additional_context":
                additional_context = req.content
                break
        bank_agent = (
            additional_context.get("bank_agent") if additional_context and hasattr(additional_context, "get") else None
        )

        # If bank_agent is not provided, return the original requests list unchanged
        if bank_agent is None:
            return requests

        # Otherwise, add the bank agent to the prompt without dropping non-text requests (e.g. multimodal attachments)
        modified_requests: list[AgentRequest] = []
        modified_any = False
        for r in requests:
            if isinstance(r, AgentRequestText):
                modified_requests.append(AgentRequestText(prompt=r.prompt + f". My bank agent was {bank_agent}."))
                modified_any = True
            else:
                modified_requests.append(r)
        if not modified_any:
            modified_requests.append(AgentRequestText(prompt=f"My bank agent was {bank_agent}."))
        return modified_requests

    def name(self) -> str:
        return "bank_agent_prehook"


# Initialize Pydantic AI module and attach RAG pre-hook to the support agent
PydanticAIModule([triage_agent, general_agent, support_agent]).pre_hook(support_agent, [RAGPreHook()])

# Entry point referenced by the Dockerfile (from app import runner; runner()).
runner = RESTAPI.run

if __name__ == "__main__":
    runner()
