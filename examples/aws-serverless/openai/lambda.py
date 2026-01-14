import json

from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
)

history_agent = Agent(
    name="history",
    handoff_description="Specialist agent for historical questions",
    instructions="You provide assistance with historical queries. Explain important events and context clearly.",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question.",
    handoffs=[history_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, history_agent])

# Lambda.override_base_paths(api_base_path="api-new", api_version="v2", agent_endpoint="chat-new")


@Lambda.register("/app", method="GET")
def custom_app_handler(event, context):
    return {"recievedEventPayload": dict(event), "response": "Hello! from AK"}


@Lambda.register("/app", method="POST")
def custom_app_info_handler(event, context):
    payload = json.loads(event.get("body") or "{}")
    return {"recievedEventPayload": dict(event), "request": payload, "response": "Hello! from AK"}


handler = Lambda.handler
