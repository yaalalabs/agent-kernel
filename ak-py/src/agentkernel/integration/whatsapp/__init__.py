"""
Agent Kernel Integration with WhatsApp

This package contains the Agent Kernel integration implementations for Whats App chats.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .whatsapp_chat import AgentWhatsAppRequestHandler
