"""
Agent Kernel.

This package contains the Agent Kernel AWS lambda implementation.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("ak")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .aklambda import Lambda
