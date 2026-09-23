"""Secret resolution: environment first, falling back to a managed store.

``SecretManager.current().get("OPENAI_API_KEY")`` resolves a key through the process environment,
then the process cache, then the configured ``SecretProvider`` (``secret.provider.type``). A set,
non-empty environment variable always wins, and a resolved value is never written back to the
environment — callers hand it to the SDK explicitly.

The reusable provider contract suite lives in ``agentkernel.secret.testing`` (it depends on pytest)
and the AWS SSM provider is reached through the factory behind the ``aws`` extra, so neither is
re-exported here.
"""

from . import errors
from .base import SecretProvider
from .cache import SecretCache
from .errors import SecretError, SecretNotFoundError
from .manager import SecretManager
from .providers.env import EnvSecretProvider

__all__ = [
    "errors",
    "EnvSecretProvider",
    "SecretCache",
    "SecretError",
    "SecretManager",
    "SecretNotFoundError",
    "SecretProvider",
]
