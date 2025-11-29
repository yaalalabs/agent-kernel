from agentkernel import Agent as AKAgent
from agentkernel import GlobalRuntime, Prehook, Session
from agentkernel.api import RESTAPI
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestAny, AgentRequestText
from agentkernel.openai import OpenAIModule
from agents import Agent
from fastapi import APIRouter

from tool import fetch_customer_activity

general_agent = Agent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

customer_support_agent = Agent(
    name="support",
    instructions="You are a customer feedback agent. When I give you the name of the customer you will generate "
    "the feedback conversation. I will also tell the banking operation this customer carried out. "
    "You will only ask questions on satisfaction based on only the activities the user carried out. "
    "When I provide the name and the work, you will assume you are having a conversation with this "
    "customer itself and mimic the conversation. Ask questions one by one and gather answers and show "
    "the summary once the conversation is over.",
    tools=[fetch_customer_activity],
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[general_agent, customer_support_agent],
)

# Optional custom route to add your own endpoints
router = APIRouter()


@router.post("/deposit")
async def run(req: dict):
    amount = req.get("amount")
    return {"result": f"Deposited ${amount} over the counter"}


RESTAPI.add(router=router)
# End of optional code block for REST API mode

OpenAIModule([triage_agent, general_agent, customer_support_agent])


# Optionally Using additional context passed in a pre-hook to be used in a RAG
class RAGPreHook(Prehook):
    async def on_run(
        self, session: Session, agent: AKAgent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        """
        REST API will pack all keys and their values from the request body into AgentRequestAny objects.
        In this example, we look for an AgentRequestAny with name 'additional' to get the additional_context (i.e. a dictionary)
        we packed into the request body under the key 'additional'.
        In this example, we are using it to fetch the bank agent's name and assume that additional['bank_agent'] is the bank agent's name
        """
        additional_context = None
        prompt = ""
        for req in requests:
            if isinstance(req, AgentRequestText):
                prompt = req.text

            if isinstance(req, AgentRequestAny) and req.name == "additional":
                additional_context = req.content
                break
        bank_agent = additional_context.get("bank_agent") if additional_context and hasattr(additional_context, 'get') else None

        # If bank_agent is not provided, return the original requests list unchanged
        if bank_agent is None:
            return requests

        # Otherwise, add the bank agent to the prompt
        modified_prompt = prompt + ". My bank agent was " + bank_agent + "."

        return [AgentRequestText(text=modified_prompt)]

    def name(self) -> str:
        return "bank_agent_prehook"


GlobalRuntime.instance().register_pre_hooks("support", [RAGPreHook()])
# End of optional RAG code block

if __name__ == "__main__":
    RESTAPI.run()
