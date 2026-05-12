import json

from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. no reasoning and no need for steps explanation. Just give the final answer. \
        If prompted for anything else you refuse to answer.",
    model="openai/gpt-4.1-mini",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
    model="openai/gpt-4.1-mini",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[history_agent, math_agent],
    model="openai/gpt-4.1-mini",
)

OpenAIModule([triage_agent, math_agent, history_agent])


# Defining a custom handler function for a custom path
@Lambda.register("/app", method="GET")
def custom_app_handler(event, context):
    return {"receivedEventPayload": dict(event), "response": "Hello! from AK 'app'"}


@Lambda.register("/app_info", method="POST")
def custom_app_info_handler(event, context):
    payload = json.loads(event.get("body") or "{}")
    return {"receivedEventPayload": dict(event), "request": payload, "response": "Hello! from AK 'app_info'"}


handler = Lambda.handler
