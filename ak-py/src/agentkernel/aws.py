import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .deployment import aws as _deployment_aws

__all__ = _deployment_aws.__all__


def __getattr__(name):
    """Delegate to deployment.aws's own lazy __getattr__ so `from agentkernel.aws import Lambda`
    doesn't eagerly import the containerized (ECS) target, and vice versa."""
    return getattr(_deployment_aws, name)
