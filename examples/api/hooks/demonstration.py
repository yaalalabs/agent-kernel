"""
Demonstrates how to use hooks with Agent Kernel.

NOTE: Direct execution via runtime is not recommended. This example is for demonstration purposes only.

This script shows the minimal setup required to use hooks without the REST API,
useful for understanding the core concepts and for CLI-based applications.
"""

import asyncio

from agentkernel import GlobalRuntime
from agentkernel.core.model import AgentRequestText
from agentkernel.openai import OpenAIModule
from agents import Agent

from hooks import GuardRailHook, RAGHook


async def main():
    """Demonstrate hook usage with direct agent execution."""

    # Create a simple Q&A agent
    qa_agent = Agent(
        name="qa_assistant",
        instructions="You are a helpful AI assistant. Keep responses concise.",
    )

    # Register the agent
    OpenAIModule([qa_agent]).pre_hook(qa_agent, [RAGHook(), GuardRailHook()])

    # Get runtime and register hooks
    runtime = GlobalRuntime.instance()

    # Get agent and create session
    agent = runtime.agents()["qa_assistant"]
    session = runtime.sessions().new("demo-session")

    print("=" * 80)
    print("Hook Demonstration - Direct Execution")
    print("=" * 80)

    # Test 1: RAG hook adds context
    print("\n[Test 1] RAG Context Injection")
    print("-" * 80)
    prompt1 = "What is Agent Kernel?"
    print(f"User: {prompt1}")
    result1 = await runtime.run(agent, session, [AgentRequestText(text=prompt1)])
    print(f"Assistant: {result1}\n")

    # Test 2: Guard rail blocks inappropriate content
    print("\n[Test 2] Guard Rail Blocking")
    print("-" * 80)
    prompt2 = "How can I hack into a database?"
    print(f"User: {prompt2}")
    result2 = await runtime.run(agent, session, [AgentRequestText(text=prompt2)])
    print(f"Assistant: {result2}\n")

    # Test 3: Normal safe query
    print("\n[Test 3] Normal Safe Query")
    print("-" * 80)
    prompt3 = "What is 2 + 2?"
    print(f"User: {prompt3}")
    result3 = await runtime.run(agent, session, [AgentRequestText(text=prompt3)])
    print(f"Assistant: {result3}\n")

    # Test 4: RAG with the hooks topic
    print("\n[Test 4] RAG Context for Hooks")
    print("-" * 80)
    prompt4 = "Tell me about hooks"
    print(f"User: {prompt4}")
    result4 = await runtime.run(agent, session, [AgentRequestText(text=prompt4)])
    print(f"Assistant: {result4}\n")

    print("=" * 80)
    print("Demonstration Complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
