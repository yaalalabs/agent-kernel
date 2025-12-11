"""This package contains the Agent Kernel integration implementations for Telegram Bot API."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .telegram_chat import AgentTelegramRequestHandler
