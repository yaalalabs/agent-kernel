"""
Hook implementations demonstrating pre-execution and post-execution hooks.

Pre-execution hooks:
- GuardRailHook: Validates input for guardrails
- RAGHook: Simulates RAG context injection

Post-execution hooks:
- DisclaimerHook: Adds disclaimer to agent responses
"""

from typing import Any

from agentkernel import Agent, PostHook, PreHook, Session
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestText


class GuardRailHook(PreHook):
    """
    Guardrail hook that validates user input before execution.

    This hook checks for inappropriate content, blocked topics, or harmful requests.
    If detected, it halts execution and returns a polite rejection message.
    """

    # List of blocked keywords/topics
    BLOCKED_KEYWORDS = [
        "hack",
        "illegal",
        "password",
        "exploit",
        "malware",
        "virus",
    ]

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        """
        Validates the prompt for inappropriate content.

        :param session: The session instance
        :param agent: The agent that will execute the prompt
        :param requests: requests to agent

        :return: AgentReply: If the hook decides to halt execution, it can return an AgentReply which will be sent
                 list[AgentRequest]: The modified requests or the input list. You can modify the requests in place without taking copies
                                      You can also add additional content to the requests list. e.g. files, images, etc.
        """
        # NOTE:  we are assuming single text request for simplicity
        if requests and isinstance(requests[0], AgentRequestText):
            prompt = requests[0].text
        else:
            return requests  # No text prompt to validate

        prompt_lower = prompt.lower()

        # Check for blocked keywords
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in prompt_lower:
                rejection_message = (
                    f"I apologize, but I cannot assist with requests related to '{keyword}'. "
                    "Please ask a different question that complies with ethical guidelines."
                )
                return AgentReplyText(text=rejection_message)

        # Check for excessively long inputs (potential abuse)
        if len(prompt) > 5000:
            return AgentReplyText(
                text="Your input is too long. Please keep your questions concise (under 5000 characters)."
            )
        # Prompt is safe - proceed with execution
        return requests

    def name(self) -> str:
        return "GuardRailHook"


class RAGHook(PreHook):
    """
    Simulated RAG (Retrieval-Augmented Generation) hook.

    This hook simulates retrieving relevant context from a knowledge base
    and injecting it into the prompt before execution. In a real implementation,
    this would query a vector database or document store.
    """

    # Simulated knowledge base
    KNOWLEDGE_BASE = {
        "agent kernel": (
            "Agent Kernel is a Python framework for building and deploying AI agents. "
            "It supports multiple frameworks including OpenAI, LangGraph, CrewAI, and ADK. "
            "Key features include session management, runtime orchestration, and multiple deployment modes."
        ),
        "hooks": (
            "Hooks in Agent Kernel are pre-execution and post-execution callbacks that allow "
            "you to modify prompts or responses. Pre-hooks can inject context (RAG) or validate input (guardrails). "
            "Post-hooks can modify agent replies or add disclaimers."
        ),
        "python": (
            "Python is a high-level, interpreted programming language known for its simplicity "
            "and readability. It's widely used in web development, data science, AI/ML, and automation."
        ),
        "openai": (
            "OpenAI is an AI research organization that developed GPT models and other AI tools. "
            "The OpenAI API provides access to language models like GPT-4 for various applications."
        ),
    }

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        """
        Simulates RAG by searching the knowledge base and injecting relevant context

        :param session: The session instance
        :param agent: The agent that will execute the prompt
        :param requests: requests to agent

        :return: AgentReply: If the hook decides to halt execution, it can return an AgentReply which will be sent
                 list[AgentRequest]: The modified requests or the input list. You can modify the requests in place without taking copies
                                      You can also add additional content to the requests list. e.g. files, images, etc.
        """
        # NOTE:  we are assuming single text request for simplicity
        if requests and isinstance(requests[0], AgentRequestText):
            prompt = requests[0].text
        else:
            return requests  # No text prompt to validate

        prompt_lower = prompt.lower()

        # Search for relevant context in the knowledge base
        relevant_contexts = []
        for topic, context in self.KNOWLEDGE_BASE.items():
            if topic in prompt_lower:
                relevant_contexts.append(f"[Context about {topic}]: {context}")

        # If we found relevant context, inject it into the prompt
        if relevant_contexts:
            context_block = "\n\n".join(relevant_contexts)
            enriched_prompt = f"""You have access to the following context information:

{context_block}

Please use this context to help answer the following question:
{prompt}

If the context is relevant, incorporate it into your answer. If not, answer based on your general knowledge."""

            return [AgentRequestText(text=enriched_prompt)]  # Note: We assume that there is only one text request

        # No relevant context found - proceed with original prompt
        return requests

    def name(self) -> str:
        return "RAGHook"


class DisclaimerHook(PostHook):
    """
    Post-execution hook that adds a disclaimer to agent responses.

    This hook demonstrates how post-hooks can modify agent replies to add
    compliance messages, disclaimers, or additional information.
    """

    # Disclaimer message to append
    DISCLAIMER = (
        "\n\n---\n"
        "*Disclaimer: This response is generated by an AI assistant and should be "
        "verified for accuracy. For critical decisions, please consult with a qualified "
        "professional in the relevant field.*"
    )

    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        """
        Adds a disclaimer to the agent's response.
        :param:  session (Session): The session instance.
        :param:  requests (list[AgentRequest]): The original requests provided to the agent after any pre-execution hooks have been applied.
        :param:  agent (Agent): The agent that executed the prompt.
        :param:  agent_reply (AgentReply): The reply to process. For the first posthook, this is the unmodified
                              agent reply. For subsequent posthooks, this is the reply modified by previous posthooks in the chain.
        :return: The modified reply with disclaimer appended
        """
        agent_reply.text = agent_reply.text + self.DISCLAIMER
        return agent_reply

    def name(self) -> str:
        return "DisclaimerHook"
