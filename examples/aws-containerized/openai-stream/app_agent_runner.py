from agentkernel.aws import ECSAgentRunner
from agentkernel.openai import OpenAIModule
from agents import Agent

math_agent = Agent(
    name="math",
    handoff_description="Specialist agent for math questions",
    instructions="You provide help with math problems. Do not provide reasoning or step-by-step explanations. Just give the final answer. \
         If prompted for anything else, refuse to answer.",
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
    model="openai/gpt-4.1-mini",
    handoffs=[history_agent, math_agent],
)

OpenAIModule([triage_agent, math_agent, history_agent])

# Agent Runner entrypoint. ECSAgentRunner resolves to ECSStreamAgentRunner at import time because
# config.yaml sets execution.mode: stream — it polls the Input Queue, runs the agent, and fans out
# each streamed token delta as its own message on the Output Queue (instead of one full reply).
handler = ECSAgentRunner.run

if __name__ == "__main__":
    handler()
