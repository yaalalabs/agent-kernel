"""
Hook implementations demonstrating pre-execution hooks for guard rails and RAG simulation.
"""

from agentkernel.core.hooks import Prehook
from agentkernel.core.base import Session, Agent


class GuardRailHook(Prehook):
    """
    Guard rail hook that validates user input before execution.
    
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
    
    def on_pre_execution(self, session: Session, agent: Agent, original_prompt: str, prompt: str) -> tuple[bool, str]:
        """
        Validates the prompt for inappropriate content.
        
        Args:
            session: The session instance
            agent: The agent that will execute the prompt
            original_prompt: The original unmodified prompt
            prompt: The current prompt (possibly modified by previous hooks)
        
        Returns:
            tuple[bool, str]: (proceed, modified_prompt)
                - proceed: False if guard rail triggered, True otherwise
                - modified_prompt: Rejection message if halted, or original prompt if safe
        """
        prompt_lower = prompt.lower()
        
        # Check for blocked keywords
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in prompt_lower:
                rejection_message = (
                    f"I apologize, but I cannot assist with requests related to '{keyword}'. "
                    "Please ask a different question that complies with ethical guidelines."
                )
                return False, rejection_message
        
        # Check for excessively long inputs (potential abuse)
        if len(prompt) > 5000:
            return False, "Your input is too long. Please keep your questions concise (under 5000 characters)."
        
        # Prompt is safe - proceed with execution
        return True, prompt
    
    def name(self) -> str:
        return "GuardRailHook"


class RAGHook(Prehook):
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
            "you to modify prompts or responses. Pre-hooks can inject context (RAG) or validate input (guard rails). "
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
    
    def on_pre_execution(self, session: Session, agent: Agent, original_prompt: str, prompt: str) -> tuple[bool, str]:
        """
        Simulates RAG by searching the knowledge base and injecting relevant context.
        
        Args:
            session: The session instance
            agent: The agent that will execute the prompt
            original_prompt: The original unmodified prompt
            prompt: The current prompt (possibly modified by previous hooks)
        
        Returns:
            tuple[bool, str]: (True, enriched_prompt) - always proceeds with enriched prompt
        """
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
            
            return True, enriched_prompt
        
        # No relevant context found - proceed with original prompt
        return True, prompt
    
    def name(self) -> str:
        return "RAGHook"
