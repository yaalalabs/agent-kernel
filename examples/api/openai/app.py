from agentkernel.api import RESTAPI
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

if __name__ == "__main__":
    RESTAPI.run()
