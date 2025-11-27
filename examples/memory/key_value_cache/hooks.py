"""
Hook implementations demonstrating pre-execution and post-execution hooks.

Pre-execution hooks:
- RAGHook: Simulates adding extra information to a vector store for a tool use
"""

import os
from typing import Any

from agentkernel import Agent, Posthook, Prehook, Session, KeyValueCache, Runtime


class RAGHook(Prehook):
    """
    Simulated RAG (Retrieval-Augmented Generation) hook.

    This hook simulates retrieving relevant context from a knowledge base based on the input prompt
    and injecting it into the auxiliary memory to be used by the agent tool during execution.
    """

    # Simulated knowledge base
    KNOWLEDGE_BASE = {
        "AcmeXXLabs": (
            "AcmeXXLabs is cutting-edge green technology solution provider. Its headquarters is in San Francisco"
        ),
        "SoftYYLabs": (
            "SoftYYLabs is a leading Thorium based research agency. Its headquarters is in Shandong, China"
        ),
    }

    async def on_run(
        self, session: Session, agent: Agent, original_prompt: str, prompt: str, additional_context: Any | None = None
    ) -> tuple[bool, str]:
        """
        Simulates injecting of additional information into the memory to be used by the agent tool during execution.
        """
        # Search for relevant context in the knowledge base
        relevant_contexts = []
        for topic, context in self.KNOWLEDGE_BASE.items():
            if topic in prompt:
                relevant_contexts.append({topic: context})

        cache:KeyValueCache = session.get_volatile_cache()
        cache.set("rag_context", relevant_contexts)
        print(f"RAGHook: Injected context into volatile cache: {relevant_contexts}")
        
        return True, prompt

    def name(self) -> str:
        return "RAGHook"

