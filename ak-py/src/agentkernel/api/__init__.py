"""
Agent Kernel REST package.

This package contains the REST API implementation for exposing Agent Kernel over HTTP.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .auth import AuthValidator, ValidationContext, ValidationResult

try:
    # AuthValidator does not need these, these need fastapi and other libraries which are not available in AuthValidator as it doesn't need them
    from .handler import AgentRESTRequestHandler, RESTRequestHandler
    from .http import RESTAPI
except ImportError:
    pass
