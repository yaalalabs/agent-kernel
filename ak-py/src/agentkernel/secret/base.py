"""The SecretProvider seam: where a secret value lives."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core.config import _SecretConfig


class SecretProvider(ABC):
    """A backend that holds secrets, addressed by an environment-variable-style key."""

    @classmethod
    def from_config(cls, config: "_SecretConfig") -> "SecretProvider":
        """Build the provider from the `secret` block.

        The whole block, not just `secret.provider`: `secret.prefix` is a deployment-wide scope that
        more than one backend can key off (SSM today, Secrets Manager or Key Vault later), so it
        stays one field rather than being redeclared per provider. A provider needing no settings
        inherits this default and ignores the block (the ScheduleProvider.from_config precedent).

        :raises AKConfigError: If the settings this provider needs are missing or malformed.
        """
        return cls()

    @abstractmethod
    def get_secret(self, key: str) -> Optional[str]:
        """Return the value stored for `key`, or None when this backend does not have it.

        The provider owns its own addressing — it translates `key` to whatever its backend uses —
        and it never caches and never falls back to another layer. It MUST tolerate concurrent
        calls.

        :raises SecretError: If the backend failed (as opposed to not holding the value).
        """
        raise NotImplementedError
