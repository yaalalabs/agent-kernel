"""
Agent Kernel Auth package.

This package contains the Auth implementation for exposing Agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .token_validator import AuthTokenValidator, ValidationContext, ValidationResult
from .gateway_authorizer import APIGatewayAuthorizer, APIGatewayRequestAuthorizerEvent