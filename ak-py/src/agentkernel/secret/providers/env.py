"""EnvSecretProvider — the default backend: the process environment."""

import os
from typing import Optional

from ..base import SecretProvider


class EnvSecretProvider(SecretProvider):
    """The default backend: os.environ as the store, the key IS the variable name, read verbatim.

    An empty variable is treated as absent, matching the manager's layer-1 rule."""

    def get_secret(self, key: str) -> Optional[str]:
        return os.environ.get(key) or None
