from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details.",
)

general_agent = Agent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details",
)

triage_agent = Agent(
    name="triage",
    instructions="You determine which agent to use based on the user's question. Give short and direct answers exactly to the question. "
    "Don't provide any explanations nor additional details",
    handoffs=[general_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, general_agent])

if __name__ == "__main__":
    CLI.main()
