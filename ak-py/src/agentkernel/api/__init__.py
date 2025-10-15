"""
Agent Kernel REST package.

This package contains the REST API implementation for exposing Agent Kernel over HTTP.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .restapi import RESTAPI
