"""
Agent Kernel Core.

This package contains the Agent Kernel tracing implementation.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("ak")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .config import _TracingConfig
from .enums_and_mappings import TracingProviderEnum
from .tracers import Tracer
from .engine import get_tracer