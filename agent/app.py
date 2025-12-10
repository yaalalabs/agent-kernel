from agentkernel.api import RESTAPI
# from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

from tool import search_agent_kernel_docs

general_agent = Agent(
    name="general",
    instructions="You are an expert on Agent Kernel, a framework-agnostic runtime for building and deploying AI agents. "
                 "Use the search_agent_kernel_docs tool to find relevant information from the official documentation "
                 "to answer questions about Agent Kernel accurately. Always cite information from the documentation. "
                 "If you can't find relevant information in the docs, say so clearly. Don't answer anything outside Agent Kernel's scope."
                 "Agent kernel currently supports LangGraph, CrewAI, OpenAI Agents SDK and Google ADK as agentic frameworks. If any question is asked about these"
                 "frameworks, answer accordingly by linking Agent Kernel's relevance and integration with the framework.",
    tools=[search_agent_kernel_docs],
)

# Register the agent with Agent Kernel
OpenAIModule([general_agent])

if __name__ == "__main__":
    RESTAPI.run()
    # CLI.main()
