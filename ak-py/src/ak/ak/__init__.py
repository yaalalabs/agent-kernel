"""
Agent Kernel.

This package contains the Agent Kernel implementation including the base API and a CLI front-end.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("ak")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .ak import Agent, Module, Runner, Runtime, Session
from .akcli import CLI
