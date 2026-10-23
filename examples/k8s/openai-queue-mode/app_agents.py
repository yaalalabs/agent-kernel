"""The agents, loaded by both processes.

The agent runner (app_agent_runner.py) executes them. The io handler (app_io_handler.py) only
registers them, because A2A cards and MCP agent tools are built from the agents registered in the
process that serves those routes. The OpenAI key is set by the runner alone: the io handler never
runs a model.

Named app_agents rather than agents so it does not shadow the openai-agents ``agents`` package it
imports.
"""

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
