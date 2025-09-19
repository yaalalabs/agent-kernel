from google.adk.agents import Agent, LlmAgent

from ak.cli import CLI
from ak.google import GoogleADKModule

# Math specialist agent
math_agent = Agent(
    name="math",
    model="gemini-2.0-flash",
    description="Specialist agent for math questions",
    instruction="""
    You provide help with math problems.
    Explain your reasoning at each step and include examples.
    If prompted for anything else you refuse to answer.
    """,
)

# General purpose agent
history_agent = Agent(
    name="history",
    model="gemini-2.0-flash",
    description="Agent for history questions",
    instruction="""
    You provide assistance with history queries.
    Give short and direct answers.
    """,
)

triage_agent = LlmAgent(
    name="triage",
    model="gemini-2.0-flash",
    description="Agent that routes the user to the appropriate specialist agent (math or history).",
    instruction="""
    You determine which agent to use based on the user's question.
    If it's a math problem, issue an action.transfer_to_agent to the agent named "math".
    Otherwise, if it's history related query, transfer to "history".
    """,
    sub_agents=[history_agent, math_agent],
)

GoogleADKModule([triage_agent, math_agent, history_agent])

if __name__ == "__main__":
    CLI.main()
