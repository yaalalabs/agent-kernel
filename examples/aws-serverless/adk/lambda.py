from agentkernel.adk import GoogleADKModule
from agentkernel.aws import Lambda
from google.adk.agents import Agent, LlmAgent
from google.adk.models.lite_llm import LiteLlm

# Math specialist agent
math_agent = Agent(
    name="math",
    model=LiteLlm(model="openai/gpt-4.1-mini"),
    description="Specialist agent for math questions",
    instruction="""
    You provide help with math problems.
    Do not provide reasoning or step-by-step explanations. Just give the final answer.
    If prompted for anything else, refuse to answer.
    """,
)

# General purpose agent
history_agent = Agent(
    name="history",
    model=LiteLlm(model="openai/gpt-4.1-mini"),
    description="Agent for history questions",
    instruction="""
    You provide assistance with history queries.
    Give short and direct answers.
    """,
)

triage_agent = LlmAgent(
    name="triage",
    model=LiteLlm(model="openai/gpt-4.1-mini"),
    description="Agent that routes the user to the appropriate specialist agent (math or history).",
    instruction="""
    You determine which agent to use based on the user's question.
    If it's a math problem, issue an action.transfer_to_agent to the agent named "math".
    Otherwise, if it's history related query, transfer to "history".
    """,
    sub_agents=[history_agent, math_agent],
)

GoogleADKModule([triage_agent, math_agent, history_agent])

handler = Lambda.handler
