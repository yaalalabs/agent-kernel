"""The SecretProvider seam: where a secret value lives."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core.config import _SecretConfig


class SecretProvider(ABC):
    """A backend that holds secrets, addressed by an environment-variable-style key."""

    @classmethod
    def create(cls, config: "_SecretConfig") -> "SecretProvider":
        """Build the provider from the `secret` block. Providers needing no settings inherit this default.

        :raises AKConfigError: If the settings this provider needs are missing or malformed.
        """
        return cls()

    @abstractmethod
    def get_secret(self, key: str) -> Optional[str]:
        """Return the value stored for `key`, or None when this backend does not have it.

        Must not cache or fall back to another layer, and must tolerate concurrent calls.

        :raises SecretError: If the backend failed (as opposed to not holding the value).
        """
        raise NotImplementedError

    def describe(self, key: str) -> Optional[str]:
        """Where this backend looks for `key`, for error messages that tell the user what to create.

        For example "SSM parameter /ak/myapp-dev/openai_api_key". None when the backend reads nothing
        beyond the environment variable SecretManager always checks first. Must not perform I/O or raise.
        """
        return f"the '{key}' entry in {type(self).__name__}"
