"""The agents, shared by the request handler and the agent runner.

The agent runner (lambda_agent_runner.py) executes them. The request handler (lambda_request_handler.py) only
registers them: the A2A agent cards and the MCP agent tools are built from the agents registered in the process that
serves those routes. Each entry point registers them with its own OpenAIModule call.

Named lambda_agents rather than agents so it does not shadow the openai-agents ``agents`` package it imports.
"""

from agents import Agent

assistant = Agent(
    name="assistant",
    instructions="You are a helpful assistant. Keep answers short and follow instructions exactly.",
    model="openai/gpt-4.1-mini",
)
