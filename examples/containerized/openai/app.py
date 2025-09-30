from agents import Agent
from ak.api import RESTAPI
from ak.openai import OpenAIModule

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

OpenAIModule([triage_agent, general_agent, customer_support_agent])

runner = RESTAPI.run
