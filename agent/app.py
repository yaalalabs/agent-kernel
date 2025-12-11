import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic._internal._generate_schema")

from agentkernel.api import RESTAPI
# from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

from tool import search_agent_kernel_docs

general_agent = Agent(
    name="general",
    instructions="You are an expert on Agent Kernel, a framework-agnostic runtime for building and deploying AI agents. "
                 "Use the search_agent_kernel_docs tool to find relevant information from the official documentation "
                 "and code examples to answer questions about Agent Kernel accurately. "
                 "The search tool uses advanced RAG (Retrieval-Augmented Generation) to search through:\n"
                 "- All markdown documentation files\n"
                 "- All example projects (Python, TOML, YAML, shell scripts)\n"
                 "Always cite information from the documentation and examples. Always use OpenAI Agents SDK when user doesn't specify the framework."
                 "If you can't find relevant information, say so clearly. Don't answer anything outside Agent Kernel's scope. "
                 "Agent Kernel currently supports LangGraph, CrewAI, OpenAI Agents SDK and Google ADK as agentic frameworks. "
                 "It supports langfuse and traceloops openllmetry for for observability. It also supports various social integrations "
                 "including Slack, Messenger, Telegram and WhatsApp."
                 "When questions are asked about these frameworks, answer by linking Agent Kernel's relevance and integration. "
                 "Use the rebuild_knowledge_index tool only if specifically asked to refresh the documentation index.",
    tools=[search_agent_kernel_docs],
)

# Register the agent with Agent Kernel
OpenAIModule([general_agent])

runner = RESTAPI.run
