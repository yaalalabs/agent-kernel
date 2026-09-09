"""
Agent Kernel GCP Cloud Run deployment package.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .akauthorizer import GCPAuthorizer
from .akcloudrun import CloudRun
