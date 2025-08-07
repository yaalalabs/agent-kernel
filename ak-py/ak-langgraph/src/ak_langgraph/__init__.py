"""
Agent Kernel support for LangGraph Agents SDK.

This package contains Agent Kernel support for agents built with LangGraph Agents SDK.
It provides the necessary classes and methods to integrate LangGraph agents into the Agent Kernel
framework, allowing for seamless interaction and execution of LangGraph based agents.
"""

__version__ = "0.1.0"

from .aklanggraph import LangGraphModule as AgentModule, LangGraphRunner as AgentRunner, LangGraphAgent as Agent
